"""Tenant isolation, role matrix and field-leak negative tests (blueprint §15, §19.3)."""
import pytest

from api_helpers import H, run_scenario
from nodal_domain.enums import Role
from nodal_domain.permissions import Principal, can_read_record, find_forbidden

B1, B2, OPS = "demo.buyer001.planner", "demo.buyer002.planner", "demo.platform.ops"


def test_policy_expectations_from_generator(store):
    rows = [r for r in store.policy_expectations() if "principal" in r and "record" in r]
    assert rows
    for r in rows:
        p = r["principal"]
        principal = Principal(p["principal_id"], p["org_id"], Role(p["role"]), frozenset([p["tenant_scope"]]))
        got = "ALLOW" if can_read_record(principal, r["entity"], r["record"]) else "DENY"
        assert got == r["expected"], r["test_id"]


def test_cross_tenant_case_is_indistinguishable_from_missing(client):
    other = client.get("/api/v1/cases/CASE-000002", headers=H(B1))  # tenant 2's case
    missing = client.get("/api/v1/cases/CASE-999999", headers=H(B1))
    assert other.status_code == missing.status_code == 404
    assert other.json() == missing.json()
    ids = [c["case_id"] for c in client.get("/api/v1/cases?q=CASE-000002", headers=H(B1)).json()["items"]]
    assert "CASE-000002" not in ids
    assert client.get("/api/v1/network/impact?case_id=CASE-000002", headers=H(B1)).status_code == 404
    assert client.post("/api/v1/cases/CASE-000002/scenarios", json={"modes": ["baseline"]}, headers=H(B1)).status_code == 404


def test_cross_tenant_run_and_agreement_ids_are_concealed(client):
    res = run_scenario(client, B2, "CASE-000002", modes=["baseline"])
    assert client.get(f"/api/v1/scenario-runs/{res['run_id']}", headers=H(B1)).status_code == 404
    assert client.get(f"/api/v1/scenario-runs/{res['run_id']}/results", headers=H(B1)).status_code == 404


def test_buyer_results_never_contain_supplier_private_fields(client):
    res = run_scenario(client, B1, "CASE-000004")
    buyer = Principal(B1, "BUY-000001", Role.BUYER_PLANNER, frozenset({"TEN-000001"}))
    assert find_forbidden(buyer, res) == []
    case = client.get("/api/v1/cases/CASE-000004", headers=H(B1)).json()
    assert find_forbidden(buyer, case) == []
    graph = client.get("/api/v1/network/impact?case_id=CASE-000004", headers=H(B1)).json()
    assert find_forbidden(buyer, graph) == [] and len(graph["nodes"]) <= graph["max_nodes"]


def test_multi_buyer_case_hides_other_tenant_lines_and_prices(client):
    res = run_scenario(client, B1, "CASE-000010", modes=["overtime"])
    r = res["results"]["overtime"]
    assert all(x["tenant_id"] in ("TEN-000001", None) for x in r["releases"])
    assert all(x["tenant_id"] == "TEN-000001" for x in r["item_weeks"])
    assert all(v["tenant_id"] == "TEN-000001" for v in r["lane_provenance"].values())
    k = r["kpis"]
    assert k["overtime_units"] == sum(x["overtime_units"] for x in r["releases"])
    assert k["primary_units"] == sum(x["regular_units"] + x["overtime_units"] for x in r["releases"] if x["role"] == "PRIMARY")
    # Other buyer's economics must not appear in (or steer) this buyer's numbers.
    assert all(v["provenance"] != "other relationship - economics withheld (resource claim only)" for v in r["lane_provenance"].values())
    assert any("other buyers share a supplier resource" in a for a in r["assumptions"])
    fixture = client.get("/api/v1/cases/CASE-000010", headers=H(B1)).json()["fixture"]
    assert fixture["other_relationships_on_shared_resource"] == 1
    assert all(line["lane_id"] != "LANE-000021" for line in fixture["lines"])


