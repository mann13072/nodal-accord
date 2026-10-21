"""File connectors for the two mock external schemas (blueprint §8).

Mappings are read from the generator's versioned mapping YAML (external column -> canonical column).
Rows are validated, invalid rows are quarantined with reason codes (never silently repaired), and the
accepted canonical rows are reconciled against the canonical Parquet snapshot.

These are illustrative mock schemas, not real ERP or SupplyOn payloads.
"""
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Protocol

import yaml

CONNECTOR_VERSION = "1.0"


@dataclass
class ConnectorCapabilities:
    name: str
    mode: str  # FILE | POLL | PUSH
    payload_format: str
    version: str
    entities: list[str]
    permitted_operations: list[str]
    full_or_delta: str
    note: str


@dataclass
class ValidationReport:
    connector: str
    entity: str
    accepted: list[dict[str, Any]] = field(default_factory=list)
    quarantined: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        reasons: dict[str, int] = {}
        for q in self.quarantined:
            for r in q["reasons"]:
                reasons[r] = reasons.get(r, 0) + 1
        return {"entity": self.entity, "accepted": len(self.accepted), "quarantined": len(self.quarantined), "reasons": reasons,
                "quarantine_sample": self.quarantined[:20]}


class SourceConnector(Protocol):
    def describe(self) -> ConnectorCapabilities: ...
    def payload_checksum(self) -> str: ...
    def run(self, store) -> list[ValidationReport]: ...


def _mapping(root: Path, name: str) -> dict[str, Any]:
    return yaml.safe_load((root / "mappings" / name).read_text(encoding="utf-8"))


def _rename(row: dict[str, Any], fields: list[dict[str, Any]]) -> dict[str, Any]:
    out = {}
    for f in fields:
        if f["external_column"] in row:
            out[f["canonical_column"]] = row[f["external_column"]]
    return out


def _is_monday(value: str) -> bool:
    try:
        return date.fromisoformat(str(value)[:10]).weekday() == 0
    except ValueError:
        return False


def _int(value: Any) -> int | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return int(f) if f == int(f) else None


