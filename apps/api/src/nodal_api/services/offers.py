"""Offer / counteroffer / approval state machine (blueprint §13).

Invariants enforced here:
  * an offer is drafted only from a completed, validated, non-stale scenario result;
  * every revision is immutable; accept/reject/approve reference an exact version and terms digest;
  * a counteroffer is a separate record and forces re-simulation before a new revision can be sent;
  * capacity/input changes make earlier offers and agreements stale (approval blocked with 409);
  * the platform operator can never act as buyer or supplier; nothing is written back to an ERP.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select

from nodal_domain.digest import sha256_digest
from nodal_domain.enums import Role
from nodal_domain.money import D, money, money_str
from nodal_domain.permissions import Principal
from nodal_finance.payment_terms import payment_term_effect

from ..db import Agreement, Approval, Case, Counteroffer, Offer, ScenarioRun, new_id, utcnow
from .audit import audit, outbox

DEFAULT_PAYMENT_DAYS = 60


def _conflict(code: str, detail: str):
    return HTTPException(409, detail={"code": code, "detail": detail})


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def public_terms(offer_like: dict[str, Any]) -> dict[str, Any]:
    """The exact shareable terms that are digested, sent, accepted and approved."""
    return {"case_id": offer_like["case_id"], "recipient_org_id": offer_like["recipient_org_id"],
            "offer_version": offer_like["offer_version"], "expires_at": offer_like["expires_at"],
            "lines": [{k: ln[k] for k in ("line_id", "kind", "lane_id", "part_id", "plant_id", "delivery_week",
                                          "additional_qty", "unit_premium_eur", "payment_days")} for ln in offer_like["lines"]]}


def offer_dict(o: Offer) -> dict[str, Any]:
    return {"offer_id": o.offer_id, "offer_group_id": o.offer_group_id, "case_id": o.case_id, "sender_org_id": o.sender_org_id,
            "recipient_org_id": o.recipient_org_id, "offer_version": o.offer_version, "status": o.status,
            "source_run_id": o.source_run_id, "source_mode": o.source_mode, "input_version": o.input_version,
            "lines": o.lines, "terms_digest": o.terms_digest, "expires_at": _aware(o.expires_at).isoformat(),
            "created_at": o.created_at.isoformat(), "sent_at": o.sent_at.isoformat() if o.sent_at else None,
            "decided_at": o.decided_at.isoformat() if o.decided_at else None,
            "premium_total_eur": money_str(sum(D(l["unit_premium_eur"]) * l["additional_qty"] for l in o.lines))}


def derive_lines(store, run: ScenarioRun, mode: str, recipient: str, tenant_id: str) -> list[dict[str, Any]]:
    """Requested actions for one supplier, taken from the validated plan (never invented)."""
    r = run.results[mode]
    carried = {(x["part_id"], x["plant_id"], x["week_start"]): x["new_inventory"] for x in r["item_weeks"]}
    lines = []
    for rel in r["releases"]:
        if rel["supplier_org_id"] != recipient or rel.get("tenant_id") not in (tenant_id, None):
            continue
        lane = store.lanes_by_id[rel["lane_id"]]
        terms = store.buyer_terms.get((lane["relationship_id"], lane["part_id"]), {})
        pay = int(terms.get("payment_days") or DEFAULT_PAYMENT_DAYS)
        base = {"lane_id": rel["lane_id"], "part_id": rel["part_id"], "plant_id": rel["plant_id"],
                "delivery_week": rel["arrival_week"], "payment_days": pay, "release_week": rel["release_week"]}
        if rel["role"] == "ALTERNATE":
            lines.append(base | {"kind": "ALTERNATE_SUPPLY", "additional_qty": rel["regular_units"] + rel["overtime_units"],
                                 "unit_premium_eur": "0.00"})
        else:
            if rel["overtime_units"]:
                lines.append(base | {"kind": "OVERTIME", "additional_qty": rel["overtime_units"],
                                     "unit_premium_eur": rel["disclosed_premium_eur"]})
            pre = carried.get((rel["part_id"], rel["plant_id"], rel["arrival_week"]), 0)
            if pre and rel["regular_units"]:
                lines.append(base | {"kind": "PREBUILD", "additional_qty": min(pre, rel["regular_units"]), "unit_premium_eur": "0.00"})
    for n, ln in enumerate(lines, 1):
        ln["line_id"] = f"L{n}"
    return lines


def _validate_custom_lines(planned: list[dict[str, Any]], custom: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Buyers may lower quantities, change premium or payment days; they may not exceed the validated plan."""
    by_key = {(p["kind"], p["lane_id"], p["delivery_week"]): p for p in planned}
    out = []
    for n, c in enumerate(custom, 1):
        key = (c["kind"], c["lane_id"], c["delivery_week"])
        p = by_key.get(key)
        if p is None:
            raise HTTPException(422, detail=f"line {key} is not part of the validated plan")
        qty = int(c.get("additional_qty", p["additional_qty"]))
        if qty <= 0 or qty > p["additional_qty"]:
            raise HTTPException(422, detail=f"quantity for {key} must be 1..{p['additional_qty']} (validated plan)")
        prem = money(c.get("unit_premium_eur", p["unit_premium_eur"]))
        if prem < 0:
            raise HTTPException(422, detail="premium cannot be negative")
        days = int(c.get("payment_days", p["payment_days"]))
        if not 0 <= days <= 180:
            raise HTTPException(422, detail="payment_days must be within 0..180")
        out.append(p | {"line_id": f"L{n}", "additional_qty": qty, "unit_premium_eur": f"{prem:.2f}", "payment_days": days})
    return out


