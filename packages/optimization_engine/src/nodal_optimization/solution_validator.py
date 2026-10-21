"""Independent post-solve validation (blueprint §11.6).

Re-derives every balance and capacity from the integer plan and the *original* inputs, without
looking at the Pyomo model. Any violation means the run is labelled ERROR and cannot become an offer.
"""
from __future__ import annotations

from .model_inputs import ScenarioInput

TOL = 1e-6


def validate(inp: ScenarioInput, result) -> list[str]:
    errors: list[str] = []
    weeks = inp.weeks
    widx = {w: i for i, w in enumerate(weeks)}
    lanes = {ln.lane_id: ln for ln in inp.lanes}
    items = {it.key: it for it in inp.items}

    # Lane rules: qualification, mode permission, lead time, capacity, lots.
    per_lane_week: dict[tuple[str, str], tuple[int, int]] = {}
    for rl in result.releases:
        ln = lanes.get(rl.lane_id)
        if ln is None:
            errors.append(f"release on unknown lane {rl.lane_id}")
            continue
        if rl.regular_units < 0 or rl.overtime_units < 0:
            errors.append(f"negative quantity on {rl.lane_id} {rl.release_week}")
        if not ln.qualified:
            errors.append(f"unqualified lane {rl.lane_id} received {rl.units} units")
        if ln.role == "ALTERNATE" and not inp.allow_alternate:
            errors.append(f"alternate lane {rl.lane_id} used while ALTERNATE_SOURCE is disabled")
        if rl.overtime_units and not inp.allow_overtime:
            errors.append(f"overtime on {rl.lane_id} while OVERTIME is disabled")
        if widx[rl.arrival_week] - widx[rl.release_week] != ln.lead_weeks:
            errors.append(f"lead time broken on {rl.lane_id}: {rl.release_week} -> {rl.arrival_week}")
        if rl.regular_units > ln.committed_cap.get(rl.release_week, 0):
            errors.append(f"{rl.lane_id} regular {rl.regular_units} > committed {ln.committed_cap.get(rl.release_week, 0)} in {rl.release_week}")
        if rl.overtime_units > ln.flex_cap.get(rl.release_week, 0):
            errors.append(f"{rl.lane_id} overtime {rl.overtime_units} > disclosed flex in {rl.release_week}")
        if rl.release_week in ln.max_total and rl.units > ln.max_total[rl.release_week]:
            errors.append(f"{rl.lane_id} exceeds contractual ceiling in {rl.release_week}")
        if ln.lot_multiple > 1 and rl.units % ln.lot_multiple:
            errors.append(f"{rl.lane_id} quantity {rl.units} not a multiple of {ln.lot_multiple}")
        if ln.min_lot and 0 < rl.units < ln.min_lot:
            errors.append(f"{rl.lane_id} quantity {rl.units} below minimum lot {ln.min_lot}")
        per_lane_week[(rl.lane_id, rl.release_week)] = (rl.regular_units, rl.overtime_units)
    for ln in inp.lanes:
        for w, q in ln.locked_releases.items():
            got = sum(per_lane_week.get((ln.lane_id, w), (0, 0)))
            if got != q:
                errors.append(f"locked release on {ln.lane_id} {w} changed: {q} -> {got}")

    # Shared resources: one budget across all lanes (no double counting).
    for res in inp.resources:
        reqs = [rq for rq in inp.requirements if rq.resource_id == res.resource_id]
        for w in weeks:
            reg = sum(rq.hours_per_unit * per_lane_week.get((rq.lane_id, w), (0, 0))[0] for rq in reqs)
            reg += sum(rq.setup_hours for rq in reqs if rq.setup_hours and sum(per_lane_week.get((rq.lane_id, w), (0, 0))) > 0)
            ot = sum(rq.hours_per_unit * per_lane_week.get((rq.lane_id, w), (0, 0))[1] for rq in reqs)
            if reg > res.regular_hours.get(w, 0.0) + TOL:
                errors.append(f"resource {res.resource_id} over regular hours in {w}: {reg:.4f} > {res.regular_hours.get(w, 0.0)}")
            ot_cap = res.overtime_hours.get(w, 0.0) if inp.allow_overtime else 0.0
            if ot > ot_cap + TOL:
                errors.append(f"resource {res.resource_id} over overtime hours in {w}: {ot:.4f} > {ot_cap}")

    # Item ledgers reconcile from scratch.
    arrivals: dict[tuple, int] = {}
    for rl in result.releases:
        arrivals[(rl.part_id, rl.plant_id, rl.arrival_week)] = arrivals.get((rl.part_id, rl.plant_id, rl.arrival_week), 0) + rl.units
    rows: dict[tuple, dict[str, object]] = {}
    for iw in result.item_weeks:
        rows[(iw.part_id, iw.plant_id, iw.week_start)] = iw
    for key, it in items.items():
        old, new, backlog = it.opening_usable, 0, 0
        for w in weeks:
            iw = rows.get((it.part_id, it.plant_id, w))
            if iw is None:
                errors.append(f"missing ledger row {key} {w}")
                break
            rec = int(it.receipts.get(w, 0))
            arr = arrivals.get((it.part_id, it.plant_id, w), 0)
            dem = int(it.demand.get(w, 0))
            if iw.new_arrivals != arr or iw.receipts != rec or iw.demand != dem:
                errors.append(f"ledger inputs differ for {key} {w}")
            if min(iw.served_from_stock, iw.served_from_new, iw.backlog, iw.old_inventory, iw.new_inventory) < 0:
                errors.append(f"negative ledger value for {key} {w}")
            old = old + rec - iw.served_from_stock
            new = new + arr - iw.served_from_new
            if old != iw.old_inventory or new != iw.new_inventory:
                errors.append(f"inventory does not reconcile for {key} {w}")
            if old < 0 or new < 0:
                errors.append(f"negative inventory for {key} {w}")
            if not inp.allow_prebuild and new != 0:
                errors.append(f"new production carried in {key} {w} while PREBUILD is disabled")
            served = iw.served_from_stock + iw.served_from_new
            if served + iw.backlog != dem + backlog:
                errors.append(f"demand/backlog does not reconcile for {key} {w}")
            backlog = iw.backlog
            if inp.require_zero_shortage and backlog:
                errors.append(f"zero-shortage requirement violated for {key} {w}")
    if result.financials and result.financials.purchase_spend_eur < 0:
        errors.append("negative purchase spend")
    return errors
