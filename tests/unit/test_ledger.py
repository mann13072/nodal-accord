from hypothesis import given
from hypothesis import strategies as st

from nodal_planning.ledger import run_ledger

WEEKS = ["2026-11-02", "2026-11-09", "2026-11-16", "2026-11-23"]


def test_zero_demand_means_zero_shortage():
    res = run_ledger(WEEKS, 0, {}, {})
    assert res.first_shortage_week is None and res.final_backlog == 0


def test_backlog_carries_and_recovers():
    res = run_ledger(WEEKS, 50, {WEEKS[2]: 200}, {WEEKS[0]: 100, WEEKS[1]: 100, WEEKS[2]: 0})
    assert [w.closing_backlog for w in res.weeks] == [50, 150, 0, 0]
    assert res.first_shortage_week == WEEKS[0]
    assert res.weeks[2].closing_usable == 50
    assert res.peak_backlog == 150


def test_tiny_feasible_golden(store):
    g = store.golden("tiny_feasible")
    # 200 usable + 40 h / 0.1 h per unit = 600 units => no shortage.
    producible = int(g["available_hours"] / float(g["hours_per_unit"]))
    res = run_ledger(["2026-11-23"], g["usable_units"], {"2026-11-23": producible}, {"2026-11-23": g["demand_units"]})
    assert res.final_backlog == g["unmet_units"] == 0


quantities = st.dictionaries(st.sampled_from(WEEKS), st.integers(0, 500), max_size=4)


@given(st.integers(0, 1000), quantities, quantities, st.integers(1, 300))
def test_more_stock_never_increases_shortage(opening, receipts, demand, extra):
    a = run_ledger(WEEKS, opening, receipts, demand)
    b = run_ledger(WEEKS, opening + extra, receipts, demand)
    assert b.backlog_unit_weeks <= a.backlog_unit_weeks


@given(st.integers(0, 1000), quantities, quantities)
def test_ledger_conserves_units(opening, receipts, demand):
    res = run_ledger(WEEKS, opening, receipts, demand)
    for w in res.weeks:
        assert w.closing_usable >= 0 and w.closing_backlog >= 0
        assert w.opening_usable + w.receipts - w.fulfilled == w.closing_usable
        assert w.demand + w.prior_backlog - w.fulfilled == w.closing_backlog
    total_in = opening + sum(receipts.values())
    total_out = sum(w.fulfilled for w in res.weeks)
    assert total_in - total_out == res.weeks[-1].closing_usable