def create_draft(session, store, principal: Principal, case: Case, body: dict[str, Any]) -> Offer:
    run = session.get(ScenarioRun, body["run_id"])
    if run is None or run.case_id != case.case_id:
        raise HTTPException(404, detail="Not found")
    mode = body["mode"]
    if run.state != "COMPLETED" or not run.results or mode not in run.results:
        raise HTTPException(422, detail="Scenario run is not completed for this mode")
    res = run.results[mode]
    if not res["offer_eligible"]:
        raise HTTPException(422, detail=f"Mode {mode} has status {res['status']}; only validated feasible plans can become offers")
    if run.input_version != case.input_version:
        raise _conflict("STALE_SCENARIO", "Inputs changed after this run; re-run the scenario before drafting")
    recipient = body["recipient_org_id"]
    if recipient not in (case.supplier_org_ids or []):
        raise HTTPException(422, detail="Recipient is not a supplier in this case")
    planned = derive_lines(store, run, mode, recipient, case.tenant_id)
    if not planned:
        raise HTTPException(422, detail="The selected plan requests no additional action from this supplier")
    lines = _validate_custom_lines(planned, body["lines"]) if body.get("lines") else planned
    group = body.get("offer_group_id") or new_id("OFG")
    prev = session.scalar(select(func.max(Offer.offer_version)).where(Offer.offer_group_id == group)) or 0
    expires = utcnow() + timedelta(hours=float(body.get("expires_in_hours", 72)))
    draft = {"case_id": case.case_id, "recipient_org_id": recipient, "offer_version": prev + 1,
             "expires_at": expires.isoformat(), "lines": lines}
    offer = Offer(offer_id=f"{group}-V{prev + 1}", offer_group_id=group, case_id=case.case_id, tenant_id=case.tenant_id,
                  sender_org_id=case.buyer_org_id, recipient_org_id=recipient, offer_version=prev + 1, status="DRAFT",
                  source_run_id=run.run_id, source_mode=mode, input_version=case.input_version, lines=lines,
                  terms_digest=sha256_digest(public_terms(draft)), expires_at=expires, created_by=principal.principal_id)
    session.add(offer)
    case.state, case.version, case.updated_at = "DRAFT_OFFER", case.version + 1, utcnow()
    audit(session, principal, action="offer.draft", resource_type="offer", resource_id=offer.offer_id, tenant_id=case.tenant_id,
          case_id=case.case_id, after=offer.offer_version, payload=public_terms(draft), summary=f"Draft v{offer.offer_version} for {recipient}")
    return offer


def _check_live(case: Case, offer: Offer, expected_status: str) -> None:
    if offer.status != expected_status:
        raise _conflict("INVALID_STATE", f"offer is {offer.status}, expected {expected_status}")
    if _aware(offer.expires_at) < utcnow():
        offer.status = "EXPIRED"
        raise _conflict("EXPIRED", "offer validity window has elapsed")
    if offer.input_version != case.input_version:
        raise _conflict("STALE_OFFER", "case inputs changed after this offer was drafted; re-run and revise")


