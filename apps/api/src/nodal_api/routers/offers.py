from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from nodal_domain.enums import Role
from nodal_domain.permissions import Principal

from ..auth import get_principal, require_roles
from ..db import Agreement, Approval, Case, Counteroffer, Offer
from ..schemas import ApprovalRequest, CounterofferRequest, DecisionRequest, OfferDraftRequest, SendRequest
from ..services import offers as svc
from ..services.audit import audit
from ..services.cases import load_case
from .cases import db, supplier_offer_view

router = APIRouter(prefix="/api/v1")


def _offer_for(session, principal: Principal, offer_id: str) -> tuple[Offer, Case]:
    offer = session.get(Offer, offer_id)
    if offer is None:
        raise HTTPException(404, detail="Not found")
    case = load_case(session, principal, offer.case_id)
    if principal.is_supplier and (offer.recipient_org_id != principal.org_id or offer.status == "DRAFT"):
        raise HTTPException(404, detail="Not found")
    return offer, case


def _commit_or_conflict(session, fn):
    try:
        out = fn()
        session.commit()
        return out
    except HTTPException as exc:
        if exc.status_code == 409:
            session.commit()  # persist lazy state changes such as EXPIRED and denial audit events
        else:
            session.rollback()
        raise


@router.get("/cases/{case_id}/offers")
def list_offers(case_id: str, request: Request, principal: Principal = Depends(get_principal), session=Depends(db)) -> dict[str, Any]:
    case = load_case(session, principal, case_id)
    stmt = select(Offer).where(Offer.case_id == case.case_id)
    if principal.is_supplier:
        stmt = stmt.where(Offer.recipient_org_id == principal.org_id, Offer.status != "DRAFT")
    offers = list(session.scalars(stmt.order_by(Offer.offer_group_id, Offer.offer_version)))
    store = request.app.state.store
    items = [supplier_offer_view(store, principal, o) if principal.is_supplier else svc.offer_dict(o) for o in offers]
    counters = session.scalars(select(Counteroffer).where(Counteroffer.parent_offer_id.in_([o.offer_id for o in offers])))
    agreements = session.scalars(select(Agreement).where(Agreement.offer_id.in_([o.offer_id for o in offers])))
    return {"items": items,
            "counteroffers": [{"counteroffer_id": c.counteroffer_id, "parent_offer_id": c.parent_offer_id, "parent_version": c.parent_version,
                               "lines": c.lines, "reason_code": c.reason_code, "created_at": c.created_at.isoformat()} for c in counters],
            "agreements": [_agreement_dict(session, a) for a in agreements]}


@router.post("/cases/{case_id}/offers", status_code=201)
def draft_offer(case_id: str, body: OfferDraftRequest, request: Request,
                principal: Principal = Depends(require_roles(Role.BUYER_PLANNER, Role.BUYER_PROCUREMENT)), session=Depends(db)) -> dict[str, Any]:
    case = load_case(session, principal, case_id, buyer_only=True)
    payload = body.model_dump()
    if payload.get("lines"):
        payload["lines"] = [{k: v for k, v in ln.items() if v is not None} for ln in payload["lines"]]
    offer = _commit_or_conflict(session, lambda: svc.create_draft(session, request.app.state.store, principal, case, payload))
    return svc.offer_dict(offer)


@router.get("/offers/{offer_id}")
def get_offer(offer_id: str, request: Request, principal: Principal = Depends(get_principal), session=Depends(db)) -> dict[str, Any]:
    offer, _ = _offer_for(session, principal, offer_id)
    return supplier_offer_view(request.app.state.store, principal, offer) if principal.is_supplier else svc.offer_dict(offer)


@router.post("/offers/{offer_id}/send")
def send_offer(offer_id: str, body: SendRequest, principal: Principal = Depends(require_roles(Role.BUYER_PROCUREMENT)),
               session=Depends(db)) -> dict[str, Any]:
    offer, case = _offer_for(session, principal, offer_id)
    return svc.offer_dict(_commit_or_conflict(session, lambda: svc.send(session, principal, case, offer, terms_digest=body.terms_digest)))


@router.post("/offers/{offer_id}/counteroffers", status_code=201)
def counteroffer(offer_id: str, body: CounterofferRequest, principal: Principal = Depends(require_roles(Role.SUPPLIER_PLANNER)),
                 session=Depends(db)) -> dict[str, Any]:
    offer, case = _offer_for(session, principal, offer_id)
    payload = body.model_dump()
    payload["lines"] = [{k: v for k, v in ln.items() if v is not None} for ln in payload["lines"]]
    co =_commit_or_conflict(session, lambda: svc.counter(session, principal, case, offer, payload))
    return {"counteroffer_id": co.counteroffer_id, "parent_offer_id": co.parent_offer_id, "lines": co.lines,
            "requires_buyer_resimulation": True}


