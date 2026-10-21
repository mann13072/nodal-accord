from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select

from nodal_domain.enums import Role
from nodal_domain.permissions import Principal
from nodal_integrations.connectors import connector_for, reconcile

from ..auth import get_principal, require_roles
from ..db import Agreement, AuditEvent, Case, ImportRun, Offer, OutboxEvent, ScenarioRun, new_id
from ..schemas import ImportRequest
from ..services.audit import audit
from .cases import db

router = APIRouter(prefix="/api/v1")


@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
def ready(request: Request) -> dict[str, Any]:
    st = request.app.state
    try:
        st.store.week_starts
        data_ok = True
    except Exception:
        data_ok = False
    return {"status": "ok" if data_ok else "degraded", "dataset": st.store.dataset_label, "data_ok": data_ok,
            "environment": st.settings.environment_label, "inline_worker": st.settings.inline_worker}


@router.get("/session/principals")
def demo_principals(request: Request) -> dict[str, Any]:
    """Demo identity picker. Only available in DEMO_MODE; lists fictional, non-deliverable principal IDs."""
    if not request.app.state.settings.demo_mode:
        raise HTTPException(404, detail="Not found")
    store = request.app.state.store
    rows = []
    for p in store.principals.values():
        org = store.organizations.get(p["org_id"], {})
        rows.append({"principal_id": p["principal_id"], "org_id": p["org_id"], "role": p["role"],
                     "org_name": org.get("display_name", p["org_id"]), "tenant_scopes": sorted(p["tenant_scopes"])})
    return {"items": sorted(rows, key=lambda r: (r["role"].startswith("SUPPLIER"), r["principal_id"])),
            "environment": request.app.state.settings.environment_label, "dataset": store.dataset_label}


@router.get("/session/me")
def me(request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    store = request.app.state.store
    org = store.organizations.get(principal.org_id, {})
    return {"principal_id": principal.principal_id, "org_id": principal.org_id, "org_name": org.get("display_name", principal.org_id),
            "role": principal.role.value, "tenant_scopes": sorted(principal.tenant_scopes),
            "environment": request.app.state.settings.environment_label, "dataset": store.dataset_label,
            "snapshot_id": store.snapshot_id, "snapshot_generated_at": store.manifest.get("generated_at_utc")}


@router.get("/metrics/resolution")
def resolution_metrics(principal: Principal = Depends(get_principal), session=Depends(db)) -> dict[str, Any]:
    if principal.is_ops:
        # Operational metadata only: no tenant economics, no case identifiers.
        return {"scope": "PLATFORM_METADATA",
                "solver_runs": dict(session.execute(select(ScenarioRun.state, func.count()).group_by(ScenarioRun.state)).all()),
                "solver_status_counts": dict(session.execute(select(ScenarioRun.overall_status, func.count()).group_by(ScenarioRun.overall_status)).all()),
                "policy_denials": session.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.authorization_decision.like("DENY%"))),
                "outbox_backlog": session.scalar(select(func.count()).select_from(OutboxEvent)),
                "request_count": session.scalar(select(func.count()).select_from(AuditEvent))}
    if not principal.is_buyer:
        raise HTTPException(403, detail="Not permitted")
    tenants = sorted(principal.tenant_scopes)
    cases = dict(session.execute(select(Case.state, func.count()).where(Case.tenant_id.in_(tenants)).group_by(Case.state)).all())
    offers = dict(session.execute(select(Offer.status, func.count()).where(Offer.tenant_id.in_(tenants)).group_by(Offer.status)).all())
    agreements = dict(session.execute(select(Agreement.status, func.count()).where(Agreement.tenant_id.in_(tenants)).group_by(Agreement.status)).all())
    runs = list(session.execute(select(ScenarioRun.wall_seconds).where(ScenarioRun.tenant_id.in_(tenants), ScenarioRun.wall_seconds.is_not(None))).scalars())
    return {"scope": tenants, "cases_by_state": cases, "offers_by_status": offers, "agreements_by_status": agreements,
            "scenario_runs": len(runs), "scenario_wall_seconds_p50": sorted(runs)[len(runs) // 2] if runs else None,
            "note": "Synthetic demo process metrics; not customer outcomes."}


@router.post("/imports", status_code=201)
def start_import(body: ImportRequest, request: Request, principal: Principal = Depends(require_roles(Role.INTEGRATION_SERVICE, Role.BUYER_PLANNER)),
                 session=Depends(db)) -> dict[str, Any]:
    store = request.app.state.store
    conn = connector_for(body.connector, store.root / "external")
    checksum = conn.payload_checksum()
    # Idempotent: the same payload (checksum) from the same connector returns the earlier import.
    prev = session.scalar(select(ImportRun).where(ImportRun.connector == body.connector, ImportRun.payload_checksum == checksum,
                                                  ImportRun.status.in_(["VALIDATED", "COMMITTED_DRY_RUN"])))
    if prev is not None:
        return _import_dict(prev) | {"idempotent_replay": True}
    reports = conn.run(store)
    recon = [reconcile(store, r) for r in reports]
    run = ImportRun(import_id=new_id("IMP"), connector=body.connector, connector_version=conn.describe().version, payload_checksum=checksum,
                    requested_by=principal.principal_id, status="COMMITTED_DRY_RUN" if body.dry_run else "VALIDATED",
                    accepted_count=sum(len(r.accepted) for r in reports), rejected_count=sum(len(r.quarantined) for r in reports),
                    report={"capabilities": conn.describe().__dict__, "entities": [r.summary() for r in reports], "reconciliation": recon,
                            "note": "Canonical snapshot is the generator's immutable Parquet; this import validates and reconciles "
                                    "external feeds against it. Rows are not written over the snapshot."})
    session.add(run)
    audit(session, principal, action="import.run", resource_type="integration_run", resource_id=run.import_id,
          payload={"checksum": checksum}, summary=f"{body.connector}: {run.accepted_count} accepted, {run.rejected_count} quarantined")
    session.commit()
    return _import_dict(run)


@router.get("/imports/{import_id}")
def get_import(import_id: str, principal: Principal = Depends(require_roles(Role.INTEGRATION_SERVICE, Role.BUYER_PLANNER)),
               session=Depends(db)) -> dict[str, Any]:
    run = session.get(ImportRun, import_id)
    if run is None:
        raise HTTPException(404, detail="Not found")
    return _import_dict(run)


def _import_dict(run: ImportRun) -> dict[str, Any]:
    return {"import_id": run.import_id, "connector": run.connector, "connector_version": run.connector_version,
            "payload_checksum": run.payload_checksum, "status": run.status, "accepted_count": run.accepted_count,
            "rejected_count": run.rejected_count, "report": run.report, "created_at": run.created_at.isoformat()}
