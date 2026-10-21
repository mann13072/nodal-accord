"""12-week canonical scope: multi-sourced lanes, shared resources, validation and mode monotonicity."""
from nodal_domain.enums import SolveStatus
from nodal_optimization.case_inputs import snapshot_scenario
from nodal_optimization.milp_model import solve_scenario
from nodal_optimization.model_inputs import SolverOptions


def test_current_sources_are_all_lanes_with_committed_capacity(store):
    inp, _, _ = snapshot_scenario(store, "DISR-000001", "baseline")
    for ln in inp.lanes:
        has_capacity = any(v > 0 for v in store.lane_capacity_for(ln.lane_id).values() for v in [v["committed_units"]])
        assert (ln.role == "PRIMARY") == has_capacity


def test_snapshot_scope_validates_and_mitigation_never_worsens_service(store):
    opts = SolverOptions(time_limit_seconds=30, max_relative_gap=0.0)
    base = solve_scenario(snapshot_scenario(store, "DISR-000001", "baseline", solver=opts)[0])
    hyb = solve_scenario(snapshot_scenario(store, "DISR-000001", "hybrid", solver=opts)[0], seed=base)
    for r in (base, hyb):
        assert r.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE_WITH_GAP)
        assert r.validation_errors == []
    # Seeded with the baseline plan, a mitigation run can never report worse service than baseline.
    weighted = lambda r: sum(next(i.criticality_weight for i in snapshot_scenario(store, "DISR-000001", "baseline")[0].items
                                  if (i.part_id, i.plant_id) == (iw.part_id, iw.plant_id)) * iw.backlog for iw in r.item_weeks)
    assert weighted(hyb) <= weighted(base)


def test_unimproved_seed_is_flagged_not_presented_as_a_recommendation(store):
    from nodal_optimization.model_inputs import SolverOptions as SO

    inp = snapshot_scenario(store, "DISR-000001", "hybrid", solver=SO(time_limit_seconds=0.0))[0]
    r = solve_scenario(inp)
    assert r.status in (SolveStatus.FEASIBLE_WITH_GAP, SolveStatus.TIME_LIMIT)
    if r.status == SolveStatus.FEASIBLE_WITH_GAP and r.relative_gap not in (None, 0.0):
        assert any("did not improve" in w or "not proven" in w for w in r.warnings)


def test_other_tenant_economics_are_withheld_from_the_objective(store):
    from nodal_optimization.case_inputs import fixture_scenario

    f = store.case_fixture("CASE-000010")  # MULTI_BUYER: one TEN-000001 lane and one TEN-000002 lane on one resource
    inp, _ = fixture_scenario(store, f, "overtime")
    owner = f["tenant_ids"][0]
    for it in inp.items:
        if it.tenant_id != owner:
            assert it.reference_unit_price == 0 and it.valuation_unit_cost == 0 and it.criticality_weight == 1
    for ln in inp.lanes:
        if next(i.tenant_id for i in inp.items if i.key == ln.item_key) != owner:
            assert ln.unit_price == 0 and ln.flex_premium_per_unit == 0


def test_truncated_scope_reserves_hours_of_out_of_scope_lanes(store):
    inp, _, scope = snapshot_scenario(store, "DISR-000001", "baseline", max_items=1)
    in_scope = {ln.lane_id for ln in inp.lanes}
    for res in inp.resources:
        outside = [l for l in store.lanes_by_resource.get(res.resource_id, []) if l not in in_scope]
        if not outside:
            continue
        w = inp.weeks[0]
        row = store.capacity_calendar_for(res.resource_id)[w]
        raw = float(row["available_hours"]) - float(row["firm_reserved_hours"])
        assert res.regular_hours[w] < raw or res.regular_hours[w] == 0.0
    assert scope["out_of_scope_reserved_hours"] >= 0


def test_shared_resources_carry_all_lanes_that_use_them(store):
    inp, _, _ = snapshot_scenario(store, "DISR-000004", "baseline")
    lanes = {ln.lane_id for ln in inp.lanes}
    for res in inp.resources:
        users = set(store.lanes_by_resource.get(res.resource_id, []))
        tenants_items = {(store.lanes_by_id[l]["tenant_id"], store.lanes_by_id[l]["destination_plant_id"], store.lanes_by_id[l]["part_id"]) for l in users}
        scoped = {(i.tenant_id, i.plant_id, i.part_id) for i in inp.items}
        if tenants_items <= scoped:
            assert users <= lanes, f"{res.resource_id} budget would ignore lanes {users - lanes}"
