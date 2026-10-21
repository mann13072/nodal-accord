"""Record- and field-level access policy (blueprint §15).

Reject by default. Tenant and organization scope always come from the verified principal,
never from a client-supplied field. Permission to *optimize* with a value is separate from
permission to *display* it: this module only answers the display question.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .enums import BUYER_ROLES, Classification, Role

# Entities the platform operator may read: operational metadata only (blueprint §15.1).
OPS_METADATA_ENTITIES = frozenset({"telemetry", "health", "metrics", "job_metadata"})

# Field names that must never leave the buyer boundary, whatever the record classification.
BUYER_CONFIDENTIAL_FIELDS = frozenset({
    "stockout_exposure_proxy_eur_per_unit",
    "shortage_exposure_proxy_eur",
    "max_case_incremental_spend_eur",
    "approval_threshold_eur",
    "max_approved_premium_pct",
    "unit_price_eur",
    "unit_purchase_price",
    "inventory_holding_rate_annual",
    "cash_financing_rate_annual",
    "objective_value",
})

# Field names that must never leave the owning supplier.
SUPPLIER_PRIVATE_FIELDS = frozenset({
    "unit_variable_cost_eur",
    "overtime_premium_cost_eur_per_unit",
    "minimum_acceptable_margin_eur_per_unit",
    "internal_financing_rate_annual",
    "max_flex_units_per_week",
    "weak_margin_flag",
    "incremental_supplier_margin_eur",
    "rated_hours_per_week",
    "available_hours",
    "firm_reserved_hours",
    "flexible_additional_hours",
})


@dataclass(frozen=True)
class Principal:
    principal_id: str
    org_id: str
    role: Role
    tenant_scopes: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_buyer(self) -> bool:
        return self.role in BUYER_ROLES

    @property
    def is_supplier(self) -> bool:
        return self.role == Role.SUPPLIER_PLANNER

    @property
    def is_ops(self) -> bool:
        return self.role == Role.PLATFORM_OPS

    def in_tenant(self, tenant_id: str | None) -> bool:
        return tenant_id is not None and tenant_id in self.tenant_scopes


def _record_tenant(record: Mapping[str, Any]) -> str | None:
    return record.get("tenant_id") or record.get("buyer_tenant_id")


def _classification(record: Mapping[str, Any]) -> str | None:
    return record.get("data_classification") or record.get("classification")


def can_read_record(principal: Principal, entity: str, record: Mapping[str, Any]) -> bool:
    """Decide whether `principal` may see `record` of `entity` at all."""
    if principal.is_ops:
        return entity in OPS_METADATA_ENTITIES
    if entity in OPS_METADATA_ENTITIES:
        return False
    if principal.role == Role.INTEGRATION_SERVICE:
        return False  # write-scoped; reads go through import status endpoints only

    cls = _classification(record)
    tenant = _record_tenant(record)
    supplier = record.get("supplier_org_id")
    owner = record.get("owner_org_id")

    if principal.is_buyer:
        if cls == Classification.SUPPLIER_INTERNAL:
            return False
        if cls == Classification.PUBLIC_SYNTHETIC:
            return True
        return principal.in_tenant(tenant)

    if principal.is_supplier:
        if cls == Classification.SUPPLIER_INTERNAL:
            return principal.org_id in (supplier, owner)
        if cls == Classification.RELATIONSHIP_SHARED:
            return supplier == principal.org_id and principal.in_tenant(tenant)
        if cls == Classification.PUBLIC_SYNTHETIC:
            return True
        return False  # BUYER_INTERNAL and anything unknown

    return False


def forbidden_fields_for(principal: Principal) -> frozenset[str]:
    if principal.is_buyer:
        return SUPPLIER_PRIVATE_FIELDS
    if principal.is_supplier:
        return BUYER_CONFIDENTIAL_FIELDS
    return SUPPLIER_PRIVATE_FIELDS | BUYER_CONFIDENTIAL_FIELDS


def project_fields(principal: Principal, record: Mapping[str, Any], *, own_supplier_record: bool = False) -> dict[str, Any]:
    """Drop fields the principal may not see. A supplier keeps its own private fields."""
    forbidden = forbidden_fields_for(principal)
    if own_supplier_record and principal.is_supplier:
        forbidden = BUYER_CONFIDENTIAL_FIELDS
    return {k: v for k, v in record.items() if k not in forbidden}


def find_forbidden(principal: Principal, payload: Any, *, allow_own_supplier: bool = False) -> list[str]:
    """Recursively list forbidden keys present in a response payload (used by leak tests)."""
    forbidden = BUYER_CONFIDENTIAL_FIELDS if (allow_own_supplier and principal.is_supplier) else forbidden_fields_for(principal)
    found: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, Mapping):
            for k, v in node.items():
                if k in forbidden:
                    found.append(f"{path}.{k}")
                walk(v, f"{path}.{k}")
        elif isinstance(node, (list, tuple)):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(payload, "$")
    return found
