"""Planning buckets are Monday dates formatted YYYY-MM-DD (blueprint §7.3)."""
from __future__ import annotations

import math
from datetime import date, timedelta


def parse_week(value: str) -> date:
    d = date.fromisoformat(str(value)[:10])
    if d.weekday() != 0:
        raise ValueError(f"planning week {value} is not a Monday")
    return d


def add_weeks(week: str, n: int) -> str:
    return (parse_week(week) + timedelta(weeks=n)).isoformat()


def week_index(weeks: list[str], week: str) -> int:
    return weeks.index(week)


def lead_weeks(lead_time_days: int) -> int:
    """A lane with a positive lead time can never deliver in the release week."""
    if lead_time_days <= 0:
        return 0
    return math.ceil(lead_time_days / 7)


def monday_of(day: date) -> str:
    return (day - timedelta(days=day.weekday())).isoformat()