def _checksum(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return "sha256:" + h.hexdigest()


class MockErpConnector:
    """Mock ERP-like CSV export: demand.csv and stock_positions.csv."""

    def __init__(self, external_root: Path):
        self.root = Path(external_root)

    def describe(self) -> ConnectorCapabilities:
        return ConnectorCapabilities("mock_erp", "FILE", "CSV", CONNECTOR_VERSION, ["demand_forecast", "inventory_positions"],
                                     ["READ"], "FULL", "Illustrative ERP-like schema; not a real SAP/ERP contract.")

    def files(self) -> list[Path]:
        return [self.root / "mock_erp" / "demand.csv", self.root / "mock_erp" / "stock_positions.csv"]

    def payload_checksum(self) -> str:
        return _checksum(self.files())

    def run(self, store) -> list[ValidationReport]:
        maps = _mapping(self.root, "mock_erp_to_canonical.yaml")["mappings"]
        return [self._demand(store, maps), self._stock(store, maps)]

    def _demand(self, store, maps) -> ValidationReport:
        rep = ValidationReport("mock_erp", "demand_forecast")
        fields = maps["demand"]["fields"]
        seen = set()
        weeks = set(store.week_starts)
        with (self.root / "mock_erp" / "demand.csv").open(encoding="utf-8", newline="") as fh:
            for n, raw in enumerate(csv.DictReader(fh), start=2):
                row = _rename(raw, fields)
                reasons = []
                for col in ("tenant_id", "plant_id", "part_id", "week_start", "required_units"):
                    if not str(row.get(col, "")).strip():
                        reasons.append(f"MISSING_{col.upper()}")
                if raw.get("unit_code", "EA") != "EA":
                    reasons.append("UNSUPPORTED_UNIT")
                qty = _int(row.get("required_units"))
                if qty is None or qty < 0:
                    reasons.append("INVALID_QUANTITY")
                if row.get("week_start") and not _is_monday(row["week_start"]):
                    reasons.append("WEEK_NOT_MONDAY")
                elif row.get("week_start") and row["week_start"] not in weeks:
                    reasons.append("WEEK_OUTSIDE_HORIZON")
                if (row.get("tenant_id"), row.get("part_id")) not in store.parts:
                    reasons.append("UNKNOWN_PART_FOR_TENANT")
                key = (row.get("tenant_id"), row.get("plant_id"), row.get("part_id"), row.get("week_start"), row.get("revision"))
                if key in seen:
                    reasons.append("DUPLICATE_KEY")
                seen.add(key)
                if reasons:
                    rep.quarantined.append({"source_row": n, "reasons": reasons, "raw": raw})
                else:
                    rep.accepted.append({"tenant_id": row["tenant_id"], "plant_id": row["plant_id"], "part_id": row["part_id"],
                                         "week_start": row["week_start"], "required_units": qty, "revision": _int(row.get("revision")) or 1})
        return rep

    def _stock(self, store, maps) -> ValidationReport:
        rep = ValidationReport("mock_erp", "inventory_positions")
        fields = (maps.get("stock_positions") or maps.get("stock") or {}).get("fields", [])
        with (self.root / "mock_erp" / "stock_positions.csv").open(encoding="utf-8", newline="") as fh:
            for n, raw in enumerate(csv.DictReader(fh), start=2):
                row = _rename(raw, fields) if fields else {}
                tenant = row.get("tenant_id", raw.get("client"))
                plant = row.get("plant_id", raw.get("site_code"))
                part = row.get("part_id", raw.get("material_code"))
                on_hand = _int(row.get("on_hand_units", raw.get("qty_onhand")))
                reserved = _int(row.get("reserved_units", raw.get("qty_reserved")))
                hold = _int(row.get("quality_hold_units", raw.get("qty_blocked")))
                usable = _int(row.get("usable_units", raw.get("qty_usable")))
                reasons = []
                if None in (on_hand, reserved, hold, usable):
                    reasons.append("INVALID_QUANTITY")
                elif reserved + hold > on_hand:
                    reasons.append("RESERVED_PLUS_HOLD_EXCEEDS_ON_HAND")
                elif usable != on_hand - reserved - hold:
                    reasons.append("USABLE_DOES_NOT_RECONCILE")
                if raw.get("unit_code", "EA") != "EA":
                    reasons.append("UNSUPPORTED_UNIT")
                if (tenant, part) not in store.parts:
                    reasons.append("UNKNOWN_PART_FOR_TENANT")
                if reasons:
                    rep.quarantined.append({"source_row": n, "reasons": reasons, "raw": raw})
                else:
                    rep.accepted.append({"tenant_id": tenant, "plant_id": plant, "part_id": part, "on_hand_units": on_hand,
                                         "reserved_units": reserved, "quality_hold_units": hold, "usable_units": usable})
        return rep


class MockCollaborationConnector:
    """Mock supplier-collaboration capacity feed (JSON lines)."""

    def __init__(self, external_root: Path):
        self.root = Path(external_root)

    def describe(self) -> ConnectorCapabilities:
        return ConnectorCapabilities("mock_collaboration", "FILE", "JSONL", CONNECTOR_VERSION, ["lane_capacity"], ["READ"], "FULL",
                                     "Generic capacity-collaboration fixture; not SupplyOn's payload or an official connector.")

    def files(self) -> list[Path]:
        return [self.root / "mock_collaboration" / "supplier_capacity.jsonl"]

    def payload_checksum(self) -> str:
        return _checksum(self.files())

    def run(self, store) -> list[ValidationReport]:
        fields = _mapping(self.root, "mock_collaboration_to_canonical.yaml")["mappings"]["fields"]
        rep = ValidationReport("mock_collaboration", "lane_capacity")
        seen = set()
        for n, line in enumerate(self.files()[0].read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                rep.quarantined.append({"source_row": n, "reasons": ["MALFORMED_JSON"], "raw": line[:200]})
                continue
            row = _rename(raw, fields)
            lane_id = row.get("lane_id", raw.get("route"))
            week = row.get("week_start", raw.get("period"))
            committed = _int(row.get("committed_units", raw.get("confirmed_capacity_units")))
            flex = _int(row.get("supplier_offered_flex_units", raw.get("optional_additional_units")))
            reasons = []
            lane = store.lanes_by_id.get(lane_id)
            if lane is None:
                reasons.append("UNKNOWN_LANE")
            else:
                if lane["supplier_org_id"] != raw.get("partner"):
                    reasons.append("PARTNER_LANE_MISMATCH")
                if lane["part_id"] != raw.get("product") or lane["destination_plant_id"] != raw.get("destination"):
                    reasons.append("PRODUCT_OR_DESTINATION_MISMATCH")
                if raw.get("customer_scope") and lane["tenant_id"] != raw.get("customer_scope"):
                    reasons.append("TENANT_SCOPE_MISMATCH")
            if committed is None or committed < 0 or flex is None or flex < 0:
                reasons.append("INVALID_QUANTITY")
            if raw.get("unit_code", "EA") != "EA":
                reasons.append("UNSUPPORTED_UNIT")
            if not week or not _is_monday(week):
                reasons.append("WEEK_NOT_MONDAY")
            key = (lane_id, week)
            if key in seen:
                reasons.append("DUPLICATE_KEY")
            seen.add(key)
            if reasons:
                rep.quarantined.append({"source_row": n, "reasons": reasons, "raw": raw})
            else:
                rep.accepted.append({"lane_id": lane_id, "tenant_id": lane["tenant_id"], "week_start": week, "committed_units": committed,
                                     "supplier_offered_flex_units": flex, "revision": _int(raw.get("revision")) or 1})
        return [rep]


def reconcile(store, report: ValidationReport) -> dict[str, Any]:
    """Row-by-row comparison of accepted canonical rows against the canonical snapshot."""
    matched, differ, missing = 0, [], 0
    if report.entity == "demand_forecast":
        for r in report.accepted:
            got = store.demand_for(r["tenant_id"], r["plant_id"], r["part_id"]).get(r["week_start"])
            if got is None:
                missing += 1
            elif got == r["required_units"]:
                matched += 1
            else:
                differ.append({"key": [r["tenant_id"], r["plant_id"], r["part_id"], r["week_start"]], "external": r["required_units"], "canonical": got})
    elif report.entity == "inventory_positions":
        for r in report.accepted:
            inv = store.inventory_for(r["tenant_id"], r["plant_id"], r["part_id"])
            if inv is None:
                missing += 1
            elif int(inv["usable_units"]) == r["usable_units"]:
                matched += 1
            else:
                differ.append({"key": [r["tenant_id"], r["plant_id"], r["part_id"]], "external": r["usable_units"], "canonical": int(inv["usable_units"])})
    elif report.entity == "lane_capacity":
        for r in report.accepted:
            got = store.lane_capacity_for(r["lane_id"]).get(r["week_start"])
            if got is None:
                missing += 1
            elif got["committed_units"] == r["committed_units"] and got["supplier_offered_flex_units"] == r["supplier_offered_flex_units"]:
                matched += 1
            else:
                differ.append({"key": [r["lane_id"], r["week_start"]], "external": [r["committed_units"], r["supplier_offered_flex_units"]],
                               "canonical": [got["committed_units"], got["supplier_offered_flex_units"]]})
    return {"entity": report.entity, "matched": matched, "differences": len(differ), "missing_in_canonical": missing,
            "difference_sample": differ[:20]}


def connector_for(name: str, external_root: Path):
    if name == "mock_erp":
        return MockErpConnector(external_root)
    if name == "mock_collaboration":
        return MockCollaborationConnector(external_root)
    raise KeyError(name)
