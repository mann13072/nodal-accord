"""Golden solver fixtures (blueprint §19.2)."""
from decimal import Decimal

from nodal_domain.enums import SolveStatus
from nodal_optimization.milp_model import solve_scenario
from nodal_optimization.model_inputs import (MODE_SETS, ItemInput, LaneInput, Requirement, ResourceInput, ScenarioInput,
                                             SolverOptions)

W = ["2026-11-16", "2026-11-23"]
T = W[1]


def item(part, demand, stock=0, price="10"):
    return ItemInput(part, "PL1", "TEN-1", stock, {T: demand}, {}, Decimal("8"), 1, Decimal(price))


def lane(lid, part, cap, role="PRIMARY", price="10", lead=0, qualified=True, flex=0, premium="0", prior_cap=0, supplier="S1"):
    return LaneInput(lid, supplier, part, "PL1", role, qualified, lead, Decimal(price), {T: cap, W[0]: prior_cap},
                     flex_cap={T: flex}, flex_premium_per_unit=Decimal(premium))


def scenario(items, lanes, mode="baseline", resources=(), reqs=(), weeks=W, **kw):
    return ScenarioInput("t", list(weeks), list(items), list(lanes), list(resources), list(reqs), MODE_SETS[mode],
                         Decimal("0.18"), solver=SolverOptions(time_limit_seconds=20), **kw)


def test_tiny_feasible_hand_computed_optimum():
    # 600 demand, 200 in stock; primary 10 EUR (cap 300), alternate 12 EUR (cap 300).
    # Optimum: 300 primary + 100 alternate, 0 unmet; incremental = 100 * (12-10) = 200.00.
    r = solve_scenario(scenario([item("P", 600, stock=200)],
                                [lane("A1", "P", 300), lane("A2", "P", 300, role="ALTERNATE", price="12", supplier="S2")],
                                mode="alternate"))
    assert r.status == SolveStatus.OPTIMAL
    assert r.unmet_units_at_end == 0
    assert r.units_by("PRIMARY") == 300 and r.units_by("ALTERNATE") == 100
    assert r.financials.incremental_buyer_cost_eur == Decimal("200.00")
    assert r.financials.purchase_spend_eur == Decimal("4200.00")


def test_alternate_with_lead_time_cannot_fix_earlier_shortage():
    r = solve_scenario(scenario([item("P", 600)],
                                [lane("A1", "P", 400), lane("A2", "P", 500, role="ALTERNATE", lead=1, supplier="S2")],
                                mode="alternate"))
    assert r.status == SolveStatus.OPTIMAL
    assert r.unmet_units_at_end == 200
    assert r.units_by("ALTERNATE") == 0


def test_shared_machine_is_one_budget_not_two():
    # Golden case A: 80 h, 0.1 h/unit, demand 600 + 400 -> 100 h needed, 200 units must stay unmet.
    res = ResourceInput("R1", "S1", {T: 80.0, W[0]: 0.0})
    reqs = [Requirement("LA", "R1", 0.1), Requirement("LB", "R1", 0.1)]
    r = solve_scenario(scenario([item("A", 600), item("B", 400)], [lane("LA", "A", 600), lane("LB", "B", 400)],
                                resources=[res], reqs=reqs))
    assert r.status == SolveStatus.OPTIMAL
    assert r.unmet_units_at_end == 200
    used = sum(rw.regular_hours_used for rw in r.resource_weeks if rw.week_start == T)
    assert used <= 80.0 + 1e-9
    assert any("R1" in b for b in r.binding_constraints)


def test_unqualified_cheap_supplier_is_excluded():
    r = solve_scenario(scenario([item("P", 500)],
                                [lane("A1", "P", 500, price="10"),
                                 lane("CHEAP", "P", 500, role="ALTERNATE", price="5", qualified=False, supplier="S9")],
                                mode="alternate"))
    assert r.status == SolveStatus.OPTIMAL
    assert all(rl.lane_id != "CHEAP" for rl in r.releases)


