"""Principal-scoped read views shared by the HTTP routers and the AI tool gateway.

Every view takes the verified principal and applies object-level access and role projections, so an AI tool
output is exactly what the API would return to the same user — never more.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select

from nodal_domain.enums import RunState
from nodal_domain.permissions import Principal
from nodal_planning.impact import disruption_window, item_ledgers

from ..db import Case, Offer, ScenarioRun, new_id
from .audit import audit
from .cases import buyer_fixture_view, case_summary, load_case, supplier_case_summary
from .offers import offer_dict
from .projections import run_envelope


def list_cases_view(session, principal: Principal, *, state: str | None = None, q: str | None = None,
                    limit: int = 200, offset: int = 0) -> dict[str, Any]:
    if principal.is_buyer:
        stmt = select(Case).where(Case.tenant_id.in_(sorted(principal.tenant_scopes)))
    elif principal.is_supplier:
        # Suppliers only see cases where an offer was actually sent to them.
        sent = select(Offer.case_id).where(Offer.recipient_org_id == principal.org_id, Offer.status != "DRAFT")
        stmt = select(Case).where(Case.case_id.in_(sent))
    else:
        return {"items": [], "total": 0}
    if state:
        stmt = stmt.where(Case.state == state)
    if q:
        stmt = stmt.where(or_(Case.case_id.contains(q.upper()), Case.title.contains(q)))
    rows = list(session.scalars(stmt.order_by(Case.impact_score.desc(), Case.case_id)))
    items = [case_summary(c) if principal.is_buyer else supplier_case_summary(c) for c in rows[offset:offset + limit]]
    return {"items": items, "total": len(rows), "limit": limit, "offset": offset}


def disruption_view(ev: dict[str, Any]) -> dict[str, Any]:
    keep = ("disruption_id", "event_type", "supplier_org_id", "lane_id", "start_week", "duration_weeks", "capacity_loss_percent",
            "demand_increase_percent", "lead_time_extension_days", "event_confidence", "is_confirmed", "synthetic_root_cause")
    out = {k: (str(ev[k]) if ev.get(k) is not None and not isinstance(ev[k], (int, bool, str)) else ev.get(k)) for k in keep}
    out["window"] = disruption_window(ev)
    out["has_resource_constraint"] = bool(ev.get("resource_id"))
    return out


def supplier_offer_view(store, principal: Principal, offer: Offer) -> dict[str, Any]:
    """Supplier sees the shareable terms, plus its *own* private economics evaluated locally (never shown to the buyer)."""
    view = offer_dict(offer)
    own = []
    for ln in offer.lines:
        econ = store.private_economics_by_lane.get(ln["lane_id"])
        if econ and econ["supplier_org_id"] == principal.org_id:
            prem = float(ln["unit_premium_eur"])
            ot_cost = float(econ["overtime_premium_cost_eur_per_unit"])
            own.append({"line_id": ln["line_id"], "kind": ln["kind"], "your_overtime_cost_eur_per_unit": f"{ot_cost:.2f}",
                        "your_contribution_on_premium_eur": f"{(prem - ot_cost) * ln['additional_qty']:.2f}" if ln["kind"] == "OVERTIME" else None,
                        "your_max_flex_units_per_week": int(econ["max_flex_units_per_week"])})
    view["your_private_evaluation"] = {"visible_to": principal.org_id, "lines": own,
                                       "note": "Computed from your own private economics; never shared with the buyer."}
    caps = []
    for ln in offer.lines:
        lc = store.lane_capacity_for(ln["lane_id"]).get(ln.get("release_week") or ln["delivery_week"])
        if lc:
            caps.append({"lane_id": ln["lane_id"], "week": ln.get("release_week") or ln["delivery_week"], **lc})
    view["your_lane_capacity"] = caps
    view.pop("source_run_id", None)
    return view


def case_view(session, store, principal: Principal, case_id: str) -> dict[str, Any]:
    case = load_case(session, principal, case_id)
    if principal.is_supplier:
        offers = session.scalars(select(Offer).where(Offer.case_id == case_id, Offer.recipient_org_id == principal.org_id,
                                                     Offer.status != "DRAFT").order_by(Offer.offer_version))
        return {"case": supplier_case_summary(case), "offers": [supplier_offer_view(store, principal, o) for o in offers]}
    fixture = store.case_fixture(case_id) or {}
    ev = store.disruptions.get(case.disruption_id) if case.disruption_id else None
    lanes = [store.lanes_by_id[l] for l in fixture.get("lane_ids", []) if l in store.lanes_by_id]
    items = sorted({(l["part_id"], l["destination_plant_id"]) for l in lanes if l["tenant_id"] == case.tenant_id})
    ledgers = item_ledgers(store, case.tenant_id, items, ev)
    return {
        "case": case_summary(case), "supplier_org_ids": case.supplier_org_ids,
        "suppliers": [{"org_id": s, "display_name": store.organizations.get(s, {}).get("display_name", s)} for s in case.supplier_org_ids],
        "disruption": disruption_view(ev) if ev else None,
        "fixture": buyer_fixture_view(fixture, case.tenant_id) if fixture else None,
        "snapshot_horizon": {"weeks": store.week_starts, "items": ledgers,
                             "note": "Deterministic ledger from the canonical snapshot (baseline vs disrupted receipts)."},
        "input_overrides": case.input_overrides, "dataset": store.dataset_label,
    }


def load_run(session, principal: Principal, run_id: str) -> tuple[ScenarioRun, Case]:
    run = session.get(ScenarioRun, run_id)
    if run is None:
        raise HTTPException(404, detail="Not found")
    case = load_case(session, principal, run.case_id, buyer_only=True)
    return run, case


def run_view(session, principal: Principal, run_id: str, *, include_results: bool) -> dict[str, Any]:
    run, case = load_run(session, principal, run_id)
    if include_results and run.state not in (RunState.COMPLETED.value, RunState.FAILED.value):
        raise HTTPException(409, detail={"code": "NOT_READY", "detail": f"run is {run.state}"})
    env = run_envelope(run, principal, include_results=include_results)
    env["stale"] = run.input_version != case.input_version
    return env


def enqueue_scenario(session, settings, principal: Principal, case: Case, body, *, via: str = "api") -> ScenarioRun:
    """Queue a scenario job (caller commits). Applies the deployment's solver-time cap and writes the audit event."""
    cap = settings.max_solver_seconds
    if body.solver.time_limit_seconds > cap:
        body.solver.time_limit_seconds = cap  # public demo protection; the applied value is stored with the run
    run = ScenarioRun(run_id=new_id("RUN"), case_id=case.case_id, tenant_id=case.tenant_id, requested_by=principal.principal_id,
                      request=body.model_dump(), input_version=case.input_version, state=RunState.QUEUED.value)
    session.add(run)
    if case.state == "DETECTED":
        case.state = "INVESTIGATING"
        case.version += 1
    audit(session, principal, action="scenario.submit", resource_type="scenario_run", resource_id=run.run_id, tenant_id=case.tenant_id,
          case_id=case.case_id, payload=body.model_dump(),
          summary=f"Scenario run requested ({', '.join(body.modes)}; {body.scope})" + (" via AI assistant" if via == "agent" else ""))
    return run


def case_runs_view(session, principal: Principal, case_id: str) -> dict[str, Any]:
    case = load_case(session, principal, case_id, buyer_only=True)
    runs = session.scalars(select(ScenarioRun).where(ScenarioRun.case_id == case.case_id).order_by(ScenarioRun.created_at.desc()))
    out = []
    for r in runs:
        env = run_envelope(r, principal, include_results=False)
        env["stale"] = r.input_version != case.input_version
        out.append(env)
    return {"items": out}
