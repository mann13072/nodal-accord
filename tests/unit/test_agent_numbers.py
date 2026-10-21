from nodal_agent_tools.numbers import extract_numbers, unverified_numbers

TOOL = [{"kpis": {"unmet_units_at_end": 200, "late_unit_weeks": 1400}, "financials": {"incremental_buyer_cost_eur": "536.00"},
         "capacity_loss_percent": "0.200000", "note": "resource RES-000004 regular hours full in 2026-11-23",
         "gap": 0.0123}]


def test_ids_and_dates_are_not_numbers():
    toks = [t for t, _, _ in extract_numbers("See CASE-000004 and LANE-000006 from 2026-11-23 (RUN-1CF26B09F37D).")]
    assert toks == []


def test_numbers_from_tools_are_verified_in_canonical_forms():
    answer = "Baseline leaves 200 units unmet (1,400 late unit-weeks); hybrid costs €536 extra; capacity loss 20%; gap 1.23%."
    assert unverified_numbers(answer, TOOL) == []


def test_invented_numbers_are_flagged():
    assert unverified_numbers("This saves €12,345.67 and 87% of the shortage.", TOOL) == ["12,345.67", "87%"]


def test_small_counts_are_allowed():
    assert unverified_numbers("I compared 5 options across 2 suppliers.", TOOL) == []
