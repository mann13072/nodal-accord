"""Weekly inventory/backlog ledger for one part at one plant (blueprint §10.1).

Usable inventory and backlog are kept as two non-negative fields; inventory is never negative.
    available       = opening_usable + eligible_receipts
    fulfilled       = min(available, demand + prior_backlog)
    closing_usable  = available - fulfilled
    closing_backlog = demand + prior_backlog - fulfilled
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class LedgerWeek:
    week_start: str
    opening_usable: int
    receipts: int
    demand: int
    prior_backlog: int
    fulfilled: int
    closing_usable: int
    closing_backlog: int

    @property
    def is_short(self) -> bool:
        return self.closing_backlog > 0

    def as_dict(self) -> dict:
        return asdict(self) | {"is_short": self.is_short}


@dataclass(frozen=True)
class LedgerResult:
    weeks: list[LedgerWeek]

    @property
    def first_shortage_week(self) -> str | None:
        return next((w.week_start for w in self.weeks if w.is_short), None)

    @property
    def final_backlog(self) -> int:
        return self.weeks[-1].closing_backlog if self.weeks else 0

    @property
    def peak_backlog(self) -> int:
        return max((w.closing_backlog for w in self.weeks), default=0)

    @property
    def backlog_unit_weeks(self) -> int:
        return sum(w.closing_backlog for w in self.weeks)


def run_ledger(week_starts: list[str], opening_usable: int, receipts: dict[str, int], demand: dict[str, int]) -> LedgerResult:
    if opening_usable < 0:
        raise ValueError("opening usable inventory must be non-negative")
    rows: list[LedgerWeek] = []
    usable, backlog = opening_usable, 0
    for week in week_starts:
        rec = int(receipts.get(week, 0))
        dem = int(demand.get(week, 0))
        if rec < 0 or dem < 0:
            raise ValueError(f"negative receipt or demand in {week}")
        available = usable + rec
        fulfilled = min(available, dem + backlog)
        closing_usable = available - fulfilled
        closing_backlog = dem + backlog - fulfilled
        rows.append(LedgerWeek(week, usable, rec, dem, backlog, fulfilled, closing_usable, closing_backlog))
        usable, backlog = closing_usable, closing_backlog
    return LedgerResult(rows)
