"""Simple-interest payment-term financing illustration: P * r * (Δdays / 365).

Sign convention: the party that pays earlier bears a funding cost; the party paid earlier gains the
same amount. In a consolidated two-party view the effect nets to zero: a payment-term change moves
cash timing, it does not create supply-chain value. This is not a bank's actual cost of funds.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from nodal_domain.money import D, money


@dataclass(frozen=True)
class FinancingEffect:
    principal_eur: Decimal
    annual_rate: Decimal
    from_payment_days: int
    to_payment_days: int
    buyer_incremental_financing_cost_eur: Decimal
    supplier_financing_benefit_eur: Decimal
    consolidated_net_financing_eur: Decimal
    basis: str = "SIMPLE_INTEREST_ILLUSTRATION_365_DAY_YEAR"

    def as_dict(self) -> dict[str, str | int]:
        return {
            "principal_eur": f"{self.principal_eur:.2f}",
            "annual_rate": str(self.annual_rate),
            "from_payment_days": self.from_payment_days,
            "to_payment_days": self.to_payment_days,
            "buyer_incremental_financing_cost_eur": f"{self.buyer_incremental_financing_cost_eur:.2f}",
            "supplier_financing_benefit_eur": f"{self.supplier_financing_benefit_eur:.2f}",
            "consolidated_net_financing_eur": f"{self.consolidated_net_financing_eur:.2f}",
            "basis": self.basis,
        }


def payment_term_effect(principal_eur, annual_rate, from_days: int, to_days: int) -> FinancingEffect:
    p, r = D(principal_eur), D(annual_rate)
    if p < 0 or r < 0:
        raise ValueError("principal and rate must be non-negative")
    days_earlier = D(from_days - to_days)  # positive => buyer pays earlier
    amount = money(p * r * days_earlier / D(365))
    buyer_cost = amount
    supplier_benefit = amount
    return FinancingEffect(money(p), r, from_days, to_days, buyer_cost, supplier_benefit, money(buyer_cost - supplier_benefit))
