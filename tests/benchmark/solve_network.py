"""Reproducible solve benchmark over a generated dataset (blueprint §12, §20.1).

Measures, separately: table load, scope/model build, solver wall time, and validation, for a deterministic
sample of disruption events solved over the 12-week SNAPSHOT_HORIZON scope. Reports what was measured;
it does not extrapolate to other sizes or hardware.

    python tests/benchmark/solve_network.py --data-root <dataset dir> --events 10 --modes baseline hybrid
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for sub in ("packages/domain/src", "packages/planning_engine/src", "packages/optimization_engine/src", "packages/finance_engine/src",
            "packages/integrations/src"):
    sys.path.insert(0, str(REPO / sub))

from nodal_integrations.snapshot import SnapshotStore  # noqa: E402
from nodal_optimization.case_inputs import snapshot_scenario  # noqa: E402
from nodal_optimization.milp_model import solve_scenario  # noqa: E402
from nodal_optimization.model_inputs import SolverOptions  # noqa: E402

TABLES = ["organizations", "sourcing_lanes", "resource_lane_requirements", "capacity_calendar", "lane_capacity", "demand_forecast",
          "inventory_positions", "scheduled_receipts", "buyer_commercial_terms", "parts", "disruption_events"]


def peak_rss_mb() -> float | None:
    try:
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        if os.name == "nt":
            pmc = PMC()
            pmc.cb = ctypes.sizeof(PMC)
            k32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
            k32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
            if not psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
                return None
            return round(pmc.PeakWorkingSetSize / 2**20, 1)
        import resource
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--events", type=int, default=10)
    ap.add_argument("--modes", nargs="+", default=["baseline", "hybrid"])
    ap.add_argument("--time-limit", type=float, default=60.0)
    ap.add_argument("--gap", type=float, default=0.01)
    ap.add_argument("--max-items", type=int, default=60)
    ap.add_argument("--out", default=str(REPO / "docs" / "evaluation"))
    args = ap.parse_args()

    store = SnapshotStore(args.data_root)
    t0 = time.perf_counter()
    rows = {}
    for t in TABLES:
        s = time.perf_counter()
        rows[t] = len(store.table(t))
        rows[t + "_load_s"] = round(time.perf_counter() - s, 3)
    s = time.perf_counter()
    store.lanes_by_id, store.lanes_by_resource, store.lanes_by_part_plant, store.private_economics_by_lane  # noqa: B018 (build indexes)
    store.demand_for("x", "x", "x"); store.lane_capacity_for("x"); store.capacity_calendar_for("x"); store.receipts_for("x", "x", "x")
    index_s = time.perf_counter() - s
    load_s = time.perf_counter() - t0

    orgs = store.table("organizations")
    suppliers = int((orgs["org_type"] == "SUPPLIER").sum())
    events = sorted(store.disruptions)
    step = max(1, len(events) // args.events)
    sample = events[::step][: args.events]
    runs = []
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    name = f"benchmark-{Path(args.data_root).name}"

    def write_report(complete: bool) -> dict:
        solver_times = sorted(r["solver_s"] for r in runs)
        p95 = solver_times[min(len(solver_times) - 1, int(round(0.95 * (len(solver_times) - 1))))] if solver_times else None
        report = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "complete": complete,
            "dataset": {"root": str(Path(args.data_root).name), "suppliers": suppliers,
                        "table_rows": {k: v for k, v in rows.items() if not k.endswith("_s")},
                        "generator_seed": store.manifest.get("seed"), "generator_version": store.manifest.get("generator_version")},
            "host": {"platform": platform.platform(), "python": platform.python_version(), "processor": platform.processor(),
                     "cpu_count": os.cpu_count(), "note": "Developer laptop; dev servers stopped during the run."},
            "solver": {"name": "HiGHS via Pyomo APPSI", "time_limit_s": args.time_limit, "mip_rel_gap": args.gap},
            "workload": {"scope": "SNAPSHOT_HORIZON", "events_sampled": len(sample), "modes": args.modes,
                         "max_items_per_scope": args.max_items, "sampling": f"every {step}th disruption_id in sorted order"},
            "timings": {"table_load_s": round(load_s - index_s, 3), "index_build_s": round(index_s, 3),
                        "table_load_breakdown_s": {k[:-7]: v for k, v in rows.items() if k.endswith("_load_s")},
                        "solver_s_p50": statistics.median(solver_times) if solver_times else None, "solver_s_p95": p95,
                        "solver_s_max": max(solver_times) if solver_times else None,
                        "runs_at_time_limit": sum(1 for t in solver_times if t >= args.time_limit * 0.98)},
            "status_counts": {s: sum(1 for r in runs if r["status"] == s) for s in sorted({r["status"] for r in runs})},
            "validation_failures": sum(r["validation_errors"] for r in runs),
            "peak_rss_mb": peak_rss_mb(),
            "runs": runs,
            "interpretation": "Measured on this host only. Not a production SLA. Each solve covers one disruption's scoped "
                              "component (12 weeks, <= max_items items), not the whole network at once.",
        }
        (out / f"{name}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        return report

    for ev in sample:
        for mode in args.modes:
            b = time.perf_counter()
            inp, econ, scope = snapshot_scenario(store, ev, mode, max_items=args.max_items,
                                                 solver=SolverOptions(time_limit_seconds=args.time_limit, max_relative_gap=args.gap))
            scope_s = time.perf_counter() - b
            res = solve_scenario(inp, exposure_proxy_per_unit=econ.exposure_proxy_per_unit)
            runs.append({"disruption_id": ev, "mode": mode, "status": res.status.value, "items": scope["items"], "lanes": scope["lanes"],
                         "resources": scope["resources"], "truncated": scope["truncated"], "weeks": len(inp.weeks),
                         "out_of_scope_reserved_hours": scope.get("out_of_scope_reserved_hours"),
                         "variables": res.model_size.get("variables"), "integer_variables": res.model_size.get("integer_variables"),
                         "constraints": res.model_size.get("constraints"), "scope_build_s": round(scope_s, 4),
                         "model_build_s": round(res.build_seconds, 4), "solver_s": round(res.solver_seconds, 4),
                         "relative_gap": res.relative_gap, "unmet_units_at_end": res.unmet_units_at_end,
                         "late_unit_weeks": res.late_unit_weeks, "validation_errors": len(res.validation_errors)})
            print(json.dumps(runs[-1]), flush=True)
            write_report(complete=False)

    report = write_report(complete=True)
    print(json.dumps({k: report[k] for k in ("dataset", "timings", "status_counts", "validation_failures", "peak_rss_mb")}, indent=2))


if __name__ == "__main__":
    main()
