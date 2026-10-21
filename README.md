# Nodal Accord — collaborative supply resolution engine (prototype)

A working, API-first prototype of the blueprint in `../Nodal_Accord_Engineering_Blueprint.md`: detect a supply
exception, compare constrained mitigation plans (Pyomo + HiGHS MILP), turn a validated plan into a structured offer, let
the supplier accept or counteroffer, re-simulate, route human approvals, and export an immutable agreement record.

**Synthetic data only.** Independent concept; no affiliation with SupplyOn or any ERP vendor; no real integration,
credentials or ERP write-back. Not production-ready.

## What runs

| Piece | Where | Notes |
|---|---|---|
| Domain, ledger, MILP, finance, connectors | `packages/*/src` | pure Python, no web/cloud dependency |
| API (FastAPI, `/api/v1`, OpenAPI in `contracts/openapi/nodal-accord-v1.json`) | `apps/api` | demo identities, policy, cases, scenarios (202 + poll), offers, approvals, audit, imports |
| Optimization worker | `apps/worker` | separate process; atomic job claiming; several can run |
| Resolution Workbench (React + TS + Vite) | `apps/web` | queue · Investigate / Simulate / Resolve · supplier portal · agreements · audit · imports |
| Data | `../Nodal_Accord_5000_Supplier_Data/data/synthetic/generated/<tiny\|medium_500\|enterprise_5000>` | produced by the companion generator; read-only here |

## Run it

From this folder (`nodal-accord/`):

```powershell
.\scripts\bootstrap.ps1        # once: venv + pip install -e ".[dev]" + npm install   (sh scripts/bootstrap.sh on macOS/Linux)
npm run dev                    # frees :8000/:5173, starts API, worker and web
```

Open http://localhost:5173. Pick a demo identity in the top bar (the server resolves its role and tenant):
`demo.buyer001.planner` → run scenarios and draft offers; `demo.buyer001.procurement` → send offers and approve;
`demo.buyer001.finance` → required above the approval threshold or when payment days change; `demo.supplierNNNN.planner`
→ supplier portal (accept / counteroffer / reject); `demo.platform.ops` → metadata only.

Dataset: `tiny` by default. Switch with `NODAL_DATA_ROOT` (e.g. `...\generated\enterprise_5000`) before `npm run dev`.
Workflow state lives in `var/nodal_<dataset>.db` (SQLite); delete it to reset the demo.

