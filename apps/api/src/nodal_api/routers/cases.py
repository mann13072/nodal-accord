from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy import or_, select

from nodal_domain.enums import Role, RunState
from nodal_domain.permissions import Principal
from nodal_planning.impact import disruption_window, impact_graph, item_ledgers

from ..auth import get_principal, require_roles
from ..db import AuditEvent, Case, IdempotencyRecord, Offer, ScenarioRun, new_id, utcnow
from ..schemas import CapacityConfirmation, ScenarioRequest
from ..services.audit import audit, outbox
from ..services.cases import buyer_fixture_view, case_summary, load_case, supplier_case_summary
from ..services.offers import offer_dict
from ..services.projections import run_envelope

router = APIRouter(prefix="/api/v1")
BUYERS = (Role.BUYER_PLANNER, Role.BUYER_PROCUREMENT, Role.BUYER_FINANCE, Role.BUYER_OPERATIONS)


def db(request: Request):
    with request.app.state.sessions() as s:
        yield s


@router.get("/cases")
def list_cases(request: Request, principal: Principal = Depends(get_principal), session=Depends(db),
               state: str | None = None, q: str | None = None, limit: int = Query(200, le=500), offset: int = 0) -> dict[str, Any]:
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


@router.get("/cases/{case_id}")
def get_case(case_id: str, request: Request, principal: Principal = Depends(get_principal), session=Depends(db)) -> dict[str, Any]:
    case = load_case(session, principal, case_id)
    store = request.app.state.store
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
        "disruption": _disruption_view(ev) if ev else None,
        "fixture": buyer_fixture_view(fixture, case.tenant_id) if fixture else None,
        "snapshot_horizon": {"weeks": store.week_starts, "items": ledgers,
                             "note": "Deterministic ledger from the canonical snapshot (baseline vs disrupted receipts)."},
        "input_overrides": case.input_overrides, "dataset": store.dataset_label,
    }


def _disruption_view(ev: dict[str, Any]) -> dict[str, Any]:
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


@router.get("/cases/{case_id}/impact")
@router.get("/network/impact")
def network_impact(request: Request, case_id: str | None = None, principal: Principal = Depends(require_roles(*BUYERS)),
                   session=Depends(db), max_nodes: int = Query(100, ge=10, le=300)) -> dict[str, Any]:
    if not case_id:
        raise HTTPException(422, detail="case_id is required")
    case = load_case(session, principal, case_id, buyer_only=True)
    store = request.app.state.store
    fixture = store.case_fixture(case_id) or {}
    return impact_graph(store, tenant_id=case.tenant_id, lane_ids=fixture.get("lane_ids", []),
                        alternate_lane_ids=[x for x in (fixture.get("alternate_lane_ids") or []) if x],
                        resource_id=fixture.get("resource_id"), max_nodes=max_nodes)


@router.get("/network/summary")
def network_summary(request: Request, principal: Principal = Depends(require_roles(*BUYERS))) -> dict[str, Any]:
    store = request.app.state.store
    lanes = store.table("sourcing_lanes")
    mine = lanes[lanes["tenant_id"].isin(sorted(principal.tenant_scopes))]
    return {"tenant_ids": sorted(principal.tenant_scopes), "suppliers": int(mine["supplier_org_id"].nunique()),
            "parts": int(mine["part_id"].nunique()), "plants": int(mine["destination_plant_id"].nunique()),
            "lanes": int(len(mine)), "qualified_lanes": int(mine["qualified"].sum()), "dataset": store.dataset_label}


# ---- scenarios -------------------------------------------------------------------------------
@router.post("/cases/{case_id}/scenarios", status_code=202)
def submit_scenario(case_id: str, body: ScenarioRequest, request: Request, response: Response,
                    principal: Principal = Depends(require_roles(Role.BUYER_PLANNER, Role.BUYER_PROCUREMENT, Role.BUYER_FINANCE)),
                    session=Depends(db), idempotency_key: str | None = Header(default=None)) -> dict[str, Any]:
    case = load_case(session, principal, case_id, buyer_only=True)
    idem = f"{principal.principal_id}|scenario|{case_id}|{idempotency_key}" if idempotency_key else None
    if idem and (prev := session.get(IdempotencyRecord, idem)):
        response.status_code = prev.status_code
        return prev.response
    cap = request.app.state.settings.max_solver_seconds
    if body.solver.time_limit_seconds > cap:
        body.solver.time_limit_seconds = cap  # public demo protection; the applied value is stored with the run
    run = ScenarioRun(run_id=new_id("RUN"), case_id=case.case_id, tenant_id=case.tenant_id, requested_by=principal.principal_id,
                      request=body.model_dump(), input_version=case.input_version, state=RunState.QUEUED.value)
    session.add(run)
    if case.state == "DETECTED":
        case.state = "INVESTIGATING"
        case.version += 1
    audit(session, principal, action="scenario.submit", resource_type="scenario_run", resource_id=run.run_id, tenant_id=case.tenant_id,
          case_id=case.case_id, payload=body.model_dump(), summary=f"Scenario run requested ({', '.join(body.modes)}; {body.scope})")
    payload = {"run_id": run.run_id, "status": RunState.QUEUED.value, "status_url": f"/api/v1/scenario-runs/{run.run_id}"}
    if idem:
        session.add(IdempotencyRecord(key=idem, response=payload, status_code=202))
    session.commit()
    request.app.state.wake_worker()
    return payload


