from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from nodal_domain.enums import Role
from nodal_domain.permissions import Principal

from ..auth import require_roles
from ..db import AgentRun, new_id
from ..services.agent import LIMITER, agent_run_dict
from ..services.audit import audit
from ..services.cases import load_case
from .cases import db

router = APIRouter(prefix="/api/v1/agent")
BUYERS = (Role.BUYER_PLANNER, Role.BUYER_PROCUREMENT, Role.BUYER_FINANCE, Role.BUYER_OPERATIONS)
DISCLOSURE = ("Questions and the case data visible to you are sent to the configured AI provider. "
              "Answers come from tool results; numbers not found in those results are flagged as unverified.")


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    case_id: str | None = None


def _provider(request: Request):
    return request.app.state.agent_provider_factory()


@router.get("/status")
def status(request: Request) -> dict[str, Any]:
    p = _provider(request)
    s = request.app.state.settings
    return {"enabled": p is not None, "provider": getattr(p, "name", None), "model": getattr(p, "model", None),
            "requires_access_code": bool(s.ai_access_code), "hourly_limit": s.ai_hourly_limit, "disclosure": DISCLOSURE}


@router.post("/ask", status_code=202)
def ask(body: AskRequest, request: Request, principal: Principal = Depends(require_roles(*BUYERS)), session=Depends(db),
        x_ai_access_code: str | None = Header(default=None)) -> dict[str, Any]:
    settings = request.app.state.settings
    if _provider(request) is None:
        raise HTTPException(503, detail="AI assistant is disabled on this deployment.")
    if settings.ai_access_code and not hmac.compare_digest((x_ai_access_code or "").encode(), settings.ai_access_code.encode()):
        raise HTTPException(403, detail="AI access code required.")
    if body.case_id:
        load_case(session, principal, body.case_id, buyer_only=True)  # 404 for cases the user cannot see
    if not LIMITER.allow(settings.ai_hourly_limit):
        raise HTTPException(429, detail="AI assistant hourly limit reached; try again later.", headers={"Retry-After": "600"})
    run = AgentRun(agent_run_id=new_id("AIR"), principal_id=principal.principal_id,
                   tenant_id=sorted(principal.tenant_scopes)[0] if principal.tenant_scopes else None,
                   case_id=body.case_id, question=body.question, state="QUEUED")
    session.add(run)
    audit(session, principal, action="agent.ask", resource_type="agent_run", resource_id=run.agent_run_id, case_id=body.case_id,
          payload={"question_chars": len(body.question)}, summary="Question to the AI assistant")
    session.commit()
    request.app.state.wake_worker()
    return {"agent_run_id": run.agent_run_id, "state": "QUEUED", "status_url": f"/api/v1/agent/runs/{run.agent_run_id}"}


@router.get("/runs/{agent_run_id}")
def get_run(agent_run_id: str, principal: Principal = Depends(require_roles(*BUYERS)), session=Depends(db)) -> dict[str, Any]:
    run = session.get(AgentRun, agent_run_id)
    if run is None or run.principal_id != principal.principal_id:
        raise HTTPException(404, detail="Not found")
    return agent_run_dict(run)
