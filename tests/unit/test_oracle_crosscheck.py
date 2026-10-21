"""Cross-check our Pyomo/HiGHS engine against the data generator's independent scipy oracle.

Two independent implementations must agree on the *physical* outcome (unmet units) for every curated
case and mitigation mode. Objective values are not compared: the oracle uses unit placeholder costs,
we use the snapshot's buyer prices.
"""
import json

import pytest

from nodal_domain.enums import SolveStatus
from nodal_optimization.case_inputs import fixture_scenario
from nodal_optimization.milp_model import solve_scenario

MODES = ["baseline", "overtime", "alternate", "prebuild", "hybrid"]


def _fixtures(store):
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((store.root / "scenarios").glob("CASE-*.json"))]


def test_every_case_and_mode_matches_oracle(store):
    fixtures = _fixtures(store)
    assert fixtures, "no curated case fixtures found"
    mismatches = []
    for f in fixtures:
        for mode in MODES:
            expected = f["results"][mode]
            inp, econ = fixture_scenario(store, f, mode)
            r = solve_scenario(inp, exposure_proxy_per_unit=econ.exposure_proxy_per_unit)
            if expected["status"] == "OPTIMAL":
                ok = r.status == SolveStatus.OPTIMAL and r.unmet_units_at_end == expected["unmet_units"]
            else:
                ok = r.status.value == expected["status"]
            if not ok:
                mismatches.append((f["case_id"], f["category"], mode, expected["unmet_units"], r.status.value, r.unmet_units_at_end))
    assert not mismatches, mismatches


def test_shared_machine_golden_matches(store):
    g = store.golden("shared_bottleneck")
    f = store.case_fixture(g["case_id"])
    r = solve_scenario(fixture_scenario(store, f, "baseline")[0])
    assert r.unmet_units_at_end == g["minimum_unmet_units"]
    zero_modes = {m for m in MODES if solve_scenario(fixture_scenario(store, f, m)[0]).unmet_units_at_end == 0}
    assert zero_modes == set(g["demo_steps"][2]["assert"]["zero_shortage_modes"])


def test_zero_shortage_impossible_golden(store):
    g = store.golden("zero_shortage_impossible")
    base = store.case_fixture("CASE-000001")
    fixture = dict(base, **g["input"])
    inp, _ = fixture_scenario(store, fixture, "hybrid", require_zero_shortage=True)
    r = solve_scenario(inp)
    assert r.status.value == g["result"]["status"] == "INFEASIBLE"
    assert r.releases == []


@pytest.mark.parametrize("case_category", ["COUNTEROFFER_FEASIBILITY"])
def test_counteroffer_recompute_matches_oracle(store, case_category):
    for f in _fixtures(store):
        if f["category"] != case_category or "counteroffer_recomputed_result" not in f:
            continue
        inp, _ = fixture_scenario(store, f, "alternate", overrides={"alternate_arrives_in_time": False})
        r = solve_scenario(inp)
        assert r.unmet_units_at_end == f["counteroffer_recomputed_result"]["unmet_units"]