def test_supplier_cannot_read_scenarios_or_unsent_cases(client):
    res = run_scenario(client, B1, "CASE-000004", modes=["baseline"])
    sup = "demo.supplier0018.planner"
    assert client.get(f"/api/v1/scenario-runs/{res['run_id']}", headers=H(sup)).status_code == 403
    assert client.get("/api/v1/cases/CASE-000004", headers=H(sup)).status_code == 404
    assert client.get("/api/v1/cases", headers=H(sup)).json()["items"] == []


def test_supplier_offer_view_has_no_buyer_confidential_fields(client):
    res = run_scenario(client, B1, "CASE-000005", modes=["overtime"])
    rel = next(r for r in res["results"]["overtime"]["releases"] if r["overtime_units"])
    offer = client.post("/api/v1/cases/CASE-000005/offers", headers=H(B1),
                        json={"run_id": res["run_id"], "mode": "overtime", "recipient_org_id": rel["supplier_org_id"]}).json()
    client.post(f"/api/v1/offers/{offer['offer_id']}/send", headers=H("demo.buyer001.procurement"), json={})
    sup_id = next(p["principal_id"] for p in client.get("/api/v1/session/principals").json()["items"]
                  if p["org_id"] == rel["supplier_org_id"] and p["role"] == "SUPPLIER_PLANNER")
    view = client.get("/api/v1/cases/CASE-000005", headers=H(sup_id)).json()
    supplier = Principal(sup_id, rel["supplier_org_id"], Role.SUPPLIER_PLANNER, frozenset({"TEN-000001"}))
    assert find_forbidden(supplier, view, allow_own_supplier=True) == []
    assert view["offers"][0]["your_private_evaluation"]["visible_to"] == rel["supplier_org_id"]
    # ...and the buyer never sees the supplier's private evaluation.
    buyer_offers = client.get("/api/v1/cases/CASE-000005/offers", headers=H(B1)).json()
    assert "your_private_evaluation" not in str(buyer_offers)


def test_platform_operator_metadata_only_and_cannot_act(client):
    assert client.get("/api/v1/cases", headers=H(OPS)).json()["items"] == []
    assert client.get("/api/v1/cases/CASE-000001", headers=H(OPS)).status_code == 404
    m = client.get("/api/v1/metrics/resolution", headers=H(OPS)).json()
    assert m["scope"] == "PLATFORM_METADATA" and "unit_price" not in str(m) and "CASE-" not in str(m)
    assert client.post("/api/v1/agreements/AGR-X/approvals", headers=H(OPS), json={"decision": "APPROVE", "terms_digest": "x"}).status_code == 404
    assert client.post("/api/v1/cases/CASE-000001/scenarios", json={}, headers=H(OPS)).status_code == 403


def test_missing_or_unknown_identity_is_rejected(client):
    assert client.get("/api/v1/cases").status_code == 401
    assert client.get("/api/v1/cases", headers=H("demo.nobody")).status_code == 401


def test_demo_mode_cannot_start_in_production(monkeypatch):
    from nodal_api.config import ConfigError, load_settings

    monkeypatch.setenv("NODAL_ENV", "production")
    monkeypatch.setenv("DEMO_MODE", "true")
    with pytest.raises(ConfigError):
        load_settings()


def test_imports_validate_reconcile_and_are_idempotent(client):
    svc = "demo.integration.service"
    a = client.post("/api/v1/imports", json={"connector": "mock_collaboration"}, headers=H(svc))
    assert a.status_code == 201, a.text
    body = a.json()
    recon = body["report"]["reconciliation"][0]
    assert recon["matched"] == body["accepted_count"] and recon["differences"] == 0
    b = client.post("/api/v1/imports", json={"connector": "mock_collaboration"}, headers=H(svc)).json()
    assert b["import_id"] == body["import_id"] and b["idempotent_replay"] is True
    erp = client.post("/api/v1/imports", json={"connector": "mock_erp"}, headers=H(svc)).json()
    entities = {e["entity"]: e for e in erp["report"]["entities"]}
    assert {"demand_forecast", "inventory_positions"} <= set(entities)
    for rc in erp["report"]["reconciliation"]:
        assert rc["differences"] == 0, rc
    assert client.post("/api/v1/imports", json={"connector": "mock_erp"}, headers=H("demo.supplier0001.planner")).status_code == 403