def test_locked_release_blocks_cheaper_reallocation():
    cheap = lane("A2", "P", 500, role="ALTERNATE", price="5", supplier="S2")
    pricey = lane("A1", "P", 500, price="10")
    pricey.locked_releases = {T: 300}
    r = solve_scenario(scenario([item("P", 500, price="10")], [pricey, cheap], mode="alternate"))
    assert r.status == SolveStatus.OPTIMAL
    assert sum(rl.units for rl in r.releases if rl.lane_id == "A1") == 300
    assert sum(rl.units for rl in r.releases if rl.lane_id == "A2") == 200


def test_mandatory_zero_shortage_reports_infeasible_without_inventing_a_plan():
    res = ResourceInput("R1", "S1", {T: 40.0, W[0]: 0.0})
    r = solve_scenario(scenario([item("P", 600)], [lane("A1", "P", 600)], resources=[res],
                                reqs=[Requirement("A1", "R1", 0.1)], require_zero_shortage=True))
    assert r.status == SolveStatus.INFEASIBLE
    assert r.releases == [] and r.unmet_units_at_end is None
    assert any("zero shortage is impossible" in d for d in r.diagnostics)


def test_prebuild_requires_mode_and_carries_holding_cost():
    res = ResourceInput("R1", "S1", {T: 40.0, W[0]: 20.0})
    lanes = [lane("A1", "P", 600, prior_cap=200)]
    reqs = [Requirement("A1", "R1", 0.1)]
    base = solve_scenario(scenario([item("P", 600)], lanes, resources=[res], reqs=reqs))
    pre = solve_scenario(scenario([item("P", 600)], lanes, mode="prebuild", resources=[res], reqs=reqs))
    assert base.unmet_units_at_end == 200 and pre.unmet_units_at_end == 0
    assert pre.financials.working_capital_peak_eur == Decimal("1600.00")  # 200 units x 8 EUR valuation
    assert pre.financials.holding_cost_eur > 0


def test_overtime_consumes_overtime_hours_and_premium():
    res = ResourceInput("R1", "S1", {T: 40.0, W[0]: 0.0}, {T: 20.0})
    r = solve_scenario(scenario([item("P", 600)], [lane("A1", "P", 400, flex=200, premium="1.50")], mode="overtime",
                                resources=[res], reqs=[Requirement("A1", "R1", 0.1)]))
    assert r.status == SolveStatus.OPTIMAL and r.unmet_units_at_end == 0
    assert r.units_by(overtime=True) == 200
    assert r.financials.overtime_premium_eur == Decimal("300.00")


def test_time_limit_is_never_labelled_optimal():
    weeks = [f"2026-{m:02d}-{d:02d}" for m, d in [(10, 26), (11, 2), (11, 9), (11, 16), (11, 23), (11, 30), (12, 7), (12, 14)]]
    items, lanes, reqs, resources = [], [], [], []
    for p in range(30):
        items.append(ItemInput(f"P{p}", "PL1", "TEN-1", 0, {w: 37 + (p * 7 + i * 13) % 50 for i, w in enumerate(weeks)}, {},
                               Decimal("8"), 1 + p % 3, Decimal("10")))
        for s in range(3):
            lid = f"L{p}-{s}"
            lanes.append(LaneInput(lid, f"S{s}", f"P{p}", "PL1", "PRIMARY" if s == 0 else "ALTERNATE", True, s % 2,
                                   Decimal(10 + s + (p % 5) / 10), {w: 31 + (p + s) % 17 for w in weeks},
                                   lot_multiple=7 + s, flex_cap={w: 9 for w in weeks}, flex_premium_per_unit=Decimal("1.3")))
            reqs.append(Requirement(lid, f"R{(p + s) % 4}", 0.1 + 0.01 * s, 0.5))
    for k in range(4):
        resources.append(ResourceInput(f"R{k}", "S", {w: 70.0 for w in weeks}, {w: 10.0 for w in weeks}))
    inp = ScenarioInput("dense", weeks, items, lanes, resources, reqs, MODE_SETS["hybrid"], Decimal("0.18"),
                        solver=SolverOptions(time_limit_seconds=0.0))
    r = solve_scenario(inp)
    assert r.status in (SolveStatus.TIME_LIMIT, SolveStatus.FEASIBLE_WITH_GAP)
    if r.status == SolveStatus.TIME_LIMIT:
        assert r.releases == []