@router.get("/cases/{case_id}/scenario-runs")
def list_runs(case_id: str, principal: Principal = Depends(require_roles(*BUYERS)), session=Depends(db)) -> dict[str, Any]:
    case = load_case(session, principal, case_id, buyer_only=True)
    runs = session.scalars(select(ScenarioRun).where(ScenarioRun.case_id == case.case_id).order_by(ScenarioRun.created_at.desc()))
    out = []
    for r in runs:
        env = run_envelope(r, principal, include_results=False)
        env["stale"] = r.input_version != case.input_version
        out.append(env)
    return {"items": out}


def _load_run(session, principal: Principal, run_id: str) -> tuple[ScenarioRun, Case]:
    run = session.get(ScenarioRun, run_id)
    if run is None:
        raise HTTPException(404, detail="Not found")
    case = load_case(session, principal, run.case_id, buyer_only=True)
    return run, case


@router.get("/scenario-runs/{run_id}")
def get_run(run_id: str, principal: Principal = Depends(require_roles(*BUYERS)), session=Depends(db)) -> dict[str, Any]:
    run, case = _load_run(session, principal, run_id)
    env = run_envelope(run, principal, include_results=False)
    env["stale"] = run.input_version != case.input_version
    return env


@router.get("/scenario-runs/{run_id}/results")
def get_results(run_id: str, principal: Principal = Depends(require_roles(*BUYERS)), session=Depends(db)) -> dict[str, Any]:
    run, case = _load_run(session, principal, run_id)
    if run.state not in (RunState.COMPLETED.value, RunState.FAILED.value):
        raise HTTPException(409, detail={"code": "NOT_READY", "detail": f"run is {run.state}"})
    env = run_envelope(run, principal, include_results=True)
    env["stale"] = run.input_version != case.input_version
    return env


@router.post("/scenario-runs/{run_id}/cancel")
def cancel_run(run_id: str, principal: Principal = Depends(require_roles(Role.BUYER_PLANNER, Role.BUYER_PROCUREMENT)),
               session=Depends(db)) -> dict[str, Any]:
    run, case = _load_run(session, principal, run_id)
    if run.state != RunState.QUEUED.value:
        raise HTTPException(409, detail={"code": "NOT_CANCELLABLE", "detail": f"run is {run.state}"})
    run.state = RunState.CANCELLED.value
    run.finished_at = utcnow()
    audit(session, principal, action="scenario.cancel", resource_type="scenario_run", resource_id=run.run_id,
          tenant_id=case.tenant_id, case_id=case.case_id)
    session.commit()
    return {"run_id": run.run_id, "state": run.state}


# ---- capacity confirmations (input changes => stale scenarios/approvals) -----------------------
@router.post("/cases/{case_id}/capacity-confirmations")
def confirm_capacity(case_id: str, body: CapacityConfirmation, request: Request, principal: Principal = Depends(get_principal),
                     session=Depends(db)) -> dict[str, Any]:
    case = session.get(Case, case_id)
    store = request.app.state.store
    lane = store.lanes_by_id.get(body.lane_id)
    allowed = (case is not None and lane is not None and principal.is_supplier and lane["supplier_org_id"] == principal.org_id
               and principal.org_id in (case.supplier_org_ids or []) and lane["tenant_id"] == case.tenant_id)
    if not allowed:
        if case is not None:
            audit(session, principal, action="capacity.confirm", resource_type="case", resource_id=case_id, decision="DENY",
                  tenant_id=case.tenant_id, case_id=case_id)
            session.commit()
        raise HTTPException(404, detail="Not found")
    overrides = dict(case.input_overrides or {})
    overrides["supplier_limits"] = list(overrides.get("supplier_limits", [])) + [
        {"lane_id": body.lane_id, "week": body.week, "max_units": body.max_units, "source": "CAPACITY_CONFIRMATION"}]
    case.input_overrides = overrides
    before = case.input_version
    case.input_version += 1
    case.version += 1
    case.updated_at = utcnow()
    audit(session, principal, action="capacity.confirm", resource_type="case", resource_id=case_id, tenant_id=case.tenant_id,
          case_id=case_id, before=before, after=case.input_version, visible_to_org=principal.org_id,
          summary=f"Supplier capacity on {body.lane_id} for {body.week} limited to {body.max_units}; earlier scenarios are stale")
    outbox(session, "capacity.changed", case.tenant_id, case_id, case.input_version, {"case_id": case_id, "lane_id": body.lane_id, "week": body.week})
    session.commit()
    return {"case_id": case_id, "input_version": case.input_version, "stale_scenarios_and_approvals": True}


# ---- activity -------------------------------------------------------------------------------
@router.get("/cases/{case_id}/events")
def case_events(case_id: str, principal: Principal = Depends(get_principal), session=Depends(db)) -> dict[str, Any]:
    case = load_case(session, principal, case_id)
    stmt = select(AuditEvent).where(AuditEvent.case_id == case.case_id)
    if principal.is_supplier:
        stmt = stmt.where(or_(AuditEvent.visible_to_org == principal.org_id, AuditEvent.actor_org == principal.org_id))
    rows = session.scalars(stmt.order_by(AuditEvent.timestamp_utc))
    return {"items": [{"event_id": e.event_id, "at": e.timestamp_utc.isoformat(), "actor_id": e.actor_id, "actor_org": e.actor_org,
                       "action": e.action, "resource_type": e.resource_type, "resource_id": e.resource_id,
                       "decision": e.authorization_decision, "before_version": e.before_version, "after_version": e.after_version,
                       "payload_digest": e.payload_digest, "summary": e.summary} for e in rows]}