def send(session, principal: Principal, case: Case, offer: Offer, *, terms_digest: str | None) -> Offer:
    _check_live(case, offer, "DRAFT")
    if terms_digest and terms_digest != offer.terms_digest:
        raise _conflict("DIGEST_MISMATCH", "terms changed since review")
    for older in session.scalars(select(Offer).where(Offer.offer_group_id == offer.offer_group_id, Offer.offer_id != offer.offer_id,
                                                     Offer.status.in_(["SENT", "COUNTERED", "DRAFT"]))):
        older.status = "SUPERSEDED"
    offer.status, offer.sent_at = "SENT", utcnow()
    case.state, case.version, case.updated_at = "SENT", case.version + 1, utcnow()
    audit(session, principal, action="offer.send", resource_type="offer", resource_id=offer.offer_id, tenant_id=case.tenant_id,
          case_id=case.case_id, after=offer.offer_version, payload=offer.terms_digest, visible_to_org=offer.recipient_org_id,
          summary=f"Sent v{offer.offer_version} to {offer.recipient_org_id}")
    outbox(session, "offer.sent", case.tenant_id, offer.offer_id, offer.offer_version,
           {"offer_id": offer.offer_id, "case_id": case.case_id, "recipient_org_id": offer.recipient_org_id, "terms_digest": offer.terms_digest})
    return offer


def counter(session, principal: Principal, case: Case, offer: Offer, body: dict[str, Any]) -> Counteroffer:
    if principal.org_id != offer.recipient_org_id:
        raise HTTPException(404, detail="Not found")
    if int(body["offer_version"]) != offer.offer_version:
        raise _conflict("VERSION_CONFLICT", "counteroffer must reference the current offer version")
    _check_live(case, offer, "SENT")
    if not body.get("constraint_acknowledgement"):
        raise HTTPException(422, detail="Counteroffer must acknowledge the changed constraint")
    lines_by_id = {ln["line_id"]: ln for ln in offer.lines}
    changes, limits = [], []
    for c in body["lines"]:
        base = lines_by_id.get(c["line_id"])
        if base is None:
            raise HTTPException(422, detail=f"unknown line {c['line_id']}")
        qty = int(c.get("countered_qty", base["additional_qty"]))
        if qty < 0:
            raise HTTPException(422, detail="countered quantity cannot be negative")
        week = c.get("countered_delivery_week") or base["delivery_week"]
        prem = money(c.get("countered_premium_eur", base["unit_premium_eur"]))
        days = int(c.get("countered_payment_days", base["payment_days"]))
        changes.append({"line_id": base["line_id"], "kind": base["kind"], "lane_id": base["lane_id"], "original_qty": base["additional_qty"],
                        "countered_qty": qty, "original_delivery_week": base["delivery_week"], "countered_delivery_week": week,
                        "original_premium_eur": base["unit_premium_eur"], "countered_premium_eur": f"{prem:.2f}",
                        "original_payment_days": base["payment_days"], "countered_payment_days": days})
        if qty != base["additional_qty"] or week != base["delivery_week"]:
            limits.append(_limit_from_line(base, qty, week))
    co = Counteroffer(counteroffer_id=new_id("CTR"), parent_offer_id=offer.offer_id, case_id=case.case_id,
                      supplier_org_id=principal.org_id, parent_version=offer.offer_version, lines=changes,
                      reason_code=body.get("reason_code", "CAPACITY_CHANGE"), constraint_acknowledgement=True,
                      created_by=principal.principal_id)
    session.add(co)
    offer.status, offer.decided_at = "COUNTERED", utcnow()
    overrides = dict(case.input_overrides or {})
    overrides["supplier_limits"] = list(overrides.get("supplier_limits", [])) + limits
    overrides["counter_terms"] = {"counteroffer_id": co.counteroffer_id, "lines": changes}
    case.input_overrides = overrides
    if limits:
        case.input_version += 1  # physical feasibility changed: every earlier run is now stale
    case.state, case.version, case.updated_at = "COUNTERED", case.version + 1, utcnow()
    audit(session, principal, action="offer.counter", resource_type="offer", resource_id=offer.offer_id, tenant_id=case.tenant_id,
          case_id=case.case_id, before=offer.offer_version, payload=changes, visible_to_org=offer.recipient_org_id,
          summary=f"Counteroffer {co.counteroffer_id} ({co.reason_code}); re-simulation required")
    return co


