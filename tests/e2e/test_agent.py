"""Optional AI assistant: gating, tool scoping, redaction, bounded loop, number checks. No real provider calls."""
import json
import time

import pytest
from fastapi.testclient import TestClient

from api_helpers import H, run_scenario
from conftest import data_root
from nodal_agent_tools.providers import ScriptedProvider
from nodal_api.config import Settings
from nodal_api.main import create_app
from nodal_api.services.agent import LIMITER
from nodal_domain.enums import Role
from nodal_domain.permissions import Principal, find_forbidden

B1 = "demo.buyer001.planner"
BUYER = Principal(B1, "BUY-000001", Role.BUYER_PLANNER, frozenset({"TEN-000001"}))


def call(name, args, cid="c1", raw=None):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": raw if raw is not None else json.dumps(args)}}


def tools_msg(*calls):
    return {"message": {"role": "assistant", "content": "", "tool_calls": list(calls)}, "finish_reason": "tool_calls"}


def answer(text):
    return {"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}


@pytest.fixture(autouse=True)
def _reset_limiter():
    LIMITER._hits.clear()
    yield
    LIMITER._hits.clear()


def make_client(tmp_path, provider, **settings_kw):
    s = Settings(env="test", demo_mode=True, data_root=data_root().resolve(),
                 db_url=f"sqlite:///{(tmp_path / 'ai.db').as_posix()}", inline_worker=True, **settings_kw)
    c = TestClient(create_app(s))
    c.__enter__()
    c.app.state.agent_provider_factory = lambda: provider
    return c


def ask(c, question, case_id=None, principal=B1, code=None, expect=202):
    headers = H(principal, **({"X-AI-Access-Code": code} if code else {}))
    r = c.post("/api/v1/agent/ask", json={"question": question, "case_id": case_id}, headers=headers)
    assert r.status_code == expect, r.text
    return r.json()


def wait_agent(c, agent_run_id, principal=B1, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        r = c.get(f"/api/v1/agent/runs/{agent_run_id}", headers=H(principal)).json()
        if r["state"] not in ("QUEUED", "RUNNING"):
            return r
        time.sleep(0.1)
    raise AssertionError("agent run did not finish")


def tool_messages(provider):
    return [json.loads(m["content"]) if m["content"].startswith(("{", "[")) else m["content"]
            for p in provider.sent for m in p["messages"] if m["role"] == "tool"]


def assert_no_leaks(provider):
    for p in provider.sent:
        for m in p["messages"]:
            if m["role"] == "tool":
                assert find_forbidden(BUYER, json.loads(m["content"])) == []


def test_disabled_without_provider(store, tmp_path):
    c = make_client(tmp_path, None)
    try:
        assert c.get("/api/v1/agent/status").json()["enabled"] is False
        ask(c, "What is happening?", expect=503)
        assert c.get("/api/v1/cases", headers=H(B1)).status_code == 200  # rest of the app unaffected
    finally:
        c.__exit__(None, None, None)


def test_answer_from_tools_with_verified_numbers(store, tmp_path):
    p = ScriptedProvider([tools_msg(call("get_case_evidence", {"case_id": "CASE-000004"})),
                          answer("CASE-000004 needs 600 and 400 units in 2026-11-23 from one shared machine.")])
    c = make_client(tmp_path, p)
    try:
        out = wait_agent(c, ask(c, "Why is CASE-000004 short?", "CASE-000004")["agent_run_id"])
        assert out["state"] == "COMPLETED" and out["unverified_numbers"] == []
        assert out["trace"][0]["tool"] == "get_case_evidence" and out["trace"][0]["ok"] is True
        assert_no_leaks(p)
        events = c.get("/api/v1/cases/CASE-000004/events", headers=H(B1)).json()["items"]
        assert "agent.tool.get_case_evidence" in [e["action"] for e in events]
    finally:
        c.__exit__(None, None, None)


def test_invented_numbers_are_flagged(store, tmp_path):
    p = ScriptedProvider([tools_msg(call("get_case_evidence", {"case_id": "CASE-000004"})),
                          answer("Fixing this will save €98,765.43.")])
    c = make_client(tmp_path, p)
    try:
        out = wait_agent(c, ask(c, "How much will we save?")["agent_run_id"])
        assert out["unverified_numbers"] == ["98,765.43"]
    finally:
        c.__exit__(None, None, None)


def test_cross_tenant_case_returns_not_found_to_the_model(store, tmp_path):
    p = ScriptedProvider([tools_msg(call("get_case_evidence", {"case_id": "CASE-000002"})), answer("I cannot see that case.")])
    c = make_client(tmp_path, p)
    try:
        wait_agent(c, ask(c, "Tell me about CASE-000002")["agent_run_id"])
        assert tool_messages(p) == [{"error": "not_found"}]
        ask(c, "Tell me about CASE-000002", "CASE-000002", expect=404)  # case context is access-checked too
    finally:
        c.__exit__(None, None, None)


def test_multi_buyer_results_hide_other_tenant(store, tmp_path):
    p = ScriptedProvider([])
    c = make_client(tmp_path, p)
    try:
        run_id = run_scenario(c, B1, "CASE-000010", modes=["overtime"])["run_id"]
        p.responses = [tools_msg(call("get_scenario_results", {"run_id": run_id})), answer("Done.")]
        wait_agent(c, ask(c, "Summarise the run")["agent_run_id"])
        content = json.dumps(tool_messages(p))
        assert "LANE-000021" not in content and "TEN-000002" not in content
        assert_no_leaks(p)
    finally:
        c.__exit__(None, None, None)


def test_invalid_arguments_and_unknown_tools_do_not_crash(store, tmp_path):
    p = ScriptedProvider([tools_msg(call("get_case_evidence", None, raw="{not json"), call("delete_everything", {}, cid="c2")),
                          answer("Recovered.")])
    c = make_client(tmp_path, p)
    try:
        out = wait_agent(c, ask(c, "Try things")["agent_run_id"])
        assert out["state"] == "COMPLETED"
        assert [t["ok"] for t in out["trace"]] == [False, False]
    finally:
        c.__exit__(None, None, None)


def test_loop_is_bounded_and_last_round_offers_no_tools(store, tmp_path):
    p = ScriptedProvider([tools_msg(call("list_cases", {}, cid=f"c{i}")) for i in range(10)])
    c = make_client(tmp_path, p)
    try:
        out = wait_agent(c, ask(c, "Loop forever")["agent_run_id"])
        assert len(p.sent) == 4 and p.sent[-1]["tools"] == []
        assert out["state"] in ("STOPPED", "COMPLETED")
    finally:
        c.__exit__(None, None, None)


def test_request_scenario_at_most_once_and_draft_creates_nothing(store, tmp_path):
    p = ScriptedProvider([])
    c = make_client(tmp_path, p)
    try:
        res = run_scenario(c, B1, "CASE-000004", modes=["alternate"])
        alt = next(r for r in res["results"]["alternate"]["releases"] if r["role"] == "ALTERNATE")
        p.responses = [tools_msg(call("request_scenario", {"case_id": "CASE-000004"}, "a"),
                                 call("request_scenario", {"case_id": "CASE-000004"}, "b"),
                                 call("draft_offer_text", {"run_id": res["run_id"], "mode": "alternate",
                                                           "recipient_org_id": alt["supplier_org_id"]}, "c")),
                       answer("Queued one run and drafted text.")]
        wait_agent(c, ask(c, "Re-run and draft a message")["agent_run_id"])
        msgs = tool_messages(p)
        assert msgs[0]["status"] == "QUEUED" and msgs[1] == {"error": "only one scenario request per question"}
        assert msgs[2]["requested_lines"] and "No offer was created" in msgs[2]["note"]
        runs = c.get("/api/v1/cases/CASE-000004/scenario-runs", headers=H(B1)).json()["items"]
        assert len(runs) == 2  # the explicit run + exactly one from the assistant
        assert c.get("/api/v1/cases/CASE-000004/offers", headers=H(B1)).json()["items"] == []
    finally:
        c.__exit__(None, None, None)


def test_access_code_roles_ownership_and_rate_limit(store, tmp_path):
    p = ScriptedProvider([answer("ok")] * 5)
    c = make_client(tmp_path, p, ai_access_code="demo-code", ai_hourly_limit=1)
    try:
        assert c.get("/api/v1/agent/status").json()["requires_access_code"] is True
        ask(c, "hello", expect=403)
        ask(c, "hello", code="wrong", expect=403)
        rid = ask(c, "hello", code="demo-code")["agent_run_id"]
        ask(c, "again", code="demo-code", expect=429)
        ask(c, "hello", principal="demo.supplier0001.planner", code="demo-code", expect=403)
        ask(c, "hello", principal="demo.platform.ops", code="demo-code", expect=403)
        wait_agent(c, rid)
        assert c.get(f"/api/v1/agent/runs/{rid}", headers=H("demo.buyer001.procurement")).status_code == 404
    finally:
        c.__exit__(None, None, None)
