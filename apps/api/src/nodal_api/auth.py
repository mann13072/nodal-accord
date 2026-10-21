"""Principal resolution.

DEMO_MODE: the caller names a seeded demo principal in `X-Demo-Principal`; roles, organization and tenant
scope come from the server-side principal table, never from the client. Without DEMO_MODE no identity
provider is configured in this prototype, so every request is rejected (fail closed).
"""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request

from nodal_domain.enums import Role
from nodal_domain.permissions import Principal


def get_principal(request: Request, x_demo_principal: str | None = Header(default=None)) -> Principal:
    state = request.app.state
    if not state.settings.demo_mode:
        raise HTTPException(401, detail="No identity provider configured; demo identities are disabled.")
    if not x_demo_principal:
        raise HTTPException(401, detail="Missing X-Demo-Principal header.")
    row = state.store.principals.get(x_demo_principal)
    if row is None:
        raise HTTPException(401, detail="Unknown principal.")
    return Principal(row["principal_id"], row["org_id"], Role(row["role"]), frozenset(row["tenant_scopes"]))


def require_roles(*roles: Role):
    allowed = set(roles)

    def dep(principal: Principal = Depends(get_principal)) -> Principal:
        if principal.role not in allowed:
            raise HTTPException(403, detail="Role not permitted for this action.")
        return principal

    return dep
