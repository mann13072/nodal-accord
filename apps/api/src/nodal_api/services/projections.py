"""Role projections of scenario results. Applied on every read; stored results are never sent raw."""
from __future__ import annotations

from typing import Any

from nodal_domain.permissions import Principal


def buyer_run_view(run_results: dict[str, Any], tenant_id: str) -> dict[str, Any]:
    out = {}
    for mode, r in (run_results or {}).items():
        releases = [x for x in r["releases"] if x.get("tenant_id") in (tenant_id, None)]
        hidden_releases = len(r["releases"]) - len(releases)
        out[mode] = {
            "status": r["status"], "message": r["message"], "offer_eligible": r["offer_eligible"],
            "kpis": _tenant_kpis(r, tenant_id), "financials": (r.get("financials_by_tenant") or {}).get(tenant_id),
            "solver": r["solver"],
            "releases": releases,
            "item_weeks": [x for x in r["item_weeks"] if x.get("tenant_id") in (tenant_id, None)],
            # Supplier machine hours are private: buyers only learn *that* a resource was binding.
            "resource_weeks": [{"resource_id": x["resource_id"], "week_start": x["week_start"], "binding": x["binding"]}
                               for x in r["resource_weeks"]],
            "binding_constraints": r["binding_constraints"], "diagnostics": r["diagnostics"], "warnings": r["warnings"],
            "validation_errors": r["validation_errors"], "assumptions": r["assumptions"],
            "lane_provenance": {k: v for k, v in r["lane_provenance"].items() if v.get("tenant_id") in (tenant_id, None)},
            "hidden_other_relationship_lines": hidden_releases, "input_hash": r["input_hash"], "scope": r.get("scope"),
        }
    return out


def _tenant_kpis(r: dict[str, Any], tenant_id: str) -> dict[str, Any]:
    k = dict(r["kpis"])
    rows = [x for x in r["item_weeks"] if x.get("tenant_id") == tenant_id]
    if r["status"] in ("OPTIMAL", "FEASIBLE_WITH_GAP") and rows and len(rows) != len(r["item_weeks"]):
        rels = [x for x in r["releases"] if x.get("tenant_id") == tenant_id]
        last: dict[tuple, int] = {}
        by_week: dict[str, int] = {}
        for x in rows:
            last[(x["part_id"], x["plant_id"])] = x["backlog"]
            by_week[x["week_start"]] = by_week.get(x["week_start"], 0) + x["backlog"]
        mitig = [x["arrival_week"] for x in rels if x["role"] == "ALTERNATE" or x["overtime_units"]]
        k.update({
            "unmet_units_at_end": sum(last.values()), "late_unit_weeks": sum(x["backlog"] for x in rows),
            "peak_backlog_units": max(by_week.values(), default=0),
            "primary_units": sum(x["regular_units"] + x["overtime_units"] for x in rels if x["role"] == "PRIMARY"),
            "alternate_units": sum(x["regular_units"] + x["overtime_units"] for x in rels if x["role"] == "ALTERNATE"),
            "overtime_units": sum(x["overtime_units"] for x in rels),
            "prebuild_peak_units": max((x["new_inventory"] for x in rows), default=0),
            "earliest_relief_week": min(mitig) if mitig else None,
            "note": "KPIs restricted to this tenant's items; other relationships on the shared resource are hidden.",
        })
    return k


def run_envelope(run, principal: Principal, *, include_results: bool) -> dict[str, Any]:
    env = {"run_id": run.run_id, "case_id": run.case_id, "state": run.state, "status": run.overall_status,
           "model_version": run.model_version, "input_version": run.input_version, "input_snapshot_hash": run.input_hash,
           "requested_by": run.requested_by, "request": run.request, "created_at": run.created_at.isoformat(),
           "started_at": run.started_at.isoformat() if run.started_at else None,
           "finished_at": run.finished_at.isoformat() if run.finished_at else None, "wall_seconds": run.wall_seconds,
           "error": run.error.splitlines()[0] if run.error else None, "status_url": f"/api/v1/scenario-runs/{run.run_id}"}
    if include_results and run.results:
        env["results"] = buyer_run_view(run.results, run.tenant_id)
    return env
