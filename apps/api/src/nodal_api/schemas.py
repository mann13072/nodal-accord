"""Request contracts (exported to contracts/openapi/nodal-accord-v1.json)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SolverParams(BaseModel):
    time_limit_seconds: float = Field(30, ge=0, le=600)
    max_relative_gap: float = Field(0.0, ge=0, le=0.5)


class ScenarioConstraints(BaseModel):
    max_incremental_cost_eur: str | None = Field(None, description="Cap on buyer incremental cost (decimal string, EUR)")
    require_zero_shortage: bool = False


class ScenarioRequest(BaseModel):
    modes: list[Literal["baseline", "overtime", "alternate", "prebuild", "hybrid"]] = ["baseline", "overtime", "alternate", "prebuild", "hybrid"]
    scope: Literal["CASE_FIXTURE", "SNAPSHOT_HORIZON"] = "CASE_FIXTURE"
    constraints: ScenarioConstraints = ScenarioConstraints()
    solver: SolverParams = SolverParams()


class OfferLineInput(BaseModel):
    kind: Literal["OVERTIME", "ALTERNATE_SUPPLY", "PREBUILD"]
    lane_id: str
    delivery_week: str
    additional_qty: int | None = None
    unit_premium_eur: str | None = None
    payment_days: int | None = None


class OfferDraftRequest(BaseModel):
    run_id: str
    mode: Literal["baseline", "overtime", "alternate", "prebuild", "hybrid"]
    recipient_org_id: str
    lines: list[OfferLineInput] | None = None
    expires_in_hours: float = Field(72, gt=0, le=24 * 30)
    offer_group_id: str | None = Field(None, description="Set to revise an earlier offer (creates the next version)")


class SendRequest(BaseModel):
    terms_digest: str | None = None


class CounterLine(BaseModel):
    line_id: str
    countered_qty: int | None = None
    countered_delivery_week: str | None = None
    countered_premium_eur: str | None = None
    countered_payment_days: int | None = None


class CounterofferRequest(BaseModel):
    offer_version: int
    lines: list[CounterLine]
    reason_code: Literal["CAPACITY_CHANGE", "DATE_CHANGE", "PRICE_CHANGE", "PAYMENT_TERMS", "OTHER"] = "CAPACITY_CHANGE"
    constraint_acknowledgement: bool


class DecisionRequest(BaseModel):
    decision: Literal["ACCEPT", "REJECT"]
    offer_version: int
    terms_digest: str
    reason: str | None = None


class ApprovalRequest(BaseModel):
    decision: Literal["APPROVE", "REJECT"]
    terms_digest: str
    rationale: str | None = None


class CapacityConfirmation(BaseModel):
    lane_id: str
    week: str
    max_units: int = Field(ge=0)
    note: str | None = None


class ImportRequest(BaseModel):
    connector: Literal["mock_erp", "mock_collaboration"]
    dry_run: bool = True
