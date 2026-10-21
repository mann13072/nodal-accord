"""Build ScenarioInputs from the canonical snapshot.

Two scopes are supported and always labelled in results:

CASE_FIXTURE      The curated case's isolated override (generator semantics: "replace only listed
                  part/week demand, usable stock, lane ceilings and resource hours; other baseline
                  production/receipts excluded"). Two buckets: the prior week (prebuild only) and the
                  disrupted week. This is what the generator's oracle solved, so results are cross-checkable.

SNAPSHOT_HORIZON  The full 12-week canonical snapshot around the disruption: real demand, usable stock,
                  in-transit receipts, lane capacities, lead times, lot multiples and the shared resources
                  of the affected supplier, expanded across lanes that share a resource.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Protocol

from nodal_domain.money import D
from nodal_domain.weeks import add_weeks, lead_weeks, monday_of

from .model_inputs import MODE_SETS, ItemInput, LaneInput, Requirement, ResourceInput, ScenarioInput, SolverOptions

CRITICALITY_WEIGHT = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}


class StoreLike(Protocol):
    lanes_by_id: dict
    week_starts: list[str]


@dataclass
class EconomicsContext:
    holding_rate_annual: Decimal
    exposure_proxy_per_unit: Decimal
    max_case_incremental_spend: Decimal | None
    assumptions: list[str] = field(default_factory=list)


def _economics(store, tenant_id: str) -> EconomicsContext:
    prof = store.financial_profiles.get(tenant_id, {})
    return EconomicsContext(D(prof.get("inventory_holding_rate_annual", "0.18")),
                            D(prof.get("stockout_exposure_proxy_eur_per_unit", "0")),
                            D(prof["max_case_incremental_spend_eur"]) if prof.get("max_case_incremental_spend_eur") is not None else None)


def lane_price(store, lane: dict[str, Any]) -> tuple[Decimal, str]:
    terms = store.buyer_terms.get((lane["relationship_id"], lane["part_id"]))
    if terms is not None:
        return D(terms["unit_price_eur"]) + D(terms.get("base_transport_cost_eur_per_unit") or 0), "buyer_commercial_terms (price + transport)"
    return D(lane["standard_landed_unit_price_eur"]), "sourcing_lanes.standard_landed_unit_price_eur"


def disclosed_premium(store, lane: dict[str, Any], unit_price: Decimal) -> tuple[Decimal, str]:
    """Mode A: overtime premium must be supplier-disclosed. Without a disclosure, fall back to the buyer's
    approved premium ceiling and say so (never to the supplier's private overtime cost)."""
    offers = store.shareable_offers_by_lane.get(lane["lane_id"], [])
    if offers:
        return D(offers[0]["premium_price_eur_per_unit"]), f"supplier_shareable_offers {offers[0]['offer_id']}"
    terms = store.buyer_terms.get((lane["relationship_id"], lane["part_id"]))
    pct = D(terms["max_approved_premium_pct"]) if terms is not None else D("0.15")
    return (unit_price * pct).quantize(D("0.01")), "ASSUMED: buyer max approved premium (no supplier disclosure)"


def _valuation(store, tenant_id: str, part_id: str) -> Decimal:
    part = store.parts.get((tenant_id, part_id))
    return D(part["average_unit_value_eur"]) if part else D(0)


def _criticality(store, tenant_id: str, part_id: str) -> int:
    part = store.parts.get((tenant_id, part_id))
    return CRITICALITY_WEIGHT.get(str(part.get("criticality")) if part else "", 1)


# ------------------------------------------------------------------------------------------------
def fixture_scenario(store, fixture: dict[str, Any], mode: str, *, solver: SolverOptions | None = None,
                     require_zero_shortage: bool = False, overrides: dict[str, Any] | None = None) -> tuple[ScenarioInput, EconomicsContext]:
    f = dict(fixture)
    if overrides:
        f.update(overrides)
    target = f["week_start"]
    prior = f.get("prebuild_prior_week")
    weeks = [prior, target] if prior and prior < target else [target]
    owner_tenant = f["tenant_ids"][0]
    econ = _economics(store, owner_tenant)
    econ.assumptions += [
        "Scope CASE_FIXTURE: isolated case override from the generator; other baseline production and receipts excluded.",
        "Lead time inside the isolated week is treated as already satisfied for lanes marked as arriving in time.",
    ]
    hours_per_unit = float(f.get("hours_per_unit", "0.1"))
    items: list[ItemInput] = []
    lanes: list[LaneInput] = []
    requirements: list[Requirement] = []
    for i, lane_id in enumerate(f["lane_ids"]):
        lane = store.lanes_by_id[lane_id]
        tenant = f["tenant_ids"][i]
        price, price_src = lane_price(store, lane)
        prem, prem_src = disclosed_premium(store, lane, price)
        items.append(ItemInput(lane["part_id"], lane["destination_plant_id"], tenant, int(f["usable_stock"][i]),
                               {target: int(f["demand_units"][i])}, {}, _valuation(store, tenant, lane["part_id"]),
                               _criticality(store, tenant, lane["part_id"]), price))
        ceiling = int(f["lane_ceiling_units"][i])
        cap = {target: ceiling}
        if len(weeks) == 2:
            cap[prior] = int(f["prebuild_units"][i])
        lanes.append(LaneInput(lane_id, lane["supplier_org_id"], lane["part_id"], lane["destination_plant_id"], "PRIMARY", True, 0,
                               price, cap, flex_cap={target: ceiling}, flex_premium_per_unit=prem, max_total=dict(cap),
                               provenance=f"{price_src}; overtime premium: {prem_src}"))
        requirements.append(Requirement(lane_id, f["resource_id"], hours_per_unit))
        alt_ids = f.get("alternate_lane_ids") or []
        alt_id = alt_ids[i] if i < len(alt_ids) else None
        if alt_id:
            alt = store.lanes_by_id[alt_id]
            aprice, asrc = lane_price(store, alt)
            in_time = bool(f.get("alternate_arrives_in_time", True))
            lanes.append(LaneInput(alt_id, alt["supplier_org_id"], alt["part_id"], alt["destination_plant_id"], "ALTERNATE",
                                   bool(f.get("alternate_qualified", True)) and bool(alt.get("qualified", True)),
                                   0 if in_time else len(weeks), aprice, {target: int(f["alternate_units"][i])},
                                   max_total={target: int(f["alternate_units"][i])},
                                   provenance=f"{asrc}; lead time {alt['lead_time_days']} d"
                                              + ("" if in_time else " (arrives after the disrupted week)")))
    regular = {target: float(f["available_hours"])}
    if len(weeks) == 2:
        regular[prior] = float(f.get("prebuild_prior_week_free_hours") or 0.0)
    resource = ResourceInput(f["resource_id"], store.lanes_by_id[f["lane_ids"][0]]["supplier_org_id"], regular,
                             {target: float(f.get("overtime_hours") or 0.0)}, provenance="case fixture override")
    inp = ScenarioInput(f"{f['case_id']}:{mode}", weeks, items, lanes, [resource], requirements, MODE_SETS[mode],
                        econ.holding_rate_annual, require_zero_shortage, None, solver or SolverOptions(time_limit_seconds=20.0),
                        list(econ.assumptions))
    return withhold_other_tenant_economics(inp, owner_tenant), econ


def withhold_other_tenant_economics(inp: ScenarioInput, owner_tenant: str) -> ScenarioInput:
    """Blueprint §11.3 rule 10: another buyer's prices, valuations and priorities must not steer this buyer's plan.

    Items of other tenants that share a supplier resource stay in the model only as a supplier-side resource claim
    (their quantities compete for the same hours) with neutral economics: zero price, zero premium, weight 1.
    """
    others = {it.key for it in inp.items if it.tenant_id != owner_tenant}
    if not others:
        return inp
    for it in inp.items:
        if it.key in others:
            it.valuation_unit_cost = Decimal("0")
            it.reference_unit_price = Decimal("0")
            it.criticality_weight = 1
    for ln in inp.lanes:
        if ln.item_key in others:
            ln.unit_price = Decimal("0")
            ln.flex_premium_per_unit = Decimal("0")
            ln.activation_cost = Decimal("0")
            ln.provenance = "other relationship - economics withheld (resource claim only)"
    inp.assumptions.append(f"{len(others)} item(s) of other buyers share a supplier resource; they enter only as a resource "
                           "claim with neutral economics, and their lines are hidden from this buyer.")
    return inp


# ------------------------------------------------------------------------------------------------
def snapshot_scenario(store, disruption_id: str, mode: str, *, tenant_id: str | None = None, max_items: int = 60,
                      solver: SolverOptions | None = None, require_zero_shortage: bool = False,
                      max_incremental_cost: Decimal | None = None) -> tuple[ScenarioInput, EconomicsContext, dict[str, Any]]:
    """12-week canonical scenario around one disruption, expanded over shared resources."""
    ev = store.disruptions[disruption_id]
    weeks = list(store.week_starts)
    seed_lanes = {ev["lane_id"]} if ev.get("lane_id") else set()
    if ev.get("resource_id"):
        seed_lanes |= set(store.lanes_by_resource.get(ev["resource_id"], []))
    # Expand: items fed by seed lanes -> all lanes into those items -> lanes sharing their resources.
    item_keys: list[tuple[str, str, str]] = []
    lane_ids: set[str] = set()
    frontier = list(sorted(seed_lanes))
    truncated = False
    while frontier:
        lid = frontier.pop(0)
        if lid in lane_ids:
            continue
        lane = store.lanes_by_id[lid]
        key = (lane["tenant_id"], lane["destination_plant_id"], lane["part_id"])
        if key not in item_keys:
            if len(item_keys) >= max_items:
                truncated = True
                continue
            item_keys.append(key)
        lane_ids.add(lid)
        for other in store.lanes_by_part_plant.get((lane["part_id"], lane["destination_plant_id"]), []):
            if other not in lane_ids and store.lanes_by_id[other]["tenant_id"] == lane["tenant_id"]:
                frontier.append(other)
        for rq in store.resource_requirements_by_lane.get(lid, []):
            frontier.extend(x for x in store.lanes_by_resource.get(rq["resource_id"], []) if x not in lane_ids)
    lane_ids = {lid for lid in lane_ids if (store.lanes_by_id[lid]["tenant_id"], store.lanes_by_id[lid]["destination_plant_id"],
                                            store.lanes_by_id[lid]["part_id"]) in item_keys}
    owner_tenant = tenant_id or ev.get("tenant_scope") or store.lanes_by_id[ev["lane_id"]]["tenant_id"]
    econ = _economics(store, owner_tenant)
    econ.assumptions += [
        "Scope SNAPSHOT_HORIZON: 12-week canonical snapshot; disruption applied as recorded in disruption_events.",
        "CONFIRMED receipts are fixed only when released before the horizon (in transit); later ones are re-planned within lane capacity.",
        "Resource regular hours = available - firm reserved; overtime hours = flexible additional hours.",
    ]
    window = {add_weeks(ev["start_week"], k) for k in range(int(ev.get("duration_weeks") or 0))}
    loss = float(ev.get("capacity_loss_percent") or 0)
    surge = D(ev.get("demand_increase_percent") or 0)
    delay_weeks = lead_weeks(int(ev.get("lead_time_extension_days") or 0))

    # Lane roles. Items are multi-sourced in the canonical data: every lane with committed capacity in the
    # horizon is a *current* source (PRIMARY). Only qualified lanes without any committed capacity are
    # ALTERNATE sources, usable when ALTERNATE_SOURCE is enabled.
    econ.assumptions.append("Lanes with committed capacity are current sources; lanes without committed capacity are alternates.")
    current_lanes = {lid for lid in lane_ids if any(int(r["committed_units"]) > 0 for r in store.lane_capacity_for(lid).values())}
    ref_price_by_item: dict[tuple[str, str, str], Decimal] = {}
    for key in item_keys:
        tenant, plant, part = key
        prices = [lane_price(store, store.lanes_by_id[lid])[0] for lid in current_lanes
                  if (store.lanes_by_id[lid]["destination_plant_id"], store.lanes_by_id[lid]["part_id"]) == (plant, part)]
        ref_price_by_item[key] = min(prices) if prices else D(0)

    items: list[ItemInput] = []
    for key in item_keys:
        tenant, plant, part = key
        inv = store.inventory_for(tenant, plant, part) or {}
        demand = store.demand_for(tenant, plant, part)
        if surge and ev.get("lane_id") and store.lanes_by_id[ev["lane_id"]]["part_id"] == part:
            demand = {w: int((D(q) * (1 + surge)).to_integral_value()) if w in window else q for w, q in demand.items()}
        receipts: dict[str, int] = {}
        for rc in store.receipts_for(tenant, plant, part):
            if rc["status"] != "CONFIRMED":
                continue
            arrival = monday_of(date.fromisoformat(str(rc["expected_arrival_at"])[:10]))
            lane = store.lanes_by_id.get(rc["lane_id"])
            lw = lead_weeks(int(lane["lead_time_days"])) if lane else 0
            if arrival in weeks and weeks.index(arrival) - lw < 0:
                receipts[arrival] = receipts.get(arrival, 0) + int(rc["receipt_qty"])
        items.append(ItemInput(part, plant, tenant, int(inv.get("usable_units") or 0), demand, receipts,
                               _valuation(store, tenant, part), _criticality(store, tenant, part), ref_price_by_item[key]))

    lanes: list[LaneInput] = []
    for lid in sorted(lane_ids):
        lane = store.lanes_by_id[lid]
        key = (lane["tenant_id"], lane["destination_plant_id"], lane["part_id"])
        price, psrc = lane_price(store, lane)
        prem, prem_src = disclosed_premium(store, lane, price)
        cap_rows = store.lane_capacity_for(lid)
        committed, flex, ceiling = {}, {}, {}
        for w in weeks:
            row = cap_rows.get(w, {"committed_units": 0, "supplier_offered_flex_units": 0})
            c = int(row["committed_units"])
            if lid == ev.get("lane_id") and not ev.get("resource_id") and w in window and loss:
                c = int(c * (1 - loss))
            committed[w] = c
            flex[w] = int(row["supplier_offered_flex_units"])
            ceiling[w] = int(lane["max_weekly_units"])
        lw = lead_weeks(int(lane["lead_time_days"])) + (delay_weeks if lid == ev.get("lane_id") else 0)
        role = "PRIMARY" if lid in current_lanes else "ALTERNATE"
        lanes.append(LaneInput(lid, lane["supplier_org_id"], lane["part_id"], lane["destination_plant_id"], role,
                               bool(lane["qualified"]), lw, price, committed, flex, prem, ceiling, 0,
                               max(1, int(lane.get("lot_multiple") or 1)), provenance=f"{psrc}; overtime premium: {prem_src}"))

    resources: list[ResourceInput] = []
    requirements: list[Requirement] = []
    res_ids = sorted({rq["resource_id"] for lid in lane_ids for rq in store.resource_requirements_by_lane.get(lid, [])})
    reserved_out: dict[str, float] = {}
    for rid in res_ids:
        cal = store.capacity_calendar_for(rid)
        regular, overtime = {}, {}
        for w in weeks:
            row = cal.get(w)
            if row is None:
                regular[w], overtime[w] = 0.0, 0.0
                continue
            hours = float(row["available_hours"]) - float(row["firm_reserved_hours"])
            if rid == ev.get("resource_id") and w in window and loss:
                hours *= (1 - loss)
            # Lanes on this resource that are outside the scope keep their committed load (no free hours for us).
            for lid in store.lanes_by_resource.get(rid, []):
                if lid in lane_ids:
                    continue
                committed_out = int(store.lane_capacity_for(lid).get(w, {}).get("committed_units", 0))
                hpu = next((float(rq["hours_per_unit"]) for rq in store.resource_requirements_by_lane.get(lid, [])
                            if rq["resource_id"] == rid), 0.0)
                hours -= committed_out * hpu
                reserved_out[rid] = reserved_out.get(rid, 0.0) + committed_out * hpu
            regular[w] = max(hours, 0.0)
            overtime[w] = float(row["flexible_additional_hours"])
        sup = next(iter(store.resource_requirements_by_lane.get(next(iter(store.lanes_by_resource[rid])), [])), {}).get("supplier_org_id", "")
        resources.append(ResourceInput(rid, sup, regular, overtime, provenance="capacity_calendar"))
        for lid in store.lanes_by_resource.get(rid, []):
            if lid in lane_ids:
                for rq in store.resource_requirements_by_lane.get(lid, []):
                    if rq["resource_id"] == rid:
                        requirements.append(Requirement(lid, rid, float(rq["hours_per_unit"]), float(rq.get("setup_hours_if_activated") or 0)))
    if truncated:
        econ.assumptions.append(f"Scope truncated at {max_items} items.")
    if reserved_out:
        econ.assumptions.append("Shared-resource lanes outside the scope keep their committed load: "
                                f"{sum(reserved_out.values()):.1f} resource-hours reserved over the horizon.")
    inp = ScenarioInput(f"{disruption_id}:{mode}", weeks, items, lanes, resources, requirements, MODE_SETS[mode],
                        econ.holding_rate_annual, require_zero_shortage, max_incremental_cost,
                        solver or SolverOptions(time_limit_seconds=60.0, max_relative_gap=0.01), list(econ.assumptions))
    scope = {"disruption_id": disruption_id, "items": len(items), "lanes": len(lanes), "resources": len(resources),
             "truncated": truncated, "window": sorted(window), "out_of_scope_reserved_hours": round(sum(reserved_out.values()), 3)}
    return withhold_other_tenant_economics(inp, owner_tenant), econ, scope
