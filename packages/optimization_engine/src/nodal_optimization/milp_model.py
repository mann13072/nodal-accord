"""Time-indexed mitigation MILP (blueprint §11.2–11.4).

Lexicographic objective:
  stage 1  minimise criticality-weighted late unit-weeks  Σ w_i · B[i,t]
  stage 2  subject to stage-1 optimum (+ tolerance), minimise buyer purchase spend + holding cost

Inventory is split into two pools so 'prebuild' is an explicit decision, not an accident:
  old pool  Io: opening usable stock + confirmed receipts (each counted once)
  new pool  In: arrivals from releases decided here; forced to zero unless PREBUILD/HYBRID
Shared resources impose ONE hour budget per week across every lane that uses them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

import pyomo.environ as pyo

from nodal_domain.enums import SolveStatus
from nodal_domain.money import D, money
from nodal_finance.plan_costs import CarriedInventory, CostLine, PlanFinancials, plan_financials

from .model_inputs import LaneInput, ScenarioInput
from .solvers import SolveOutcome, solve_highs

EPS = 1e-6


@dataclass
class ReleaseLine:
    lane_id: str
    supplier_org_id: str
    part_id: str
    plant_id: str
    role: str
    release_week: str
    arrival_week: str
    regular_units: int
    overtime_units: int

    @property
    def units(self) -> int:
        return self.regular_units + self.overtime_units


@dataclass
class ItemWeek:
    part_id: str
    plant_id: str
    week_start: str
    demand: int
    receipts: int
    new_arrivals: int
    served_from_stock: int
    served_from_new: int
    backlog: int
    old_inventory: int
    new_inventory: int


@dataclass
class ResourceWeek:
    resource_id: str
    week_start: str
    regular_hours_used: float
    regular_hours_available: float
    overtime_hours_used: float
    overtime_hours_available: float

    @property
    def binding(self) -> bool:
        return self.regular_hours_available > 0 and self.regular_hours_used >= self.regular_hours_available - 1e-6


@dataclass
class ScenarioResult:
    label: str
    status: SolveStatus
    message: str = ""
    stage1: SolveOutcome | None = None
    stage2: SolveOutcome | None = None
    releases: list[ReleaseLine] = field(default_factory=list)
    item_weeks: list[ItemWeek] = field(default_factory=list)
    resource_weeks: list[ResourceWeek] = field(default_factory=list)
    activated_lanes: list[str] = field(default_factory=list)
    financials: PlanFinancials | None = None
    validation_errors: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    model_size: dict[str, int] = field(default_factory=dict)
    build_seconds: float = 0.0

    # ---- KPIs (recomputed from integer quantities, never from solver objective) -------------
    @property
    def has_plan(self) -> bool:
        return self.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE_WITH_GAP)

    @property
    def unmet_units_at_end(self) -> int | None:
        if not self.has_plan:
            return None
        last = {}
        for iw in self.item_weeks:
            last[(iw.part_id, iw.plant_id)] = iw.backlog
        return sum(last.values())

    @property
    def late_unit_weeks(self) -> int | None:
        return sum(iw.backlog for iw in self.item_weeks) if self.has_plan else None

    @property
    def peak_backlog_units(self) -> int | None:
        if not self.has_plan:
            return None
        by_week: dict[str, int] = {}
        for iw in self.item_weeks:
            by_week[iw.week_start] = by_week.get(iw.week_start, 0) + iw.backlog
        return max(by_week.values(), default=0)

    def units_by(self, role: str | None = None, overtime: bool | None = None) -> int:
        total = 0
        for r in self.releases:
            if role and r.role != role:
                continue
            if overtime is True:
                total += r.overtime_units
            elif overtime is False:
                total += r.regular_units
            else:
                total += r.units
        return total

    @property
    def relative_gap(self) -> float | None:
        if self.stage2 and self.stage2.has_solution:
            return self.stage2.relative_gap
        if self.stage1 and self.stage1.has_solution:
            return self.stage1.relative_gap
        return None

    @property
    def solver_seconds(self) -> float:
        return sum(s.wall_seconds for s in (self.stage1, self.stage2) if s)

    @property
    def binding_constraints(self) -> list[str]:
        out = [f"resource {rw.resource_id} regular hours full in {rw.week_start}" for rw in self.resource_weeks if rw.binding]
        return out


# ------------------------------------------------------------------------------------------------
def _usable_lanes(inp: ScenarioInput) -> list[LaneInput]:
    return [ln for ln in inp.lanes if inp.lane_usable(ln)]


def build_model(inp: ScenarioInput) -> pyo.ConcreteModel:
    weeks = inp.weeks
    T = range(len(weeks))
    lanes = _usable_lanes(inp)
    items = {it.key: it for it in inp.items}
    lane_by_id = {ln.lane_id: ln for ln in lanes}
    lane_ids = [ln.lane_id for ln in lanes]
    item_keys = list(items)
    item_index = {k: n for n, k in enumerate(item_keys)}

    m = pyo.ConcreteModel(name=inp.scenario_label)
    m.T = pyo.Set(initialize=list(T), ordered=True)
    m.A = pyo.Set(initialize=lane_ids, ordered=True)
    m.I = pyo.Set(initialize=list(range(len(item_keys))), ordered=True)

    def reg_bounds(_, a, t):
        ln = lane_by_id[a]
        if t + ln.lead_weeks >= len(weeks):  # would arrive after the horizon: useless, fix to zero
            return (0, 0)
        cap = int(ln.committed_cap.get(weeks[t], 0))
        return (0, max(cap, 0))

    def ot_bounds(_, a, t):
        ln = lane_by_id[a]
        if not inp.allow_overtime or t + ln.lead_weeks >= len(weeks):
            return (0, 0)
        return (0, max(int(ln.flex_cap.get(weeks[t], 0)), 0))

    m.r = pyo.Var(m.A, m.T, domain=pyo.NonNegativeIntegers, bounds=reg_bounds)
    m.o = pyo.Var(m.A, m.T, domain=pyo.NonNegativeIntegers, bounds=ot_bounds)

    # Contractual weekly ceiling across regular + overtime.
    m.ceiling = pyo.ConstraintList()
    for a in lane_ids:
        ln = lane_by_id[a]
        for t in T:
            if weeks[t] in ln.max_total:
                m.ceiling.add(m.r[a, t] + m.o[a, t] <= int(ln.max_total[weeks[t]]))
            locked = ln.locked_releases.get(weeks[t])
            if locked is not None:
                m.ceiling.add(m.r[a, t] + m.o[a, t] == int(locked))

    # Lot multiples and minimum lots (binary only where actually needed).
    m.lots = pyo.ConstraintList()
    lot_lanes = [a for a in lane_ids if lane_by_id[a].lot_multiple > 1]
    m.k = pyo.Var(lot_lanes, m.T, domain=pyo.NonNegativeIntegers)
    for a in lot_lanes:
        for t in T:
            m.lots.add(m.r[a, t] + m.o[a, t] == lane_by_id[a].lot_multiple * m.k[a, t])
    zlanes = [a for a in lane_ids if lane_by_id[a].min_lot > 0 or _setup_hours(inp, a) > 0]
    m.z = pyo.Var(zlanes, m.T, domain=pyo.Binary)
    for a in zlanes:
        ln = lane_by_id[a]
        for t in T:
            big = max(ln.max_total.get(weeks[t], 0), ln.committed_cap.get(weeks[t], 0) + ln.flex_cap.get(weeks[t], 0))
            m.lots.add(m.r[a, t] + m.o[a, t] <= big * m.z[a, t])
            if ln.min_lot > 0:
                m.lots.add(m.r[a, t] + m.o[a, t] >= ln.min_lot * m.z[a, t])

    # Activation of optional lanes with a fixed fee.
    act_lanes = [a for a in lane_ids if lane_by_id[a].activation_cost > 0]
    m.y = pyo.Var(act_lanes, domain=pyo.Binary)
    m.activation = pyo.ConstraintList()
    for a in act_lanes:
        ln = lane_by_id[a]
        horizon_cap = sum(ln.committed_cap.get(w, 0) + ln.flex_cap.get(w, 0) for w in weeks)
        m.activation.add(sum(m.r[a, t] + m.o[a, t] for t in T) <= horizon_cap * m.y[a])

    # Shared resources: one budget for all lanes on the resource.
    req_by_res: dict[str, list] = {}
    for rq in inp.requirements:
        if rq.lane_id in lane_by_id:
            req_by_res.setdefault(rq.resource_id, []).append(rq)
    m.resource = pyo.ConstraintList()
    for res in inp.resources:
        reqs = req_by_res.get(res.resource_id, [])
        if not reqs:
            continue
        for t in T:
            w = weeks[t]
            reg_use = sum(rq.hours_per_unit * m.r[rq.lane_id, t] for rq in reqs)
            setup = sum(rq.setup_hours * m.z[rq.lane_id, t] for rq in reqs if rq.setup_hours > 0)
            m.resource.add(reg_use + setup <= float(res.regular_hours.get(w, 0.0)))
            ot_cap = float(res.overtime_hours.get(w, 0.0)) if inp.allow_overtime else 0.0
            m.resource.add(sum(rq.hours_per_unit * m.o[rq.lane_id, t] for rq in reqs) <= ot_cap)

    # Item balances.
    m.so = pyo.Var(m.I, m.T, domain=pyo.NonNegativeIntegers)
    m.sn = pyo.Var(m.I, m.T, domain=pyo.NonNegativeIntegers)
    m.B = pyo.Var(m.I, m.T, domain=pyo.NonNegativeIntegers)
    m.Io = pyo.Var(m.I, m.T, domain=pyo.NonNegativeReals)
    m.In = pyo.Var(m.I, m.T, domain=pyo.NonNegativeReals,
                   bounds=None if inp.allow_prebuild else (0, 0))
    lanes_into: dict[int, list[LaneInput]] = {n: [] for n in range(len(item_keys))}
    for ln in lanes:
        if ln.item_key in item_index:
            lanes_into[item_index[ln.item_key]].append(ln)
    m.balance = pyo.ConstraintList()
    for n, key in enumerate(item_keys):
        it = items[key]
        for t in T:
            w = weeks[t]
            arrivals = sum(m.r[ln.lane_id, t - ln.lead_weeks] + m.o[ln.lane_id, t - ln.lead_weeks]
                           for ln in lanes_into[n] if t - ln.lead_weeks >= 0)
            prev_io = it.opening_usable if t == 0 else m.Io[n, t - 1]
            prev_in = 0 if t == 0 else m.In[n, t - 1]
            prev_b = 0 if t == 0 else m.B[n, t - 1]
            m.balance.add(m.Io[n, t] == prev_io + int(it.receipts.get(w, 0)) - m.so[n, t])
            m.balance.add(m.In[n, t] == prev_in + arrivals - m.sn[n, t])
            m.balance.add(m.so[n, t] + m.sn[n, t] + m.B[n, t] == int(it.demand.get(w, 0)) + prev_b)
            if inp.require_zero_shortage:
                m.B[n, t].fix(0)

    # Expressions used by both stages.
    weight = {n: max(1, items[k].criticality_weight) for n, k in enumerate(item_keys)}
    m.shortage = pyo.Expression(expr=sum(weight[n] * m.B[n, t] for n in m.I for t in T))
    week_frac = 7.0 / 365.0
    hold = sum(float(items[k].valuation_unit_cost) * float(inp.holding_rate_annual) * week_frac * m.In[n, t]
               for n, k in enumerate(item_keys) for t in T)
    purchase = sum(float(lane_by_id[a].unit_price) * (m.r[a, t] + m.o[a, t])
                   + float(lane_by_id[a].flex_premium_per_unit) * m.o[a, t] for a in lane_ids for t in T)
    fees = sum(float(lane_by_id[a].activation_cost) * m.y[a] for a in act_lanes)
    m.spend = pyo.Expression(expr=purchase + hold + fees)
    # Incremental cost relative to the planned price for the same units (premiums + holding + fees).
    alt_delta = sum(max(0.0, float(lane_by_id[a].unit_price - items[lane_by_id[a].item_key].reference_unit_price))
                    * (m.r[a, t] + m.o[a, t])
                    for a in lane_ids if lane_by_id[a].role == "ALTERNATE" and lane_by_id[a].item_key in items for t in T)
    ot_prem = sum(float(lane_by_id[a].flex_premium_per_unit) * m.o[a, t] for a in lane_ids for t in T)
    m.incremental = pyo.Expression(expr=alt_delta + ot_prem + hold + fees)
    if inp.max_incremental_cost is not None:
        m.budget = pyo.Constraint(expr=m.incremental <= float(inp.max_incremental_cost))

    m._meta = {"weeks": weeks, "lanes": lane_by_id, "items": items, "item_keys": item_keys, "act_lanes": act_lanes,
               "req_by_res": req_by_res}
    return m


def _setup_hours(inp: ScenarioInput, lane_id: str) -> float:
    return sum(rq.setup_hours for rq in inp.requirements if rq.lane_id == lane_id)


def _count(m: pyo.ConcreteModel) -> dict[str, int]:
    nvars = sum(1 for v in m.component_data_objects(pyo.Var, active=True) if not v.fixed)
    nint = sum(1 for v in m.component_data_objects(pyo.Var, active=True) if not v.fixed and v.is_integer())
    ncons = sum(1 for _ in m.component_data_objects(pyo.Constraint, active=True))
    return {"variables": nvars, "integer_variables": nint, "constraints": ncons}


# ------------------------------------------------------------------------------------------------
def solve_scenario(inp: ScenarioInput, *, exposure_proxy_per_unit: Decimal = Decimal("0")) -> ScenarioResult:
    import time

    t0 = time.perf_counter()
    try:
        m = build_model(inp)
    except Exception as exc:
        return ScenarioResult(inp.scenario_label, SolveStatus.ERROR, f"model build failed: {exc}")
    build = time.perf_counter() - t0
    result = ScenarioResult(inp.scenario_label, SolveStatus.NOT_RUN, model_size=_count(m) | inp.size(), build_seconds=build)
    budget = inp.solver.time_limit_seconds
    gap = inp.solver.max_relative_gap

    # Stage 1: physical service.
    m.obj1 = pyo.Objective(expr=m.shortage, sense=pyo.minimize)
    s1 = solve_highs(m, time_limit=budget * 0.5, mip_gap=gap)
    result.stage1 = s1
    if s1.termination == "infeasible":
        result.status = SolveStatus.INFEASIBLE
        result.message = "No plan satisfies the hard constraints."
        result.diagnostics = diagnose_infeasibility(inp)
        return result
    if s1.termination == "error" or s1.termination == "unbounded":
        result.status = SolveStatus.ERROR
        result.message = f"solver error in stage 1: {s1.message}"
        return result
    if not s1.has_solution:
        result.status = SolveStatus.TIME_LIMIT
        result.message = "Time limit reached before any feasible plan was found; no solution is reported."
        return result
    stage1_value = float(s1.primal)
    stage1_proven = s1.termination == "optimal" and (s1.relative_gap or 0.0) <= 1e-9
    snapshot1 = _snapshot_values(m)

    # Stage 2: cost, holding stage-1 service fixed (within tolerance).
    m.obj1.deactivate()
    m.service_lock = pyo.Constraint(expr=m.shortage <= stage1_value + inp.solver.shortage_tolerance_units + EPS)
    m.obj2 = pyo.Objective(expr=m.spend, sense=pyo.minimize)
    remaining = max(budget - s1.wall_seconds, budget * 0.25)
    s2 = solve_highs(m, time_limit=remaining, mip_gap=gap)
    result.stage2 = s2
    if not s2.has_solution:
        # Stage-1 incumbent is still a valid physical plan; report it without cost optimality.
        _restore_values(m, snapshot1)
        result.warnings.append("Cost stage found no solution within the time limit; plan is cost-unoptimised.")
        status = SolveStatus.FEASIBLE_WITH_GAP
    else:
        s2_proven = s2.termination == "optimal" and (s2.relative_gap or 0.0) <= 1e-9
        status = SolveStatus.OPTIMAL if (stage1_proven and s2_proven) else SolveStatus.FEASIBLE_WITH_GAP
        if not stage1_proven:
            result.warnings.append("Shortage minimum not proven (stage-1 time limit or gap); later stages use the incumbent.")
    _extract(m, inp, result, exposure_proxy_per_unit)

    from .solution_validator import validate

    errors = validate(inp, result)
    if errors:
        result.validation_errors = errors
        result.status = SolveStatus.ERROR
        result.message = "Post-solve validation failed; plan suppressed from offers."
        return result
    result.status = status
    if status == SolveStatus.FEASIBLE_WITH_GAP and s1.termination == "time_limit":
        result.message = "Time limit reached; best feasible plan returned with its gap. Not proven optimal."
    return result


def _snapshot_values(m: pyo.ConcreteModel) -> dict:
    return {v.name: v.value for v in m.component_data_objects(pyo.Var) if not v.fixed}


def _restore_values(m: pyo.ConcreteModel, snap: dict) -> None:
    for v in m.component_data_objects(pyo.Var):
        if not v.fixed and v.name in snap:
            v.set_value(snap[v.name], skip_validation=True)


def _iv(x) -> int:
    val = pyo.value(x, exception=False)
    return int(round(val)) if val is not None else 0


def _extract(m: pyo.ConcreteModel, inp: ScenarioInput, result: ScenarioResult, exposure_proxy: Decimal) -> None:
    meta = m._meta
    weeks, lanes, items, item_keys = meta["weeks"], meta["lanes"], meta["items"], meta["item_keys"]
    releases: list[ReleaseLine] = []
    for a, ln in lanes.items():
        for t in range(len(weeks)):
            reg, ot = _iv(m.r[a, t]), _iv(m.o[a, t])
            if reg or ot:
                releases.append(ReleaseLine(a, ln.supplier_org_id, ln.part_id, ln.plant_id, ln.role, weeks[t],
                                            weeks[t + ln.lead_weeks], reg, ot))
    result.releases = releases
    arrivals: dict[tuple, int] = {}
    for rl in releases:
        key = (rl.part_id, rl.plant_id, rl.arrival_week)
        arrivals[key] = arrivals.get(key, 0) + rl.units
    item_weeks: list[ItemWeek] = []
    carried: list[CarriedInventory] = []
    for n, key in enumerate(item_keys):
        it = items[key]
        for t, w in enumerate(weeks):
            new_inv = _iv(m.In[n, t])
            item_weeks.append(ItemWeek(it.part_id, it.plant_id, w, int(it.demand.get(w, 0)), int(it.receipts.get(w, 0)),
                                       arrivals.get((it.part_id, it.plant_id, w), 0), _iv(m.so[n, t]), _iv(m.sn[n, t]),
                                       _iv(m.B[n, t]), _iv(m.Io[n, t]), new_inv))
            if new_inv:
                carried.append(CarriedInventory(w, it.part_id, it.plant_id, new_inv, it.valuation_unit_cost))
    result.item_weeks = item_weeks
    res_weeks: list[ResourceWeek] = []
    for res in inp.resources:
        reqs = meta["req_by_res"].get(res.resource_id, [])
        if not reqs:
            continue
        for t, w in enumerate(weeks):
            reg = sum(rq.hours_per_unit * _iv(m.r[rq.lane_id, t]) for rq in reqs)
            reg += sum(rq.setup_hours * _iv(m.z[rq.lane_id, t]) for rq in reqs if rq.setup_hours > 0)
            ot = sum(rq.hours_per_unit * _iv(m.o[rq.lane_id, t]) for rq in reqs)
            res_weeks.append(ResourceWeek(res.resource_id, w, round(reg, 6), float(res.regular_hours.get(w, 0.0)), round(ot, 6),
                                          float(res.overtime_hours.get(w, 0.0)) if inp.allow_overtime else 0.0))
    result.resource_weeks = res_weeks
    activated = [a for a in meta["act_lanes"] if _iv(m.y[a])]
    result.activated_lanes = activated
    lines: dict[str, CostLine] = {}
    for rl in releases:
        ln = lanes[rl.lane_id]
        ref = items[ln.item_key].reference_unit_price if ln.item_key in items else ln.unit_price
        cl = lines.setdefault(rl.lane_id, CostLine(rl.lane_id, ln.role, 0, 0, ln.unit_price, ln.flex_premium_per_unit, ref))
        cl.regular_units += rl.regular_units
        cl.overtime_units += rl.overtime_units
    fees = sum((lanes[a].activation_cost for a in activated), D(0))
    end_backlog = {}
    for iw in item_weeks:
        end_backlog[(iw.part_id, iw.plant_id)] = iw.backlog
    result.financials = plan_financials(list(lines.values()), carried, activation_fees=fees,
                                        holding_rate_annual=inp.holding_rate_annual,
                                        unmet_units_at_end=sum(end_backlog.values()),
                                        exposure_proxy_per_unit=exposure_proxy)


def diagnose_infeasibility(inp: ScenarioInput) -> list[str]:
    """Explain an infeasible run by relaxing the optional hard requirements one at a time."""
    from dataclasses import replace

    notes: list[str] = []
    if inp.require_zero_shortage or inp.max_incremental_cost is not None:
        relaxed = replace(inp, require_zero_shortage=False, max_incremental_cost=None,
                          solver=replace(inp.solver, time_limit_seconds=min(inp.solver.time_limit_seconds, 20.0)))
        m = build_model(relaxed)
        m.obj = pyo.Objective(expr=m.shortage, sense=pyo.minimize)
        out = solve_highs(m, time_limit=relaxed.solver.time_limit_seconds, mip_gap=0.0)
        if out.has_solution:
            if inp.require_zero_shortage and out.primal and out.primal > EPS:
                notes.append(f"Mandatory zero shortage is impossible: minimum achievable weighted late unit-weeks is {out.primal:.0f} "
                             "with the enabled mitigation modes.")
            if inp.max_incremental_cost is not None:
                inc = pyo.value(m.incremental)
                notes.append(f"Budget cap {inp.max_incremental_cost} EUR: the shortage-minimising plan needs about {inc:.2f} EUR incremental cost.")
        else:
            notes.append("The plan is infeasible even without the zero-shortage and budget requirements.")
    for ln in inp.lanes:
        for w, q in ln.locked_releases.items():
            cap = ln.max_total.get(w, ln.committed_cap.get(w, 0) + ln.flex_cap.get(w, 0))
            if q > cap:
                notes.append(f"Locked release {q} on {ln.lane_id} in {w} exceeds that lane's capacity {cap}.")
    lead_blocked = [ln.lane_id for ln in inp.lanes if inp.lane_usable(ln) and ln.lead_weeks >= len(inp.weeks)]
    if lead_blocked:
        notes.append(f"Lead time prevents any arrival inside the horizon for: {', '.join(lead_blocked)}.")
    unq = [ln.lane_id for ln in inp.lanes if not ln.qualified]
    if unq:
        notes.append(f"Excluded unqualified lanes: {', '.join(unq)}.")
    return notes or ["Solver reported infeasibility; no single relaxed requirement explains it."]
