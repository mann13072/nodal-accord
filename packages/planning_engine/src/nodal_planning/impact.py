"""Affected-network scoping and deterministic baseline-vs-disrupted ledgers (blueprint §10.3, §12.1).

Disrupted projection rule (deterministic, documented): confirmed receipts on a disrupted lane whose
*release* week falls in the disruption window are reduced by the event's capacity-loss percentage (the
supplier cannot produce them); a logistics delay shifts those receipts by the extension. Demand surges
scale demand in the window. This is an explanation aid, not the optimizer.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from nodal_domain.weeks import add_weeks, lead_weeks, monday_of

from .ledger import run_ledger


def disruption_window(ev: dict[str, Any]) -> list[str]:
    return [add_weeks(ev["start_week"], k) for k in range(int(ev.get("duration_weeks") or 0))]


def disrupted_lanes(store, ev: dict[str, Any]) -> set[str]:
    lanes = {ev["lane_id"]} if ev.get("lane_id") else set()
    if ev.get("resource_id"):
        lanes |= set(store.lanes_by_resource.get(ev["resource_id"], []))
    return lanes


def item_ledgers(store, tenant_id: str, items: list[tuple[str, str]], ev: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Baseline and disrupted 12-week ledgers for (part, plant) items of one tenant."""
    weeks = store.week_starts
    window = set(disruption_window(ev)) if ev else set()
    hit = disrupted_lanes(store, ev) if ev else set()
    loss = float(ev.get("capacity_loss_percent") or 0) if ev else 0.0
    surge = float(ev.get("demand_increase_percent") or 0) if ev else 0.0
    delay = int(ev.get("lead_time_extension_days") or 0) if ev else 0
    out = []
    for part, plant in items:
        inv = store.inventory_for(tenant_id, plant, part) or {}
        opening = int(inv.get("usable_units") or 0)
        demand = store.demand_for(tenant_id, plant, part)
        base_rec: dict[str, int] = {}
        dis_rec: dict[str, int] = {}
        evidence = []
        for rc in store.receipts_for(tenant_id, plant, part):
            if rc["status"] != "CONFIRMED":
                continue
            arrival = monday_of(date.fromisoformat(str(rc["expected_arrival_at"])[:10]))
            qty = int(rc["receipt_qty"])
            base_rec[arrival] = base_rec.get(arrival, 0) + qty
            lane = store.lanes_by_id.get(rc["lane_id"], {})
            release = add_weeks(arrival, -lead_weeks(int(lane.get("lead_time_days") or 0)))
            affected = rc["lane_id"] in hit and release in window
            new_qty, new_arrival = qty, arrival
            if affected and loss:
                new_qty = int(qty * (1 - loss))
            if affected and delay:
                new_arrival = add_weeks(arrival, lead_weeks(delay))
            dis_rec[new_arrival] = dis_rec.get(new_arrival, 0) + new_qty
            if affected:
                evidence.append({"receipt_id": rc["receipt_id"], "lane_id": rc["lane_id"], "arrival_week": arrival,
                                 "planned_units": qty, "disrupted_units": new_qty, "disrupted_arrival_week": new_arrival})
        dis_demand = dict(demand)
        if surge and ev and store.lanes_by_id.get(ev.get("lane_id") or "", {}).get("part_id") == part:
            dis_demand = {w: int(q * (1 + surge)) if w in window else q for w, q in demand.items()}
        base = run_ledger(weeks, opening, base_rec, demand)
        dis = run_ledger(weeks, opening, dis_rec, dis_demand)
        out.append({
            "part_id": part, "plant_id": plant, "opening_usable": opening,
            "baseline": [w.as_dict() for w in base.weeks], "disrupted": [w.as_dict() for w in dis.weeks],
            "baseline_first_shortage_week": base.first_shortage_week, "disrupted_first_shortage_week": dis.first_shortage_week,
            "baseline_peak_backlog": base.peak_backlog, "disrupted_peak_backlog": dis.peak_backlog,
            "affected_receipts": evidence,
        })
    return out


def impact_graph(store, *, tenant_id: str, lane_ids: list[str], alternate_lane_ids: list[str], resource_id: str | None,
                 max_nodes: int = 100, max_edges: int = 250) -> dict[str, Any]:
    """Bounded, tenant-filtered subgraph. Never returns the whole network; reports what was hidden."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    hidden_nodes = 0
    other_tenant_lanes = 0

    def add_node(nid: str, kind: str, **attrs) -> bool:
        nonlocal hidden_nodes
        if nid in nodes:
            return True
        if len(nodes) >= max_nodes:
            hidden_nodes += 1
            return False
        org = store.organizations.get(nid, {})
        nodes[nid] = {"id": nid, "kind": kind, "label": org.get("display_name", nid), **attrs}
        return True

    def add_edge(src: str, dst: str, kind: str, **attrs) -> None:
        if src in nodes and dst in nodes and len(edges) < max_edges:
            edges.append({"source": src, "target": dst, "kind": kind, **attrs})

    if resource_id:
        add_node(resource_id, "RESOURCE", highlighted=True, note="shared bottleneck (hours private to supplier)")
        scope_lanes = list(lane_ids) + [x for x in store.lanes_by_resource.get(resource_id, []) if x not in lane_ids]
    else:
        scope_lanes = list(lane_ids)
    for role, ids in (("PRIMARY", scope_lanes), ("ALTERNATE", alternate_lane_ids)):
        for lid in ids:
            lane = store.lanes_by_id.get(lid)
            if lane is None:
                continue
            if lane["tenant_id"] != tenant_id:
                other_tenant_lanes += 1
                continue
            sup, part, plant = lane["supplier_org_id"], lane["part_id"], lane["destination_plant_id"]
            highlighted = lid in lane_ids
            ok = add_node(sup, "SUPPLIER", highlighted=highlighted and role == "PRIMARY")
            ok = add_node(part, "PART", highlighted=highlighted) and ok
            ok = add_node(plant, "PLANT", highlighted=highlighted) and ok
            if ok:
                add_edge(sup, part, "SUPPLIES", lane_id=lid, role=role, qualified=bool(lane["qualified"]),
                         lead_time_days=int(lane["lead_time_days"]))
                add_edge(part, plant, "DELIVERED_TO", lane_id=lid)
                if resource_id and role == "PRIMARY" and any(r["resource_id"] == resource_id for r in store.resource_requirements_by_lane.get(lid, [])):
                    add_edge(sup, resource_id, "OPERATES")
                    add_edge(resource_id, part, "CONSTRAINS", lane_id=lid)
    bom = store.table("bom_edges")
    parts_in_scope = [n for n, v in nodes.items() if v["kind"] == "PART"]
    if parts_in_scope:
        sub = bom[(bom["tenant_id"] == tenant_id) & (bom["child_part_id"].isin(parts_in_scope))]
        for row in sub.to_dict("records"):
            if add_node(row["parent_part_id"], "PART", note="BOM parent"):
                add_edge(row["child_part_id"], row["parent_part_id"], "COMPONENT_OF", quantity_per_parent=int(row["quantity_per_parent"]))
    return {"nodes": list(nodes.values()), "edges": edges, "hidden_nodes": hidden_nodes, "max_nodes": max_nodes,
            "other_relationships_sharing_resource": other_tenant_lanes,
            "completeness_note": "Bounded subgraph of the authorized case scope; not the full supplier network."}
