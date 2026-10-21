"""Read-only canonical snapshot backed by the generator's Parquet output.

The generated dataset lives outside this repository (see NODAL_DATA_ROOT). Nothing here writes to it.
Tables load lazily and are cached per process; callers must apply access policy before returning rows.
"""
from __future__ import annotations

import json
import threading
from functools import cached_property
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.dataset as ds


class SnapshotNotFound(FileNotFoundError):
    pass


class SnapshotStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        if not (self.root / "tables").is_dir():
            raise SnapshotNotFound(f"no generated dataset at {self.root} (expected a tables/ directory)")
        self._tables: dict[str, pd.DataFrame] = {}
        self._lock = threading.Lock()

    # ---- raw access -------------------------------------------------------------------------
    def table(self, name: str) -> pd.DataFrame:
        with self._lock:
            if name not in self._tables:
                path = self.root / "tables" / f"{name}.parquet"
                if not path.exists():
                    raise SnapshotNotFound(f"table {name} missing from {self.root}")
                frame = ds.dataset(str(path), format="parquet", partitioning="hive").to_table().to_pandas()
                # Hive partition columns come back as categoricals; normalise to plain strings.
                for col in frame.columns:
                    if isinstance(frame[col].dtype, pd.CategoricalDtype):
                        frame[col] = frame[col].astype(str)
                self._tables[name] = frame
            return self._tables[name]

    def has_table(self, name: str) -> bool:
        return (self.root / "tables" / f"{name}.parquet").exists()

    @cached_property
    def manifest(self) -> dict[str, Any]:
        path = self.root / "manifest.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    @property
    def dataset_label(self) -> str:
        return self.root.name

    @cached_property
    def snapshot_id(self) -> str:
        m = self.manifest
        seed = m.get("seed") or m.get("config", {}).get("seed")
        return f"SNAP-{self.dataset_label}-{seed if seed is not None else 'unseeded'}"

    @cached_property
    def week_starts(self) -> list[str]:
        return sorted(self.table("planning_weeks")["week_start"].astype(str).tolist())

    # ---- curated case fixtures -------------------------------------------------------------
    def case_fixture(self, case_id: str) -> dict[str, Any] | None:
        path = self.root / "scenarios" / f"{case_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def policy_expectations(self) -> list[dict[str, Any]]:
        path = self.root / "access-tests" / "policy_expected_results.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def golden(self, name: str) -> Any:
        path = self.root / "golden" / f"{name}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    # ---- indexed lookups ---------------------------------------------------------------------
    @cached_property
    def lanes_by_id(self) -> dict[str, dict[str, Any]]:
        return {r["lane_id"]: r for r in self.table("sourcing_lanes").to_dict("records")}

    @cached_property
    def resource_requirements_by_lane(self) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {}
        for r in self.table("resource_lane_requirements").to_dict("records"):
            out.setdefault(r["lane_id"], []).append(r)
        return out

    @cached_property
    def lanes_by_resource(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for r in self.table("resource_lane_requirements").to_dict("records"):
            out.setdefault(r["resource_id"], []).append(r["lane_id"])
        return out

    @cached_property
    def lanes_by_part_plant(self) -> dict[tuple[str, str], list[str]]:
        out: dict[tuple[str, str], list[str]] = {}
        for lane in self.lanes_by_id.values():
            out.setdefault((lane["part_id"], lane["destination_plant_id"]), []).append(lane["lane_id"])
        return out

    @cached_property
    def organizations(self) -> dict[str, dict[str, Any]]:
        return {r["org_id"]: r for r in self.table("organizations").to_dict("records")}

    @cached_property
    def parts(self) -> dict[tuple[str, str], dict[str, Any]]:
        return {(r["tenant_id"], r["part_id"]): r for r in self.table("parts").to_dict("records")}

    @cached_property
    def tenants(self) -> dict[str, dict[str, Any]]:
        return {r["tenant_id"]: r for r in self.table("tenants").to_dict("records")}

    @cached_property
    def financial_profiles(self) -> dict[str, dict[str, Any]]:
        return {r["tenant_id"]: r for r in self.table("buyer_financial_profiles").to_dict("records")}

    @cached_property
    def buyer_terms(self) -> dict[tuple[str, str], dict[str, Any]]:
        return {(r["relationship_id"], r["part_id"]): r for r in self.table("buyer_commercial_terms").to_dict("records")}

    @cached_property
    def private_economics_by_lane(self) -> dict[str, dict[str, Any]]:
        return {r["lane_id"]: r for r in self.table("supplier_private_economics").to_dict("records")}

    @cached_property
    def shareable_offers_by_lane(self) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {}
        if self.has_table("supplier_shareable_offers"):
            for r in self.table("supplier_shareable_offers").to_dict("records"):
                out.setdefault(r["lane_id"], []).append(r)
        return out

    @cached_property
    def disruptions(self) -> dict[str, dict[str, Any]]:
        return {r["disruption_id"]: r for r in self.table("disruption_events").to_dict("records")}

    @cached_property
    def principals(self) -> dict[str, dict[str, Any]]:
        """Demo principals. A principal may appear once per tenant scope; scopes are merged."""
        out: dict[str, dict[str, Any]] = {}
        for r in self.table("supplier_user_roles").to_dict("records"):
            if not r.get("active", True):
                continue
            p = out.setdefault(r["principal_id"], {"principal_id": r["principal_id"], "org_id": r["org_id"],
                                                   "role": r["role"], "tenant_scopes": set()})
            p["tenant_scopes"].add(r["tenant_scope"])
        return out

    def capacity_calendar_for(self, resource_id: str) -> dict[str, dict[str, Any]]:
        cal = self._calendar_index.get(resource_id, {})
        return cal

    @cached_property
    def _calendar_index(self) -> dict[str, dict[str, dict[str, Any]]]:
        out: dict[str, dict[str, dict[str, Any]]] = {}
        for r in self.table("capacity_calendar").to_dict("records"):
            out.setdefault(r["resource_id"], {})[str(r["week_start"])] = r
        return out

    @cached_property
    def _lane_capacity_index(self) -> dict[str, dict[str, dict[str, Any]]]:
        out: dict[str, dict[str, dict[str, Any]]] = {}
        frame = self.table("lane_capacity")[["lane_id", "week_start", "committed_units", "supplier_offered_flex_units", "confidence"]]
        for lane_id, week, committed, flex, conf in frame.itertuples(index=False):
            out.setdefault(lane_id, {})[str(week)] = {"committed_units": int(committed), "supplier_offered_flex_units": int(flex), "confidence": float(conf)}
        return out

    def lane_capacity_for(self, lane_id: str) -> dict[str, dict[str, Any]]:
        return self._lane_capacity_index.get(lane_id, {})

    @cached_property
    def _demand_index(self) -> dict[tuple[str, str, str], dict[str, int]]:
        frame = self.table("demand_forecast")
        latest = frame.sort_values("revision").drop_duplicates(["tenant_id", "plant_id", "part_id", "week_start"], keep="last")
        out: dict[tuple[str, str, str], dict[str, int]] = {}
        for t, pl, pa, wk, units in latest[["tenant_id", "plant_id", "part_id", "week_start", "required_units"]].itertuples(index=False):
            out.setdefault((t, pl, pa), {})[str(wk)] = int(units)
        return out

    def demand_for(self, tenant_id: str, plant_id: str, part_id: str) -> dict[str, int]:
        return dict(self._demand_index.get((tenant_id, plant_id, part_id), {}))

    @cached_property
    def _inventory_index(self) -> dict[tuple[str, str, str], dict[str, Any]]:
        return {(r["tenant_id"], r["plant_id"], r["part_id"]): r for r in self.table("inventory_positions").to_dict("records")}

    def inventory_for(self, tenant_id: str, plant_id: str, part_id: str) -> dict[str, Any] | None:
        return self._inventory_index.get((tenant_id, plant_id, part_id))

    @cached_property
    def _receipts_index(self) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
        out: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        cols = ["receipt_id", "tenant_id", "lane_id", "part_id", "destination_plant_id", "receipt_qty", "expected_arrival_at", "status"]
        for row in self.table("scheduled_receipts")[cols].to_dict("records"):
            out.setdefault((row["tenant_id"], row["destination_plant_id"], row["part_id"]), []).append(row)
        return out

    def receipts_for(self, tenant_id: str, plant_id: str, part_id: str) -> list[dict[str, Any]]:
        return list(self._receipts_index.get((tenant_id, plant_id, part_id), []))


_STORES: dict[str, SnapshotStore] = {}
_STORES_LOCK = threading.Lock()


def get_store(root: str | Path) -> SnapshotStore:
    key = str(Path(root).resolve())
    with _STORES_LOCK:
        if key not in _STORES:
            _STORES[key] = SnapshotStore(key)
        return _STORES[key]
