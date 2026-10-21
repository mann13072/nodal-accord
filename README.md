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

42 tests: ledger properties (Hypothesis), finance goldens (payment terms EUR 394.52, consolidated 0.00), golden solver
fixtures (hand optimum, lead time, shared machine, unqualified lane, locked release, infeasible zero-shortage, prebuild,
overtime, time limit never labelled optimal), **oracle cross-check: all 36 curated cases × 5 modes agree with the
generator's independent solver on unmet units (180/180 on tiny, medium_500 and enterprise_5000)**, 12-week scope tests,
the full buyer→supplier→approval→export workflow, counteroffer re-simulation, stale-approval block, cross-tenant
concealment, field-leak scans, multi-buyer isolation, platform-operator limits, import validation/idempotency.
Run the cross-check on a bigger dataset with `NODAL_DATA_ROOT=<dir> pytest tests/unit/test_oracle_crosscheck.py`.

## Measured performance

See `docs/evaluation/` (JSON written by `tests/benchmark/solve_network.py` and `tests/benchmark/load_api.py`).
Benchmark runs for the 500- and 5,000-supplier datasets are in progress; results will be committed here when measured.
No performance figure is claimed until then.

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
