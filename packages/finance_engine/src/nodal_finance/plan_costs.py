"""Buyer-side financial effects of a mitigation plan, recomputed from integer quantities.

Mode A (default): only buyer prices and supplier-*disclosed* premiums are used. Supplier internal
cost and margin are never inputs here, so they cannot leak into buyer results.

Definitions (all EUR, horizon of the scenario):
  purchase_spend          = Σ units × lane landed price + Σ overtime units × disclosed premium
  premium_spend           = Σ overtime units × premium + Σ alternate units × max(0, alt price − planned price)
                            + activation fees
  holding_cost            = Σ_week carried *new* inventory × valuation × annual rate × 7/365
  incremental_buyer_cost  = premium_spend + holding_cost      (cost of mitigating vs. the planned price)
  working_capital_peak    = max_week carried new inventory × valuation   (balance-sheet, NOT a P&L expense)
  shortage_exposure_proxy = units unmet at horizon end × buyer proxy rate (scenario assumption, not a loss)
Joint (two-party) resource cost is not computed in Mode A: it needs supplier cost, which is private.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from nodal_domain.money import D, money

WEEK_FRACTION = D(7) / D(365)


@dataclass
class CostLine:
    lane_id: str
    role: str
    regular_units: int
    overtime_units: int
    unit_price: Decimal
    flex_premium_per_unit: Decimal
    reference_unit_price: Decimal


@dataclass
class CarriedInventory:
    week_start: str
    part_id: str
    plant_id: str
    units: int
    valuation_unit_cost: Decimal


@dataclass
class PlanFinancials:
    purchase_spend_eur: Decimal
    premium_spend_eur: Decimal
    overtime_premium_eur: Decimal
    alternate_price_delta_eur: Decimal
    activation_fees_eur: Decimal
    holding_cost_eur: Decimal
    incremental_buyer_cost_eur: Decimal
    working_capital_peak_eur: Decimal
    shortage_exposure_proxy_eur: Decimal
    currency: str = "EUR"
    basis: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        out = {k: f"{v:.2f}" for k, v in self.__dict__.items() if isinstance(v, Decimal)}
        out["currency"] = self.currency
        out["joint_resource_cost_eur"] = None
        out["joint_resource_cost_status"] = "NOT_COMPUTED_MODE_A_SUPPLIER_COST_PRIVATE"
        out["basis"] = self.basis
        return out


def plan_financials(lines: list[CostLine], carried: list[CarriedInventory], *, activation_fees: Decimal,
                    holding_rate_annual: Decimal, unmet_units_at_end: int, exposure_proxy_per_unit: Decimal) -> PlanFinancials:
    purchase = D(0)
    ot_premium = D(0)
    alt_delta = D(0)
    for ln in lines:
        units = ln.regular_units + ln.overtime_units
        purchase += D(units) * ln.unit_price + D(ln.overtime_units) * ln.flex_premium_per_unit
        ot_premium += D(ln.overtime_units) * ln.flex_premium_per_unit
        if ln.role == "ALTERNATE":
            alt_delta += D(units) * max(D(0), ln.unit_price - ln.reference_unit_price)
    holding = D(0)
    by_week: dict[str, Decimal] = {}
    for c in carried:
        value = D(c.units) * c.valuation_unit_cost
        holding += value * D(holding_rate_annual) * WEEK_FRACTION
        by_week[c.week_start] = by_week.get(c.week_start, D(0)) + value
    premium = ot_premium + alt_delta + D(activation_fees)
    return PlanFinancials(
        purchase_spend_eur=money(purchase + D(activation_fees)),
        premium_spend_eur=money(premium),
        overtime_premium_eur=money(ot_premium),
        alternate_price_delta_eur=money(alt_delta),
        activation_fees_eur=money(activation_fees),
        holding_cost_eur=money(holding),
        incremental_buyer_cost_eur=money(premium + holding),
        working_capital_peak_eur=money(max(by_week.values(), default=D(0))),
        shortage_exposure_proxy_eur=money(D(unmet_units_at_end) * D(exposure_proxy_per_unit)),
        basis=[
            "Mode A: buyer prices and supplier-disclosed premiums only",
            "Holding cost = carried new inventory x valuation x annual rate x 7/365 per week",
            "Working capital peak is an inventory balance, not an expense",
            "Shortage exposure is a scenario proxy, not a validated loss",
        ],
    )