def _limit_from_line(line: dict[str, Any], qty: int, week: str) -> dict[str, Any]:
    """Translate a countered line into a supplier capacity limit on that lane (arrival-week based).

    For overtime lines the supplier caps *total* output in that week at planned regular + countered overtime;
    alternate supply caps the lane at the countered quantity."""
    return {"lane_id": line["lane_id"], "week": line["delivery_week"], "kind": line["kind"],
            "max_units": qty if line["kind"] != "OVERTIME" else None, "max_overtime_units": qty if line["kind"] == "OVERTIME" else None,
            "moved_to_week": week if week != line["delivery_week"] else None, "source": "COUNTEROFFER"}


def decide(session, store, principal: Principal, case: Case, offer: Offer, body: dict[str, Any]) -> dict[str, Any]:
    if principal.org_id != offer.recipient_org_id or principal.role != Role.SUPPLIER_PLANNER:
        raise HTTPException(404, detail="Not found")
    if int(body["offer_version"]) != offer.offer_version or body.get("terms_digest") != offer.terms_digest:
        raise _conflict("VERSION_CONFLICT", "decision must reference the exact current version and terms digest")
    _check_live(case, offer, "SENT")
    decision = body["decision"]
    offer.decided_at = utcnow()
    if decision == "REJECT":
        offer.status = "REJECTED"
        case.state, case.version, case.updated_at = "REJECTED", case.version + 1, utcnow()
        audit(session, principal, action="offer.reject", resource_type="offer", resource_id=offer.offer_id, tenant_id=case.tenant_id,
              case_id=case.case_id, after=offer.offer_version, visible_to_org=offer.recipient_org_id, summary=body.get("reason", "Rejected"))
        return {"offer": offer_dict(offer)}
    if decision != "ACCEPT":
        raise HTTPException(422, detail="decision must be ACCEPT or REJECT")
    offer.status = "ACCEPTED"
    premium = sum(D(l["unit_premium_eur"]) * l["additional_qty"] for l in offer.lines)
    prof = store.financial_profiles.get(case.tenant_id, {})
    threshold = D(prof.get("approval_threshold_eur", "0"))
    roles = [Role.BUYER_PROCUREMENT.value]
    if premium >= threshold or _payment_terms_changed(store, offer):
        roles.append(Role.BUYER_FINANCE.value)
    ag = Agreement(agreement_id=new_id("AGR"), case_id=case.case_id, tenant_id=case.tenant_id, offer_id=offer.offer_id,
                   supplier_org_id=offer.recipient_org_id, offer_version=offer.offer_version, terms_digest=offer.terms_digest,
                   input_version=offer.input_version, required_roles=roles, status="PENDING_APPROVAL", premium_total_eur=money_str(premium))
    session.add(ag)
    case.state, case.version, case.updated_at = "BUYER_APPROVAL_PENDING", case.version + 1, utcnow()
    audit(session, principal, action="offer.accept", resource_type="offer", resource_id=offer.offer_id, tenant_id=case.tenant_id,
          case_id=case.case_id, after=offer.offer_version, payload=offer.terms_digest, visible_to_org=offer.recipient_org_id,
          summary=f"Supplier accepted v{offer.offer_version} (workflow acceptance, not a legal signature)")
    return {"offer": offer_dict(offer), "agreement_id": ag.agreement_id}


def _payment_terms_changed(store, offer: Offer) -> bool:
    for ln in offer.lines:
        lane = store.lanes_by_id[ln["lane_id"]]
        terms = store.buyer_terms.get((lane["relationship_id"], lane["part_id"]), {})
        if int(ln["payment_days"]) != int(terms.get("payment_days") or DEFAULT_PAYMENT_DAYS):
            return True
    return False


