# Architecture decisions and deviations from the blueprint

Each entry: decision, why, and what it means for claims. Deviations are listed explicitly rather than papered over.

## ADR-1 Modular monolith + separate optimization worker (as blueprint §4)
FastAPI app (`apps/api`) owns policy, cases, offers, approvals, imports and audit. `apps/worker` claims QUEUED runs with
an atomic conditional `UPDATE` and solves them; several workers can run. The API never blocks on a solve: scenario
submission returns `202` with a status URL. `NODAL_INLINE_WORKER=true` runs the same executor in a thread (tests).

## ADR-2 Pyomo + HiGHS, lexicographic objective (as blueprint §5, §11)
Pyomo APPSI interface to HiGHS; no commercial solver. See `docs/optimization/formulation.md`.
OR-Tools min-cost-flow screening was **not** built: the curated and scoped problems solve directly, and shared
resources/lots make pure network flow inapplicable anyway. Add it only if benchmarks show a need.

## ADR-3 Tenant isolation (blueprint §15) — application enforcement, tested
Principal → tenant/org scope is resolved server-side from the seeded principal table; client-sent tenant IDs are never
trusted. Object-level checks on every route; unauthorized and nonexistent IDs return identical `404`s. Projections strip
supplier-private fields from buyer views and buyer-confidential fields from supplier views; multi-buyer cases show each
buyer only its own lines and recompute financials per tenant. Negative tests: `tests/e2e/test_security.py`.
**Deviation:** PostgreSQL RLS (defense in depth) is not implemented — no PostgreSQL is available in this environment.
Do not claim RLS.

## ADR-4 Commercial data policy — Mode A only
Only buyer prices and supplier-*disclosed* premiums feed the optimizer. Where no disclosure exists, the buyer's approved
premium ceiling is used and labelled `ASSUMED` in lane provenance. Supplier private economics are used only in the
supplier's own view (its private evaluation of an offer). Mode B (consented joint optimization) is not built.

## ADR-5 Storage
**Deviation:** workflow state uses SQLite (WAL) via SQLAlchemy instead of PostgreSQL; the canonical planning snapshot is
the data generator's immutable Parquet output read through `SnapshotStore` (never written). Imports validate external
feeds, quarantine bad rows with reason codes, and reconcile against the snapshot; they do not overwrite it.
Alembic migrations, `rls_policies.sql` and Docker Compose are not provided (no Docker/PostgreSQL here).

## ADR-6 Two scenario scopes
- `CASE_FIXTURE` — the generator's isolated case override (disrupted week + prior week for prebuild); cross-checked
  against the generator oracle.
- `SNAPSHOT_HORIZON` — 12-week canonical scope around a disruption, expanded over lanes that share a resource, capped at
  60 items (truncation is reported). Every lane with committed capacity is a *current* source (the data is multi-sourced);
  only lanes without committed capacity are alternates. An earlier single-primary assumption overstated baseline
  shortages (4,368 vs 17 units on DISR-000001, tiny); found by diagnosis, fixed, and covered by a regression test.

## ADR-7 Workflow integrity
Offer revisions are immutable and digested (`sha256` of canonical public terms). Accept/reject/approve must quote the
exact version and digest. A counteroffer that changes quantity or date becomes a supplier limit on the case inputs and
bumps `input_version`, making every earlier run and offer stale (`409 STALE_SCENARIO/STALE_OFFER/STALE_APPROVAL`).
Finance approval is required above the tenant's approval threshold or when payment days change. No ERP write-back;
`/agreements/{id}/export` is a preview. Acceptance is workflow acceptance, not a legal signature.

## Not built (blueprint items deliberately left out)
Optional AI agent and tool gateway (Phase G), Azure/Bicep, Docker images, OIDC provider (demo identities only, fail-closed
otherwise), SSE progress (polling only), EDI parser, outbound webhooks (outbox records events with delivery disabled),
generated TypeScript client (hand-written typed client against the committed OpenAPI file), Playwright tests.
