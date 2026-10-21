# Mitigation MILP — formulation as implemented

Source: `packages/optimization_engine/src/nodal_optimization/milp_model.py` (model), `solution_validator.py`
(independent check), `case_inputs.py` (input builders).

## Sets and data
- Weeks `t ∈ T` (Monday buckets); items `i = (part, plant)`; lanes `a` (supplier → part → plant); resources `r`.
- `d[i,t]` demand, `s0[i]` opening usable stock, `rec[i,t]` CONFIRMED receipts counted once
  (fixture scope: none; horizon scope: only receipts released before the horizon, i.e. in transit).
- Lane `a`: `committed[a,t]`, disclosed `flex[a,t]`, contractual ceiling `max[a,t]`, lead weeks `L[a]`,
  lot multiple, unit landed price `p[a]`, disclosed overtime premium `π[a]`, role PRIMARY/ALTERNATE, qualified flag.
- Resource `r`: regular hours `H[r,t]`, overtime hours `OT[r,t]`; requirement `h[a,r]` hours/unit, setup hours.

## Variables (integer EA)
`reg[a,t]`, `ot[a,t]` releases; `so[i,t]`, `sn[i,t]` demand served from old/new stock; `B[i,t]` backlog;
`Io[i,t]`, `In[i,t]` old/new inventory pools; optional `k` (lot multiples), `z` (min lot / setup), `y` (activation).

## Constraints
1. `reg[a,t] ≤ committed[a,t]`, `ot[a,t] ≤ flex[a,t]` (0 unless OVERTIME/HYBRID), `reg+ot ≤ max[a,t]`.
2. A release whose arrival `t+L[a]` falls outside the horizon is fixed to 0 (lead time is never ignored).
3. Unqualified lanes are excluded; ALTERNATE lanes only with ALTERNATE_SOURCE/HYBRID.
4. **Shared resources:** `Σ_a h[a,r]·reg[a,t] + setup ≤ H[r,t]` and `Σ_a h[a,r]·ot[a,t] ≤ OT[r,t]` — one budget per
   resource per week across every lane that uses it (golden case A: 80 h cannot serve 600 + 400 units at 0.1 h/unit).
5. Balances: `Io[t] = Io[t-1] + rec[t] − so[t]`; `In[t] = In[t-1] + Σ_a (reg+ot)[a, t−L[a]] − sn[t]`;
   `so + sn + B[t] = d[t] + B[t-1]`.
6. **Prebuild is explicit:** `In[i,t] = 0` unless PREBUILD is enabled, so new production cannot silently be carried.
7. Locked releases (frozen/approved) are equalities; optional `B = 0` (mandatory zero shortage) and a budget on
   incremental buyer cost.

## Objective (lexicographic)
1. Minimise `Σ w_i · B[i,t]` (criticality-weighted late unit-weeks; HIGH=3, MEDIUM=2, LOW=1).
2. Holding stage-1 value (≤ optimum + tolerance), minimise purchase spend + holding cost + activation fees.

Mode A economics: only buyer prices and supplier-*disclosed* premiums enter the model. Supplier private cost is
never an input, so it cannot leak into buyer results.

## Status labels
- `OPTIMAL` only when both stages terminate optimal with zero gap.
- `FEASIBLE_WITH_GAP` when any stage stops at a time limit or a non-zero gap with an incumbent (gap reported).
- `TIME_LIMIT` when no feasible plan was found in time — no plan is returned.
- `INFEASIBLE` with diagnostics from relaxing zero-shortage/budget, locked releases and lead times.
- `ERROR` when the independent validator finds any violation; the plan cannot become an offer.

## HYBRID definition
HYBRID = overtime + alternate source (blueprint case category 8; matches the generator's oracle). Prebuild is a
separate option. An earlier version folded prebuild into HYBRID; the oracle cross-check caught it (3/180 mismatches).

## Validation against the generator
`tests/unit/test_oracle_crosscheck.py` solves all 36 curated cases × 5 modes and requires identical unmet units to the
generator's independent scipy/HiGHS oracle (180/180 on `tiny`, `medium_500` and `enterprise_5000`), plus the golden
shared-bottleneck, zero-shortage-infeasible and counteroffer-recompute fixtures.
