"""AI tool gateway (blueprint §16): tools bound server-side to the requesting principal.

- Each tool calls the same principal-scoped views as the HTTP API, so the model sees exactly what this user may see.
- Every tool output passes a second field-level redaction before it reaches the model (defense in depth).
- No tool sends, accepts, approves or edits anything. request_scenario only queues a solver job (max once per question).
- Every tool call is written to the audit trail.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy import select, update

from nodal_agent_tools.loop import Tool, run_agent
from nodal_domain.enums import Role
from nodal_domain.permissions import Principal, forbidden_fields_for

from ..db import AgentRun, utcnow
from ..schemas import ScenarioRequest
from .audit import audit
from .cases import load_case
from .offers import derive_lines
from .views import case_runs_view, case_view, enqueue_scenario, list_cases_view, load_run, run_view

MODES = ["baseline", "overtime", "alternate", "prebuild", "hybrid"]
FIN_KEYS = ("incremental_buyer_cost_eur", "purchase_spend_eur", "premium_spend_eur", "overtime_premium_eur",
            "alternate_price_delta_eur", "holding_cost_eur", "working_capital_peak_eur", "shortage_exposure_proxy_eur", "currency")


# ---- rate limiting (per process; protects the owner's API balance on a public demo) ------------------------------
class HourlyLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._hits: deque[float] = deque()

    def allow(self, limit: int) -> bool:
        now = time.time()
        with self._lock:
            while self._hits and now - self._hits[0] > 3600:
                self._hits.popleft()
            if len(self._hits) >= limit:
                return False
            self._hits.append(now)
            return True


LIMITER = HourlyLimiter()


def principal_from_id(store, principal_id: str) -> Principal | None:
    row = store.principals.get(principal_id)
    if row is None:
        return None
    return Principal(row["principal_id"], row["org_id"], Role(row["role"]), frozenset(row["tenant_scopes"]))


def make_redactor(principal: Principal) -> Callable[[Any], tuple[Any, list[str]]]:
    forbidden = forbidden_fields_for(principal)

    def redact(obj: Any) -> tuple[Any, list[str]]:
        removed: list[str] = []

        def walk(node: Any, path: str) -> Any:
            if isinstance(node, dict):
                out = {}
                for k, v in node.items():
                    if k in forbidden:
                        removed.append(f"{path}.{k}")
                        continue
                    out[k] = walk(v, f"{path}.{k}")
                return out
            if isinstance(node, list):
                return [walk(v, f"{path}[{i}]") for i, v in enumerate(node)]
            return node

        return walk(obj, "$"), removed

    return redact


# ---- tool implementations ----------------------------------------------------------------------------------------
def _summarize_case(view: dict[str, Any], runs: dict[str, Any]) -> dict[str, Any]:
    items = []
    for it in view["snapshot_horizon"]["items"]:
        items.append({k: it[k] for k in ("part_id", "plant_id", "opening_usable", "baseline_first_shortage_week",
                                         "disrupted_first_shortage_week", "baseline_peak_backlog", "disrupted_peak_backlog")}
                     | {"affected_confirmed_receipts": len(it["affected_receipts"])})
    return {"case": view["case"], "disruption": view["disruption"], "case_scope": view["fixture"],
            "suppliers": view["suppliers"], "twelve_week_items": items,
            "recent_scenario_runs": [{k: r.get(k) for k in ("run_id", "state", "status", "stale", "created_at")}
                                     | {"scope": (r.get("request") or {}).get("scope")} for r in runs["items"][:5]]}


def _summarize_results(env: dict[str, Any]) -> dict[str, Any]:
    out = {"run_id": env["run_id"], "case_id": env["case_id"], "state": env["state"], "overall_status": env["status"],
           "stale": env.get("stale"), "modes": {}}
    for mode, r in (env.get("results") or {}).items():
        fin = r.get("financials") or {}
        out["modes"][mode] = {
            "status": r["status"], "message": r["message"], "offer_eligible": r["offer_eligible"], "kpis": r["kpis"],
            "financials": {k: fin.get(k) for k in FIN_KEYS if k in fin},
            "solver_relative_gap": r["solver"].get("relative_gap"),
            "binding_constraints": r["binding_constraints"], "warnings": r["warnings"], "diagnostics": r["diagnostics"],
            "allocations": [{k: x[k] for k in ("lane_id", "supplier_org_id", "role", "part_id", "release_week", "arrival_week",
                                               "regular_units", "overtime_units")} for x in r["releases"][:10]],
        }
    return out


def _compare(env: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for mode, r in (env.get("results") or {}).items():
        fin = r.get("financials") or {}
        rows.append({"mode": mode, "status": r["status"], "offer_eligible": r["offer_eligible"],
                     "unmet_units_at_end": r["kpis"].get("unmet_units_at_end"), "late_unit_weeks": r["kpis"].get("late_unit_weeks"),
                     "alternate_units": r["kpis"].get("alternate_units"), "overtime_units": r["kpis"].get("overtime_units"),
                     "incremental_buyer_cost_eur": fin.get("incremental_buyer_cost_eur"),
                     "shortage_exposure_proxy_eur": fin.get("shortage_exposure_proxy_eur"),
                     "solver_relative_gap": r["solver"].get("relative_gap")})
    ok = [x for x in rows if x["offer_eligible"] and x["unmet_units_at_end"] is not None]
    ok.sort(key=lambda x: (x["unmet_units_at_end"], float(x["incremental_buyer_cost_eur"] or 0)))
    return {"run_id": env["run_id"], "case_id": env["case_id"], "stale": env.get("stale"), "modes": rows,
            "suggested_by_rule": ok[0]["mode"] if ok else None,
            "rule": "fewest unmet units, then lowest incremental buyer cost, among validated plans (computed by the server)"}


def build_tools(sessions, store, settings, principal: Principal, *, agent_run_id: str, wake: Callable[[], None]) -> list[Tool]:
    state = {"scenarios_requested": 0}

    def guarded(name: str, fn: Callable[[Any, dict[str, Any]], Any]) -> Callable[[dict[str, Any]], Any]:
        def call(args: dict[str, Any]) -> Any:
            with sessions() as s:
                try:
                    result = fn(s, args)
                    decision = "ALLOW"
                except HTTPException as exc:
                    result = {"error": "not_found" if exc.status_code == 404 else exc.detail}
                    decision = "DENY" if exc.status_code in (403, 404) else "ERROR"
                audit(s, principal, action=f"agent.tool.{name}", resource_type="agent_run", resource_id=agent_run_id,
                      decision=decision, case_id=args.get("case_id") if isinstance(args.get("case_id"), str) else None,
                      payload=args, summary=f"AI assistant called {name}")
                s.commit()
                return result
        return call

    def t_list(s, a):
        v = list_cases_view(s, principal, state=a.get("state"), q=a.get("query"), limit=30)
        return {"total": v["total"], "cases": [{k: c.get(k) for k in ("case_id", "title", "state", "category", "impact_score")}
                                               for c in v["items"]]}

    def t_case(s, a):
        cid = str(a.get("case_id", ""))
        return _summarize_case(case_view(s, store, principal, cid), case_runs_view(s, principal, cid))

    def t_results(s, a):
        return _summarize_results(run_view(s, principal, str(a.get("run_id", "")), include_results=True))

    def t_compare(s, a):
        return _compare(run_view(s, principal, str(a.get("run_id", "")), include_results=True))

    def t_request(s, a):
        if principal.role not in (Role.BUYER_PLANNER, Role.BUYER_PROCUREMENT, Role.BUYER_FINANCE):
            return {"error": "your role cannot request scenarios"}
        if state["scenarios_requested"] >= 1:
            return {"error": "only one scenario request per question"}
        case = load_case(s, principal, str(a.get("case_id", "")), buyer_only=True)
        modes = [m for m in (a.get("modes") or MODES) if m in MODES] or MODES
        scope = a.get("scope") if a.get("scope") in ("CASE_FIXTURE", "SNAPSHOT_HORIZON") else "CASE_FIXTURE"
        run = enqueue_scenario(s, settings, principal, case, ScenarioRequest(modes=modes, scope=scope), via="agent")
        state["scenarios_requested"] += 1
        s.flush()
        wake()
        return {"run_id": run.run_id, "status": "QUEUED", "modes": modes, "scope": scope,
                "note": "Queued for the optimization worker; results appear in the Simulate tab. Not solved yet."}

    def t_draft(s, a):
        run, case = load_run(s, principal, str(a.get("run_id", "")))
        mode = str(a.get("mode", ""))
        if run.state != "COMPLETED" or not run.results or mode not in run.results:
            return {"error": "run is not completed for this mode"}
        if not run.results[mode]["offer_eligible"]:
            return {"error": f"mode {mode} has status {run.results[mode]['status']} and cannot become an offer"}
        recipient = str(a.get("recipient_org_id", ""))
        if recipient not in (case.supplier_org_ids or []):
            return {"error": "recipient is not a supplier in this case"}
        lines = derive_lines(store, run, mode, recipient, case.tenant_id)
        return {"case_id": case.case_id, "run_id": run.run_id, "mode": mode, "recipient_org_id": recipient,
                "stale": run.input_version != case.input_version,
                "requested_lines": [{k: ln[k] for k in ("kind", "lane_id", "part_id", "delivery_week", "additional_qty",
                                                         "unit_premium_eur", "payment_days")} for ln in lines],
                "note": "Text drafting only. No offer was created. A buyer creates and sends offers in the Resolve tab."}

    sid = {"type": "string"}
    return [
        Tool("list_cases", "List the supply exception cases this user can see, optionally filtered by state or text.",
             {"type": "object", "properties": {"state": sid, "query": sid}}, guarded("list_cases", t_list)),
        Tool("get_case_evidence", "Disruption, case scope, 12-week shortage summary and recent scenario runs for one case.",
             {"type": "object", "properties": {"case_id": sid}, "required": ["case_id"]}, guarded("get_case_evidence", t_case)),
        Tool("get_scenario_results", "Solver results of one completed scenario run: per-mode status, KPIs, financials, allocations.",
             {"type": "object", "properties": {"run_id": sid}, "required": ["run_id"]}, guarded("get_scenario_results", t_results)),
        Tool("compare_scenarios", "Side-by-side comparison of the mitigation modes of one run, with the server's suggested mode.",
             {"type": "object", "properties": {"run_id": sid}, "required": ["run_id"]}, guarded("compare_scenarios", t_compare)),
        Tool("request_scenario", "Queue a new solver run for a case (at most once per question). Does not return results.",
             {"type": "object", "properties": {"case_id": sid, "modes": {"type": "array", "items": {"type": "string", "enum": MODES}},
                                               "scope": {"type": "string", "enum": ["CASE_FIXTURE", "SNAPSHOT_HORIZON"]}},
              "required": ["case_id"]}, guarded("request_scenario", t_request)),
        Tool("draft_offer_text", "Get the shareable terms a plan would ask of one supplier, to write a message. Creates nothing.",
             {"type": "object", "properties": {"run_id": sid, "mode": {"type": "string", "enum": MODES}, "recipient_org_id": sid},
              "required": ["run_id", "mode", "recipient_org_id"]}, guarded("draft_offer_text", t_draft)),
    ]


# ---- execution -------------------------------------------------------------------------------------------------
def execute_agent_run(sessions, store, settings, provider, agent_run_id: str, worker_id: str, wake: Callable[[], None]) -> bool:
    with sessions() as s:
        claimed = s.execute(update(AgentRun).where(AgentRun.agent_run_id == agent_run_id, AgentRun.state == "QUEUED")
                            .values(state="RUNNING")).rowcount
        s.commit()
    if not claimed:
        return False
    with sessions() as s:
        run = s.get(AgentRun, agent_run_id)
        principal = principal_from_id(store, run.principal_id)
        question, case_id = run.question, run.case_id
    if provider is None or principal is None:
        outcome_state, answer, trace, unverified, err, usage = "FAILED", "", [], [], "AI assistant is disabled", {}
        prov_name = model = None
    else:
        tools = build_tools(sessions, store, settings, principal, agent_run_id=agent_run_id, wake=wake)
        context = f"Current user role: {principal.role.value}." + (f" The user is looking at case {case_id}." if case_id else "")
        out = run_agent(provider, question, tools, context=context, redact=make_redactor(principal))
        outcome_state, answer, trace, unverified, err, usage = out.status, out.answer, out.trace, out.unverified, out.error, out.usage
        prov_name, model = provider.name, provider.model
    with sessions() as s:
        run = s.get(AgentRun, agent_run_id)
        run.state, run.answer, run.trace, run.unverified_numbers = outcome_state, answer, trace, unverified
        run.error, run.usage, run.provider, run.model, run.finished_at = err, usage, prov_name, model, utcnow()
        if principal is not None:
            audit(s, principal, action="agent.answer", resource_type="agent_run", resource_id=agent_run_id, case_id=case_id,
                  payload={"state": outcome_state, "tools": [t["tool"] for t in trace]},
                  summary=f"AI assistant {outcome_state.lower()} ({len(trace)} tool calls)")
        s.commit()
    return True


def pending_agent_ids(sessions, limit: int = 5) -> list[str]:
    with sessions() as s:
        return list(s.scalars(select(AgentRun.agent_run_id).where(AgentRun.state == "QUEUED").order_by(AgentRun.created_at).limit(limit)))


def agent_run_dict(run: AgentRun) -> dict[str, Any]:
    return {"agent_run_id": run.agent_run_id, "state": run.state, "question": run.question, "case_id": run.case_id,
            "answer": run.answer, "trace": run.trace, "unverified_numbers": run.unverified_numbers, "provider": run.provider,
            "model": run.model, "usage": run.usage, "error": run.error, "created_at": run.created_at.isoformat(),
            "finished_at": run.finished_at.isoformat() if run.finished_at else None}
