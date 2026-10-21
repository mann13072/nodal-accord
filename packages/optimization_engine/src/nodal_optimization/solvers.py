"""Solver adapter. HiGHS via Pyomo's APPSI interface is the only required solver."""
from __future__ import annotations

import time
from dataclasses import dataclass

import pyomo.environ as pyo
from pyomo.contrib.appsi.base import TerminationCondition as TC
from pyomo.contrib.appsi.solvers import Highs


@dataclass
class SolveOutcome:
    termination: str  # optimal | infeasible | time_limit | error | unbounded
    has_solution: bool
    primal: float | None
    bound: float | None
    wall_seconds: float
    message: str = ""

    @property
    def relative_gap(self) -> float | None:
        if self.primal is None or self.bound is None:
            return None
        return abs(self.primal - self.bound) / max(abs(self.primal), 1e-9)


def solve_highs(model: pyo.ConcreteModel, *, time_limit: float, mip_gap: float, warmstart: bool = False) -> SolveOutcome:
    """warmstart=True passes the variables' current values to HiGHS as a starting MIP solution."""
    opt = Highs()
    if not opt.available():
        return SolveOutcome("error", False, None, None, 0.0, "HiGHS solver is not available in this environment")
    opt.config.time_limit = max(float(time_limit), 0.0)
    opt.config.mip_gap = float(mip_gap)
    opt.config.warmstart = warmstart
    opt.config.load_solution = False
    opt.config.stream_solver = False
    started = time.perf_counter()
    try:
        res = opt.solve(model)
    except Exception as exc:  # solver crash must not masquerade as a result
        return SolveOutcome("error", False, None, None, time.perf_counter() - started, f"{type(exc).__name__}: {exc}")
    wall = time.perf_counter() - started
    tc = res.termination_condition
    primal = res.best_feasible_objective
    bound = res.best_objective_bound
    has_solution = primal is not None
    if has_solution:
        try:
            res.solution_loader.load_vars()
        except Exception as exc:
            return SolveOutcome("error", False, None, None, wall, f"could not load solution: {exc}")
    if tc == TC.optimal:
        term = "optimal"
    elif tc in (TC.infeasible, TC.infeasibleOrUnbounded):
        term = "infeasible"
    elif tc in (TC.maxTimeLimit, TC.maxIterations, TC.interrupted, TC.objectiveLimit):
        term = "time_limit"
    elif tc == TC.unbounded:
        term = "unbounded"
    else:
        term = "error"
    return SolveOutcome(term, has_solution, primal, bound, wall, str(tc))
