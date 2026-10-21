"""Scenario job execution, shared by the worker process and the optional inline worker thread.

The API only enqueues (202). A worker claims QUEUED runs atomically, builds inputs from the immutable
snapshot + the case's recorded input overrides, solves each requested mode, validates, and stores a
full (unprojected) result. Projections for each principal are applied on read.
"""
from __future__ import annotations

import time
import traceback
from dataclasses import replace
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update

from nodal_domain.digest import sha256_digest
from nodal_domain.enums import RunState, SolveStatus
from nodal_domain.money import money_str
from nodal_finance.plan_costs import CarriedInventory, CostLine, plan_financials
from nodal_optimization.case_inputs import fixture_scenario, snapshot_scenario
from nodal_optimization.milp_model import ScenarioResult, solve_scenario
from nodal_optimization.model_inputs import ScenarioInput, SolverOptions

from ..db import Case, ScenarioRun, utcnow
from .audit import outbox

MODE_ORDER = ["baseline", "overtime", "alternate", "prebuild", "hybrid"]
STATUS_RANK = {s: i for i, s in enumerate([SolveStatus.OPTIMAL, SolveStatus.FEASIBLE_WITH_GAP, SolveStatus.TIME_LIMIT,
                                            SolveStatus.INFEASIBLE, SolveStatus.ERROR, SolveStatus.NOT_RUN])}


def apply_supplier_limits(inp: ScenarioInput, limits: list[dict[str, Any]]) -> ScenarioInput:
    """Apply supplier-confirmed limits (from counteroffers or capacity updates) to the lanes.

    Each limit: {lane_id, week, max_units, moved_to_week?}. A delivery moved to a later week removes the
    capacity in the original week; if the new week is inside the horizon the units are allowed there.
    """
    lanes = []
    for ln in inp.lanes:
        new = replace(ln, committed_cap=dict(ln.committed_cap), flex_cap=dict(ln.flex_cap), max_total=dict(ln.max_total))
        for lim in limits:
            if lim["lane_id"] != ln.lane_id:
                continue
            week, moved = lim["week"], lim.get("moved_to_week")
            overtime_only = lim.get("max_overtime_units") is not None
            qty = int(lim["max_overtime_units"] if overtime_only else lim["max_units"])
            release_week = _release_week(inp.weeks, week, ln.lead_weeks)
            target = release_week
            if moved and moved != week:
                # Nothing on this lane in the original week beyond what is already committed; units move later.
                if release_week:
                    if overtime_only:
                        new.flex_cap[release_week] = 0
                    else:
                        new.max_total[release_week] = 0
                target = _release_week(inp.weeks, moved, ln.lead_weeks)
                if target and not overtime_only:
                    new.committed_cap[target] = max(new.committed_cap.get(target, 0), qty)
            if not target:
                continue  # moved outside the horizon: no capacity inside it
            if overtime_only:
                new.flex_cap[target] = qty if (moved and moved != week) else min(new.flex_cap.get(target, 0), qty)
            else:
                cur = new.max_total.get(target, new.committed_cap.get(target, 0) + new.flex_cap.get(target, 0))
                new.max_total[target] = qty if (moved and moved != week) else min(cur, qty)
        lanes.append(new)
    return replace(inp, lanes=lanes, assumptions=inp.assumptions + [f"Supplier-confirmed limits applied: {len(limits)}"] if limits else inp.assumptions)


def _release_week(weeks: list[str], arrival_week: str, lead: int) -> str | None:
    if arrival_week not in weeks:
        return None
    idx = weeks.index(arrival_week) - lead
    return weeks[idx] if idx >= 0 else None


def build_inputs(store, case: Case, request: dict[str, Any], mode: str) -> tuple[ScenarioInput, Any, dict[str, Any]]:
    scope = request.get("scope", "CASE_FIXTURE")
    sol = request.get("solver", {})
    solver = SolverOptions(time_limit_seconds=float(sol.get("time_limit_seconds", 30)),
                           max_relative_gap=float(sol.get("max_relative_gap", 0.0)))
    cons = request.get("constraints", {})
    zero = bool(cons.get("require_zero_shortage", False))
    budget = cons.get("max_incremental_cost_eur")
    overrides = dict((case.input_overrides or {}).get("fixture", {}))
    limits = list((case.input_overrides or {}).get("supplier_limits", [])) + list(request.get("supplier_limits", []))
    meta: dict[str, Any] = {"scope": scope}
    if scope == "SNAPSHOT_HORIZON":
        if not case.disruption_id:
            raise ValueError("case has no disruption event for a snapshot-horizon run")
        inp, econ, info = snapshot_scenario(store, case.disruption_id, mode, tenant_id=case.tenant_id, solver=solver,
                                            require_zero_shortage=zero, max_incremental_cost=Decimal(str(budget)) if budget else None)
        meta.update(info)
    else:
        fixture = store.case_fixture(case.case_id)
        if fixture is None:
            raise ValueError(f"no curated fixture for {case.case_id}")
        inp, econ = fixture_scenario(store, fixture, mode, solver=solver, require_zero_shortage=zero, overrides=overrides)
        if budget:
            inp = replace(inp, max_incremental_cost=Decimal(str(budget)))
    if limits:
        inp = apply_supplier_limits(inp, limits)
    return inp, econ, meta