Demo script (CASE-000004, shared machine): Simulate → Run comparison (baseline leaves 200 units short because one
80 h machine serves both parts; alternate and hybrid recover them) → Draft offer → switch to procurement → Send →
switch to `demo.supplier0013.planner` → Accept → back to procurement → Approve → Show export preview.
Counteroffer path: CASE-000011 (tenant 2) — supplier moves the delivery week → inputs v2, earlier runs stale → re-run →
the alternate no longer arrives in time (200 units unmet, matching the generator's oracle) → no offer can be drafted.

## Tests

```powershell
npm test                                            # or: .\.venv\Scripts\python -m pytest
```

43 tests: ledger properties (Hypothesis), finance goldens (payment terms EUR 394.52, consolidated 0.00), golden solver
fixtures (hand optimum, lead time, shared machine, unqualified lane, locked release, infeasible zero-shortage, prebuild,
overtime, time limit never labelled optimal), **oracle cross-check: all 36 curated cases × 5 modes agree with the
generator's independent solver on unmet units (180/180 on tiny, medium_500 and enterprise_5000)**, 12-week scope tests,
the full buyer→supplier→approval→export workflow, counteroffer re-simulation, stale-approval block, cross-tenant
concealment, field-leak scans, multi-buyer isolation, platform-operator limits, import validation/idempotency.
Run the cross-check on a bigger dataset with `NODAL_DATA_ROOT=<dir> pytest tests/unit/test_oracle_crosscheck.py`.

## Measured performance

Measured on one developer laptop (Windows 11, 12 logical CPUs, Python 3.13, HiGHS via Pyomo), dev servers stopped.
Raw per-run data: `docs/evaluation/*.json`. Reproduce with `tests/benchmark/solve_network.py` and `load_api.py`.
These are measurements of this synthetic workload, not a production SLA.

**Scenario solves** — 10 sampled disruptions × {baseline, hybrid} per dataset, 12-week `SNAPSHOT_HORIZON` scope
(≤ 60 items per scope), 30 s time limit per mode, 1 % MIP gap target:

| Dataset | Suppliers / lanes | Status (20 solves) | Solver p50 / p95 / max | Hit time limit | Stage-1 gap > 50 % | Validation failures | Load + index | Peak RSS |
|---|---|---|---|---|---|---|---|---|
| tiny | 20 / 37 | 6 OPTIMAL, 14 FEASIBLE_WITH_GAP | 0.24 / 4.2 / 5.2 s | 0 | 0 | 0 | 0.05 + 0.02 s | 150 MB |
| medium_500 | 500 / 3,000 | 2 OPTIMAL, 18 FEASIBLE_WITH_GAP | 16.5 / 30.7 / 31.2 s | 6 | 6 | 0 | 0.07 + 0.38 s | 391 MB |
| enterprise_5000 | 5,000 / 30,000 | 5 OPTIMAL, 15 FEASIBLE_WITH_GAP | 16.3 / 30.5 / 30.5 s | 3 | 8 | 0 | 0.26 + 3.9 s | 1,210 MB |

How to read this honestly:
- Every solve returned a validated plan, but most large scopes (≈ 6,000–8,600 integer variables) are **not proven
  optimal**: on 8 of 20 enterprise solves the shortage stage stopped with a bound gap above 50 %, so those numbers are
  incumbents, not optima. Small scopes and the curated case fixtures solve to optimality in well under a second.
- Mode results are warm-started (baseline from the no-release plan, others from baseline), so mitigation never reports
  worse service than baseline; one run per large dataset did not improve on its seed and is flagged as such.
- A solve covers one disruption's scoped component, not the whole network. Decomposition / rolling horizon for larger
  connected scopes is not implemented.

**API latency** — 5,000-supplier dataset, in-process client, 20 sequential requests (`api-latency-enterprise_5000.json`):

| Endpoint | Cold (first request) | Warm p50 / p95 | Blueprint target |
|---|---|---|---|
| `GET /cases` | 0.04 s | 4 / 5 ms | p95 < 2 s |
| `GET /cases/{id}` | 1.43 s (lazy index build) | 4 / 5 ms | p95 < 3 s |
| `GET /network/impact` | 0.19 s | 7 / 8 ms | — |

The case index holds the 36 curated cases (33 visible to buyer 1), not one case per supplier, so it is not evidence of
filtering thousands of cases.

## Getting the data
The synthetic dataset is produced by the companion generator (`Nodal_Accord_5000_Supplier_Data/`, not part of this
repository) and expected next to this folder. Point `NODAL_DATA_ROOT` at any generated dataset directory that contains
`tables/`, `scenarios/`, `golden/`, `access-tests/` and `external/`. Tests that need it are skipped when it is missing.

## Design, decisions, deviations

- `docs/optimization/formulation.md` — the MILP as implemented, status labels, HYBRID definition.
- `docs/architecture/decisions.md` — ADRs and **every deviation from the blueprint** (SQLite instead of PostgreSQL, no
  RLS, no Docker/Azure, no AI agent, demo identities instead of OIDC, Mode A economics only).

## License
Apache License 2.0 — see `LICENSE`. Third-party dependencies keep their own licenses (MIT, BSD or Apache-2.0).

## What is not claimed
Not integrated with SupplyOn or any ERP; no vendor schema is used; not production-ready; time-limited runs are labelled
`FEASIBLE_WITH_GAP`, never optimal; benchmark numbers are from one laptop and one synthetic workload; shortage exposure is
a scenario proxy, not a loss forecast; synthetic results are not customer savings.
