from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy import or_, select

from nodal_domain.enums import Role, RunState
from nodal_domain.permissions import Principal
from nodal_planning.impact import impact_graph

from ..auth import get_principal, require_roles
from ..db import AuditEvent, Case, IdempotencyRecord, utcnow
from ..schemas import CapacityConfirmation, ScenarioRequest
from ..services.audit import audit, outbox
from ..services.cases import load_case
from ..services.views import (case_runs_view, case_view, enqueue_scenario, list_cases_view, load_run, run_view,
                              supplier_offer_view)

router = APIRouter(prefix="/api/v1")
BUYERS = (Role.BUYER_PLANNER, Role.BUYER_PROCUREMENT, Role.BUYER_FINANCE, Role.BUYER_OPERATIONS)

__all__ = ["router", "db", "supplier_offer_view"]


def db(request: Request):
    with request.app.state.sessions() as s:
        yield s


@router.get("/cases")
def list_cases(request: Request, principal: Principal = Depends(get_principal), session=Depends(db),
               state: str | None = None, q: str | None = None, limit: int = Query(200, le=500), offset: int = 0) -> dict[str, Any]:
    return list_cases_view(session, principal, state=state, q=q, limit=limit, offset=offset)


@router.get("/cases/{case_id}")
def get_case(case_id: str, request: Request, principal: Principal = Depends(get_principal), session=Depends(db)) -> dict[str, Any]:
    return case_view(session, request.app.state.store, principal, case_id)


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
    run = enqueue_scenario(session, request.app.state.settings, principal, case, body)
    payload = {"run_id": run.run_id, "status": RunState.QUEUED.value, "status_url": f"/api/v1/scenario-runs/{run.run_id}"}
    if idem:
        session.add(IdempotencyRecord(key=idem, response=payload, status_code=202))
    session.commit()
    request.app.state.wake_worker()
    return payload


@router.get("/cases/{case_id}/scenario-runs")
def list_runs(case_id: str, principal: Principal = Depends(require_roles(*BUYERS)), session=Depends(db)) -> dict[str, Any]:
    return case_runs_view(session, principal, case_id)


@router.get("/scenario-runs/{run_id}")
def get_run(run_id: str, principal: Principal = Depends(require_roles(*BUYERS)), session=Depends(db)) -> dict[str, Any]:
    return run_view(session, principal, run_id, include_results=False)


@router.get("/scenario-runs/{run_id}/results")
def get_results(run_id: str, principal: Principal = Depends(require_roles(*BUYERS)), session=Depends(db)) -> dict[str, Any]:
    return run_view(session, principal, run_id, include_results=True)


@router.post("/scenario-runs/{run_id}/cancel")
def cancel_run(run_id: str, principal: Principal = Depends(require_roles(Role.BUYER_PLANNER, Role.BUYER_PROCUREMENT)),
               session=Depends(db)) -> dict[str, Any]:
    run, case = load_run(session, principal, run_id)
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
