"""Case seeding, object-level access and role projections."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select

from nodal_domain.permissions import Principal

from ..db import Case, Offer

TITLES = {
    "SIMPLE_SHORTAGE": "Capacity shortage", "NO_ACTUAL_SHORTAGE": "Capacity drop covered by stock",
    "LATE_ALTERNATIVE": "Alternate supplier too late", "SHARED_MACHINE": "Shared machine conflict",
    "OVERTIME_FEASIBLE": "Overtime can recover", "PREBUILD": "Prebuild opportunity",
    "ALTERNATIVE_SOURCING": "Qualified second source", "HYBRID": "Overtime + second source",
    "SINGLE_SOURCE_IMPOSSIBLE": "Single source, no recovery", "MULTI_BUYER": "Supplier shared across buyers",
    "COUNTEROFFER_FEASIBILITY": "Counteroffer changes feasibility", "COMMERCIAL_NEGOTIATION": "Commercial negotiation",
}
NOT_FOUND = "Not found"


def seed_cases(session, store) -> int:
    """Create live workflow cases from the snapshot's resolution_cases (idempotent)."""
    if session.scalar(select(func.count()).select_from(Case)):
        return 0
    n = 0
    for row in store.table("resolution_cases").to_dict("records"):
        fixture = store.case_fixture(row["case_id"]) or {}
        tenant = row["tenant_id"]
        lanes = [store.lanes_by_id[l] for l in fixture.get("lane_ids", []) if l in store.lanes_by_id]
        alts = [store.lanes_by_id[l] for l in (fixture.get("alternate_lane_ids") or []) if l and l in store.lanes_by_id]
        suppliers = sorted({l["supplier_org_id"] for l in lanes + alts if l["tenant_id"] == tenant} | set(row.get("shared_supplier_org_ids") or []))
        part = lanes[0]["part_id"] if lanes else ""
        session.add(Case(
            case_id=row["case_id"], tenant_id=tenant, buyer_org_id=store.tenants[tenant]["buyer_org_id"],
            category=row.get("category") or fixture.get("category", ""),
            title=f"{TITLES.get(row.get('category') or '', 'Supply exception')} - {part}",
            impact_score=int(row.get("impact_score") or 0), disruption_id=fixture.get("disruption_event_id") or row.get("exception_id"),
            snapshot_id=row["snapshot_id"], fixture_hash=fixture.get("snapshot_content_hash"), supplier_org_ids=suppliers,
            tenant_scope_ids=sorted(set(fixture.get("tenant_ids") or [tenant])), state="DETECTED",
            seeded_script_status=row.get("status"), owner_principal_id=row.get("owner_principal_id")))
        n += 1
    session.commit()
    return n


def supplier_has_sent_offer(session, case_id: str, org_id: str) -> bool:
    return bool(session.scalar(select(func.count()).select_from(Offer).where(
        Offer.case_id == case_id, Offer.recipient_org_id == org_id, Offer.status != "DRAFT")))


def load_case(session, principal: Principal, case_id: str, *, buyer_only: bool = False) -> Case:
    """Object-level check. Unauthorized and nonexistent IDs both return the same 404 (no existence leak)."""
    case = session.get(Case, case_id)
    if case is None:
        raise HTTPException(404, detail=NOT_FOUND)
    if principal.is_buyer and principal.in_tenant(case.tenant_id):
        return case
    if not buyer_only and principal.is_supplier and principal.org_id in (case.supplier_org_ids or []) \
            and supplier_has_sent_offer(session, case_id, principal.org_id):
        return case
    raise HTTPException(404, detail=NOT_FOUND)


def case_summary(case: Case) -> dict[str, Any]:
    return {"case_id": case.case_id, "title": case.title, "category": case.category, "state": case.state,
            "impact_score": case.impact_score, "tenant_id": case.tenant_id, "snapshot_id": case.snapshot_id,
            "input_version": case.input_version, "version": case.version, "opened_at": case.opened_at.isoformat(),
            "updated_at": case.updated_at.isoformat(), "seeded_script_status": case.seeded_script_status,
            "owner_principal_id": case.owner_principal_id}


def supplier_case_summary(case: Case) -> dict[str, Any]:
    return {"case_id": case.case_id, "title": "Capacity request from buyer", "state": case.state,
            "buyer_org_id": case.buyer_org_id, "updated_at": case.updated_at.isoformat()}


def buyer_fixture_view(fixture: dict[str, Any], tenant_id: str) -> dict[str, Any]:
    """Fixture facts the buyer may see. Resource hours are supplier-internal and are withheld."""
    rows = []
    for i, lane_id in enumerate(fixture.get("lane_ids", [])):
        if fixture["tenant_ids"][i] != tenant_id:
            continue
        alt = (fixture.get("alternate_lane_ids") or [None] * (i + 1))[i]
        rows.append({"lane_id": lane_id, "part_id": fixture["part_ids"][i], "demand_units": fixture["demand_units"][i],
                     "usable_stock": fixture["usable_stock"][i], "lane_ceiling_units": fixture["lane_ceiling_units"][i],
                     "alternate_lane_id": alt, "alternate_offered_units": fixture["alternate_units"][i] if alt else 0})
    hidden = sum(1 for t in fixture.get("tenant_ids", []) if t != tenant_id)
    return {"week_start": fixture.get("week_start"), "prebuild_prior_week": fixture.get("prebuild_prior_week"),
            "alternate_qualified": fixture.get("alternate_qualified"), "alternate_arrives_in_time": fixture.get("alternate_arrives_in_time"),
            "overtime_available": bool(fixture.get("overtime_hours")), "lines": rows,
            "other_relationships_on_shared_resource": hidden, "scope": "CASE_FIXTURE (isolated override, generator semantics)"}