def approve(session, principal: Principal, case: Case, ag: Agreement, body: dict[str, Any]) -> Agreement:
    if not principal.is_buyer or not principal.in_tenant(ag.tenant_id):
        raise HTTPException(404, detail="Not found")
    if principal.role.value not in ag.required_roles:
        raise HTTPException(403, detail="This role is not a designated approver for this agreement")
    if ag.status != "PENDING_APPROVAL":
        raise _conflict("INVALID_STATE", f"agreement is {ag.status}")
    if body.get("terms_digest") != ag.terms_digest:
        raise _conflict("DIGEST_MISMATCH", "approval must reference the exact accepted terms digest")
    if ag.input_version != case.input_version:
        audit(session, principal, action="agreement.approve", resource_type="agreement", resource_id=ag.agreement_id, decision="DENY_STALE",
              tenant_id=case.tenant_id, case_id=case.case_id, summary="Approval blocked: inputs changed after acceptance")
        raise _conflict("STALE_APPROVAL", "capacity or planning inputs changed after acceptance; revalidate before approval")
    if session.scalar(select(func.count()).select_from(Approval).where(Approval.agreement_id == ag.agreement_id,
                                                                        Approval.approval_role == principal.role.value)):
        raise _conflict("ALREADY_DECIDED", "this role has already decided")
    decision = body["decision"]
    session.add(Approval(approval_id=new_id("APR"), agreement_id=ag.agreement_id, approver_principal_id=principal.principal_id,
                         approver_org_id=principal.org_id, approval_role=principal.role.value, decision=decision,
                         terms_digest=ag.terms_digest, rationale=body.get("rationale")))
    session.flush()
    audit(session, principal, action=f"agreement.{decision.lower()}", resource_type="agreement", resource_id=ag.agreement_id,
          tenant_id=case.tenant_id, case_id=case.case_id, payload=ag.terms_digest, summary=f"{principal.role.value} {decision}")
    if decision == "REJECT":
        ag.status = "REJECTED"
        case.state = "REJECTED"
    else:
        approved_roles = set(session.scalars(select(Approval.approval_role).where(Approval.agreement_id == ag.agreement_id,
                                                                                   Approval.decision == "APPROVE")))
        if set(ag.required_roles) <= approved_roles:
            ag.status, ag.approved_at = "EXPORT_READY", utcnow()
            case.state = "EXPORT_READY"
            outbox(session, "agreement.approved", case.tenant_id, ag.agreement_id, ag.offer_version,
                   {"agreement_id": ag.agreement_id, "case_id": case.case_id, "terms_digest": ag.terms_digest})
    case.version, case.updated_at = case.version + 1, utcnow()
    return ag


def export_preview(session, store, ag: Agreement) -> dict[str, Any]:
    offer = session.get(Offer, ag.offer_id)
    approvals = list(session.scalars(select(Approval).where(Approval.agreement_id == ag.agreement_id)))
    financing = []
    for ln in offer.lines:
        lane = store.lanes_by_id[ln["lane_id"]]
        terms = store.buyer_terms.get((lane["relationship_id"], lane["part_id"]), {})
        base_days = int(terms.get("payment_days") or DEFAULT_PAYMENT_DAYS)
        if int(ln["payment_days"]) != base_days:
            value = D(ln["additional_qty"]) * (D(terms.get("unit_price_eur") or 0) + D(ln["unit_premium_eur"]))
            rate = D(store.financial_profiles.get(ag.tenant_id, {}).get("cash_financing_rate_annual", "0.08"))
            financing.append({"line_id": ln["line_id"]} | payment_term_effect(value, rate, base_days, int(ln["payment_days"])).as_dict())
    return {
        "schema": "nodal-accord.agreement-export.v1", "agreement_id": ag.agreement_id, "status": ag.status,
        "case_id": ag.case_id, "supplier_org_id": ag.supplier_org_id, "offer_id": ag.offer_id, "offer_version": ag.offer_version,
        "terms_digest": ag.terms_digest, "lines": offer.lines, "premium_total_eur": ag.premium_total_eur,
        "payment_term_financing": financing,
        "approvals": [{"role": a.approval_role, "principal": a.approver_principal_id, "decision": a.decision,
                       "at": a.decided_at.isoformat(), "terms_digest": a.terms_digest} for a in approvals],
        "erp_write_back": {"enabled": False, "status": ag.export_status,
                           "note": "Export preview only. No ERP purchase-order change is performed by this prototype."},
        "legal_note": "Workflow acceptance and approval record; not a legally binding electronic signature.",
    }
