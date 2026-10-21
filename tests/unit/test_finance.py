from decimal import Decimal

from nodal_finance.payment_terms import payment_term_effect
from nodal_finance.plan_costs import CarriedInventory, CostLine, plan_financials


def test_payment_terms_golden_case_b():
    e = payment_term_effect("40000.00", "0.08", 60, 15)
    assert e.buyer_incremental_financing_cost_eur == Decimal("394.52")
    assert e.supplier_financing_benefit_eur == Decimal("394.52")
    # A payment-term change moves cash timing between parties; it creates no consolidated value.
    assert e.consolidated_net_financing_eur == Decimal("0.00")


def test_payment_terms_matches_generator_golden(store):
    g = store.golden("payment_terms")
    e = payment_term_effect(g["lot_price_eur"], g["annual_rate"], g["from_payment_days"], g["to_payment_days"])
    assert f"{e.buyer_incremental_financing_cost_eur:.2f}" == g["buyer_incremental_financing_cost_eur"]
    assert f"{e.supplier_financing_benefit_eur:.2f}" == g["supplier_financing_benefit_eur"]
    assert f"{e.consolidated_net_financing_eur:.2f}" == g["consolidated_net_financing_eur"]


def test_plan_costs_separate_premium_from_purchase_and_working_capital():
    lines = [CostLine("L1", "PRIMARY", 400, 100, Decimal("10.00"), Decimal("1.50"), Decimal("10.00")),
             CostLine("L2", "ALTERNATE", 200, 0, Decimal("12.00"), Decimal("0"), Decimal("10.00"))]
    carried = [CarriedInventory("2026-11-16", "P", "PL", 200, Decimal("8.00"))]
    f = plan_financials(lines, carried, activation_fees=Decimal("0"), holding_rate_annual=Decimal("0.18"),
                        unmet_units_at_end=5, exposure_proxy_per_unit=Decimal("1000"))
    assert f.purchase_spend_eur == Decimal("7550.00")  # 500*10 + 100*1.5 + 200*12
    assert f.overtime_premium_eur == Decimal("150.00")
    assert f.alternate_price_delta_eur == Decimal("400.00")
    assert f.holding_cost_eur == Decimal("5.52")  # 1600 * 0.18 * 7/365
    assert f.incremental_buyer_cost_eur == Decimal("555.52")
    assert f.working_capital_peak_eur == Decimal("1600.00")
    assert f.shortage_exposure_proxy_eur == Decimal("5000.00")
    assert f.as_dict()["joint_resource_cost_eur"] is None