def input_fingerprint(inp: ScenarioInput) -> str:
    return sha256_digest({
        "weeks": inp.weeks, "modes": sorted(inp.modes), "zero": inp.require_zero_shortage,
        "budget": str(inp.max_incremental_cost), "holding": str(inp.holding_rate_annual),
        "items": [(i.part_id, i.plant_id, i.tenant_id, i.opening_usable, i.demand, i.receipts, str(i.valuation_unit_cost)) for i in inp.items],
        "lanes": [(l.lane_id, l.role, l.qualified, l.lead_weeks, str(l.unit_price), l.committed_cap, l.flex_cap, l.max_total,
                   str(l.flex_premium_per_unit), l.lot_multiple, l.locked_releases) for l in inp.lanes],
        "resources": [(r.resource_id, r.regular_hours, r.overtime_hours) for r in inp.resources],
        "requirements": [(q.lane_id, q.resource_id, q.hours_per_unit, q.setup_hours) for q in inp.requirements],
    })


def serialize(result: ScenarioResult, inp: ScenarioInput, econ) -> dict[str, Any]:
    lanes = {ln.lane_id: ln for ln in inp.lanes}
    fin = result.financials.as_dict() if result.financials else None
    return {
        "label": result.label,
        "status": result.status.value,
        "message": result.message,
        "offer_eligible": result.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE_WITH_GAP) and not result.validation_errors,
        "kpis": {
            "unmet_units_at_end": result.unmet_units_at_end,
            "late_unit_weeks": result.late_unit_weeks,
            "peak_backlog_units": result.peak_backlog_units,
            "primary_units": result.units_by("PRIMARY") if result.has_plan else None,
            "alternate_units": result.units_by("ALTERNATE") if result.has_plan else None,
            "overtime_units": result.units_by(overtime=True) if result.has_plan else None,
            "prebuild_peak_units": max((iw.new_inventory for iw in result.item_weeks), default=0) if result.has_plan else None,
            "earliest_relief_week": _earliest_relief(result),
        },
        "financials": fin,
        "financials_by_tenant": financials_by_tenant(result, inp, econ),
        "solver": {"name": "highs", "interface": "pyomo.appsi", "relative_gap": result.relative_gap,
                   "solver_wall_seconds": round(result.solver_seconds, 4), "build_seconds": round(result.build_seconds, 4),
                   "stage1_termination": result.stage1.termination if result.stage1 else None,
                   "stage2_termination": result.stage2.termination if result.stage2 else None,
                   "model_size": result.model_size},
        "releases": [{"lane_id": r.lane_id, "supplier_org_id": r.supplier_org_id, "part_id": r.part_id, "plant_id": r.plant_id,
                      "role": r.role, "release_week": r.release_week, "arrival_week": r.arrival_week,
                      "regular_units": r.regular_units, "overtime_units": r.overtime_units,
                      "tenant_id": next((i.tenant_id for i in inp.items if i.key == (r.part_id, r.plant_id)), None),
                      "unit_price_eur": money_str(lanes[r.lane_id].unit_price),
                      "disclosed_premium_eur": money_str(lanes[r.lane_id].flex_premium_per_unit)} for r in result.releases],
        "item_weeks": [dict(iw.__dict__, tenant_id=next((i.tenant_id for i in inp.items if i.key == (iw.part_id, iw.plant_id)), None))
                       for iw in result.item_weeks],
        "resource_weeks": [dict(rw.__dict__, binding=rw.binding) for rw in result.resource_weeks],
        "binding_constraints": result.binding_constraints,
        "diagnostics": result.diagnostics,
        "warnings": result.warnings,
        "validation_errors": result.validation_errors,
        "assumptions": inp.assumptions,
        "lane_provenance": {ln.lane_id: {"role": ln.role, "supplier_org_id": ln.supplier_org_id, "qualified": ln.qualified,
                                         "lead_weeks": ln.lead_weeks, "provenance": ln.provenance, "part_id": ln.part_id,
                                         "plant_id": ln.plant_id,
                                         "tenant_id": next((i.tenant_id for i in inp.items if i.key == ln.item_key), None)}
                            for ln in inp.lanes},
        "input_hash": input_fingerprint(inp),
    }


