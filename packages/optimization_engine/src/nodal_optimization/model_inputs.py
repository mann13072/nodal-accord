"""Solver-independent scenario inputs.

Quantities are integer EA. Money is Decimal (EUR). Every input carries a provenance string so the
UI can show where a number came from. Inputs must already be restricted to data the requesting case
is authorised to use (blueprint §11.3 rule 10); this module does not perform access control.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from nodal_domain.enums import MitigationMode

ItemKey = tuple[str, str]  # (part_id, plant_id)


@dataclass
class ItemInput:
    part_id: str
    plant_id: str
    tenant_id: str
    opening_usable: int
    demand: dict[str, int]
    receipts: dict[str, int] = field(default_factory=dict)  # eligible CONFIRMED arrivals only, counted once
    valuation_unit_cost: Decimal = Decimal("0")
    criticality_weight: int = 1
    reference_unit_price: Decimal = Decimal("0")  # planned buyer price used to measure premiums

    @property
    def key(self) -> ItemKey:
        return (self.part_id, self.plant_id)


@dataclass
class LaneInput:
    lane_id: str
    supplier_org_id: str
    part_id: str
    plant_id: str
    role: str  # PRIMARY | ALTERNATE
    qualified: bool
    lead_weeks: int
    unit_price: Decimal
    committed_cap: dict[str, int]
    flex_cap: dict[str, int] = field(default_factory=dict)  # overtime units the supplier has disclosed
    flex_premium_per_unit: Decimal = Decimal("0")
    max_total: dict[str, int] = field(default_factory=dict)  # contractual ceiling per week (regular + flex)
    min_lot: int = 0
    lot_multiple: int = 1
    activation_cost: Decimal = Decimal("0")
    locked_releases: dict[str, int] = field(default_factory=dict)  # frozen / already approved releases
    provenance: str = ""

    @property
    def item_key(self) -> ItemKey:
        return (self.part_id, self.plant_id)


@dataclass
class ResourceInput:
    resource_id: str
    supplier_org_id: str
    regular_hours: dict[str, float]
    overtime_hours: dict[str, float] = field(default_factory=dict)
    provenance: str = ""


@dataclass
class Requirement:
    lane_id: str
    resource_id: str
    hours_per_unit: float
    setup_hours: float = 0.0


@dataclass
class SolverOptions:
    time_limit_seconds: float = 30.0
    max_relative_gap: float = 0.0
    shortage_tolerance_units: float = 0.0  # slack allowed in stage 2 on the stage-1 optimum


@dataclass
class ScenarioInput:
    scenario_label: str
    weeks: list[str]
    items: list[ItemInput]
    lanes: list[LaneInput]
    resources: list[ResourceInput] = field(default_factory=list)
    requirements: list[Requirement] = field(default_factory=list)
    modes: frozenset[MitigationMode] = frozenset({MitigationMode.BASELINE})
    holding_rate_annual: Decimal = Decimal("0.18")
    require_zero_shortage: bool = False
    max_incremental_cost: Decimal | None = None
    solver: SolverOptions = field(default_factory=SolverOptions)
    assumptions: list[str] = field(default_factory=list)

    # ---- mode switches -------------------------------------------------------------------
    @property
    def allow_overtime(self) -> bool:
        return MitigationMode.OVERTIME in self.modes or MitigationMode.HYBRID in self.modes

    @property
    def allow_alternate(self) -> bool:
        return MitigationMode.ALTERNATE_SOURCE in self.modes or MitigationMode.HYBRID in self.modes

    @property
    def allow_prebuild(self) -> bool:
        # HYBRID means overtime + alternate source (blueprint case category 8 and the generator oracle);
        # prebuild is a separate option and must be selected explicitly.
        return MitigationMode.PREBUILD in self.modes

    def lane_usable(self, lane: LaneInput) -> bool:
        if not lane.qualified:
            return False
        if lane.role == "ALTERNATE" and not self.allow_alternate:
            return False
        return True

    def size(self) -> dict[str, int]:
        return {"weeks": len(self.weeks), "items": len(self.items), "lanes": len(self.lanes),
                "resources": len(self.resources), "requirements": len(self.requirements)}


MODE_SETS: dict[str, frozenset[MitigationMode]] = {
    "baseline": frozenset({MitigationMode.BASELINE}),
    "overtime": frozenset({MitigationMode.OVERTIME}),
    "alternate": frozenset({MitigationMode.ALTERNATE_SOURCE}),
    "prebuild": frozenset({MitigationMode.PREBUILD}),
    "hybrid": frozenset({MitigationMode.HYBRID}),
}