@router.post("/offers/{offer_id}/decisions")
def decide(offer_id: str, body: DecisionRequest, request: Request, principal: Principal = Depends(require_roles(Role.SUPPLIER_PLANNER)),
           session=Depends(db)) -> dict[str, Any]:
    offer, case = _offer_for(session, principal, offer_id)
    return _commit_or_conflict(session, lambda: svc.decide(session, request.app.state.store, principal, case, offer, body.model_dump()))


def _agreement_dict(session, ag: Agreement) -> dict[str, Any]:
    approvals = session.scalars(select(Approval).where(Approval.agreement_id == ag.agreement_id).order_by(Approval.decided_at))
    return {"agreement_id": ag.agreement_id, "case_id": ag.case_id, "offer_id": ag.offer_id, "offer_version": ag.offer_version,
            "supplier_org_id": ag.supplier_org_id, "terms_digest": ag.terms_digest, "status": ag.status,
            "required_roles": ag.required_roles, "premium_total_eur": ag.premium_total_eur, "input_version": ag.input_version,
            "export_status": ag.export_status, "created_at": ag.created_at.isoformat(),
            "approvals": [{"role": a.approval_role, "principal": a.approver_principal_id, "decision": a.decision,
                           "at": a.decided_at.isoformat()} for a in approvals]}


def _agreement_for(session, principal: Principal, agreement_id: str) -> tuple[Agreement, Case]:
    ag = session.get(Agreement, agreement_id)
    if ag is None:
        raise HTTPException(404, detail="Not found")
    case = load_case(session, principal, ag.case_id)
    if principal.is_supplier and ag.supplier_org_id != principal.org_id:
        raise HTTPException(404, detail="Not found")
    return ag, case


@router.get("/agreements")
def list_agreements(principal: Principal = Depends(get_principal), session=Depends(db)) -> dict[str, Any]:
    if principal.is_buyer:
        stmt = select(Agreement).where(Agreement.tenant_id.in_(sorted(principal.tenant_scopes)))
    elif principal.is_supplier:
        stmt = select(Agreement).where(Agreement.supplier_org_id == principal.org_id)
    else:
        return {"items": []}
    return {"items": [_agreement_dict(session, a) for a in session.scalars(stmt.order_by(Agreement.created_at.desc()))]}


@router.get("/agreements/{agreement_id}")
def get_agreement(agreement_id: str, principal: Principal = Depends(get_principal), session=Depends(db)) -> dict[str, Any]:
    ag, _ = _agreement_for(session, principal, agreement_id)
    return _agreement_dict(session, ag)


@router.post("/agreements/{agreement_id}/approvals")
def approve(agreement_id: str, body: ApprovalRequest, principal: Principal = Depends(get_principal), session=Depends(db)) -> dict[str, Any]:
    if principal.role in (Role.PLATFORM_OPS, Role.INTEGRATION_SERVICE, Role.SUPPLIER_PLANNER):
        ag = session.get(Agreement, agreement_id)
        if ag is not None:
            audit(session, principal, action="agreement.approve", resource_type="agreement", resource_id=agreement_id,
                  decision="DENY", tenant_id=ag.tenant_id, case_id=ag.case_id, summary="Forced approval attempt by non-approver")
            session.commit()
        raise HTTPException(404, detail="Not found")
    ag, case = _agreement_for(session, principal, agreement_id)
    _commit_or_conflict(session, lambda: svc.approve(session, principal, case, ag, body.model_dump()))
    return _agreement_dict(session, ag)


@router.get("/agreements/{agreement_id}/export")
def export(agreement_id: str, request: Request, principal: Principal = Depends(require_roles(Role.BUYER_PROCUREMENT, Role.BUYER_FINANCE,
                                                                                                Role.BUYER_PLANNER, Role.BUYER_OPERATIONS)),
           session=Depends(db)) -> dict[str, Any]:
    ag, _ = _agreement_for(session, principal, agreement_id)
    if ag.status != "EXPORT_READY":
        raise HTTPException(409, detail={"code": "NOT_APPROVED", "detail": "Only fully approved agreements can be exported"})
    return svc.export_preview(session, request.app.state.store, ag)