def financials_by_tenant(result: ScenarioResult, inp: ScenarioInput, econ) -> dict[str, Any]:
    """Recompute buyer financials separately for each tenant in scope, so a multi-buyer case never mixes
    one buyer's prices into another buyer's totals."""
    if not result.has_plan:
        return {}
    lanes = {ln.lane_id: ln for ln in inp.lanes}
    items = {it.key: it for it in inp.items}
    out = {}
    for tenant in sorted({it.tenant_id for it in inp.items}):
        keys = {k for k, it in items.items() if it.tenant_id == tenant}
        lines: dict[str, CostLine] = {}
        for rl in result.releases:
            if (rl.part_id, rl.plant_id) not in keys:
                continue
            ln = lanes[rl.lane_id]
            cl = lines.setdefault(rl.lane_id, CostLine(rl.lane_id, ln.role, 0, 0, ln.unit_price, ln.flex_premium_per_unit,
                                                       items[ln.item_key].reference_unit_price))
            cl.regular_units += rl.regular_units
            cl.overtime_units += rl.overtime_units
        carried = [CarriedInventory(iw.week_start, iw.part_id, iw.plant_id, iw.new_inventory, items[(iw.part_id, iw.plant_id)].valuation_unit_cost)
                   for iw in result.item_weeks if (iw.part_id, iw.plant_id) in keys and iw.new_inventory]
        end: dict[tuple, int] = {}
        for iw in result.item_weeks:
            if (iw.part_id, iw.plant_id) in keys:
                end[(iw.part_id, iw.plant_id)] = iw.backlog
        fees = sum((lanes[a].activation_cost for a in result.activated_lanes if lanes[a].item_key in keys), Decimal(0))
        out[tenant] = plan_financials(list(lines.values()), carried, activation_fees=fees, holding_rate_annual=inp.holding_rate_annual,
                                      unmet_units_at_end=sum(end.values()), exposure_proxy_per_unit=econ.exposure_proxy_per_unit).as_dict()
    return out


def _earliest_relief(result: ScenarioResult) -> str | None:
    if not result.has_plan:
        return None
    mitig = [r.arrival_week for r in result.releases if r.role == "ALTERNATE" or r.overtime_units]
    return min(mitig) if mitig else None


def execute_run(session_factory, store, run_id: str, worker_id: str) -> bool:
    """Claim and execute one run. Returns False if another worker claimed it first."""
    with session_factory() as s:
        claimed = s.execute(update(ScenarioRun).where(ScenarioRun.run_id == run_id, ScenarioRun.state == RunState.QUEUED.value)
                            .values(state=RunState.RUNNING.value, worker_id=worker_id, started_at=utcnow())).rowcount
        s.commit()
    if not claimed:
        return False
    started = time.perf_counter()
    with session_factory() as s:
        run = s.get(ScenarioRun, run_id)
        case = s.get(Case, run.case_id)
        request = dict(run.request)
        try:
            results: dict[str, Any] = {}
            hashes = []
            for mode in [m for m in MODE_ORDER if m in request.get("modes", MODE_ORDER)]:
                inp, econ, meta = build_inputs(store, case, request, mode)
                res = solve_scenario(inp, exposure_proxy_per_unit=econ.exposure_proxy_per_unit)
                results[mode] = serialize(res, inp, econ) | {"scope": meta}
                hashes.append(results[mode]["input_hash"])
            run.state = RunState.VALIDATING.value
            statuses = [SolveStatus(r["status"]) for r in results.values()]
            run.overall_status = max(statuses, key=lambda st: STATUS_RANK[st]).value if statuses else SolveStatus.NOT_RUN.value
            run.results = results
            run.input_hash = sha256_digest(hashes)
            run.state = RunState.COMPLETED.value
            if case.state in ("DETECTED", "INVESTIGATING", "COUNTERED"):
                case.state = "SCENARIOS_READY"
                case.version += 1
                case.updated_at = utcnow()
            outbox(s, "scenario.completed", case.tenant_id, run.run_id, 1,
                   {"run_id": run.run_id, "case_id": case.case_id, "overall_status": run.overall_status})
        except Exception as exc:
            run.state = RunState.FAILED.value
            run.overall_status = SolveStatus.ERROR.value
            run.error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}"
        run.finished_at = utcnow()
        run.wall_seconds = round(time.perf_counter() - started, 4)
        s.commit()
    return True


def pending_run_ids(session_factory, limit: int = 10) -> list[str]:
    with session_factory() as s:
        return list(s.scalars(select(ScenarioRun.run_id).where(ScenarioRun.state == RunState.QUEUED.value)
                              .order_by(ScenarioRun.created_at).limit(limit)))
