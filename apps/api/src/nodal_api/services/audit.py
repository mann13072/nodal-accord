"""Append-only audit trail and transactional outbox. Neither stores private values; payloads are digested."""
from __future__ import annotations

from typing import Any

from nodal_domain.digest import sha256_digest

from ..db import AuditEvent, OutboxEvent, new_id


def audit(session, principal, *, action: str, resource_type: str, resource_id: str, decision: str = "ALLOW",
          tenant_id: str | None = None, case_id: str | None = None, before: Any = None, after: Any = None,
          request_id: str | None = None, payload: Any = None, visible_to_org: str | None = None, summary: str = "") -> AuditEvent:
    ev = AuditEvent(
        event_id=new_id("EVT"), actor_type="SERVICE" if principal is None else "USER",
        actor_id=principal.principal_id if principal else "system", actor_org=principal.org_id if principal else "PLATFORM",
        tenant_id=tenant_id, case_id=case_id, resource_type=resource_type, resource_id=resource_id, action=action,
        authorization_decision=decision, before_version=None if before is None else str(before),
        after_version=None if after is None else str(after), request_id=request_id,
        payload_digest=sha256_digest(payload) if payload is not None else None, visible_to_org=visible_to_org, summary=summary)
    session.add(ev)
    return ev


def outbox(session, event_type: str, tenant_scope: str, aggregate_id: str, aggregate_version: int, payload: dict,
           correlation_id: str | None = None) -> OutboxEvent:
    """Outbound delivery is disabled by default (blueprint §9.3); events are recorded for consumers/tests."""
    ev = OutboxEvent(event_id=new_id("OUT"), event_type=f"{event_type}.v1", tenant_scope=tenant_scope, aggregate_id=aggregate_id,
                     aggregate_version=aggregate_version, correlation_id=correlation_id, payload=payload)
    session.add(ev)
    return ev
