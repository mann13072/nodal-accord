"""Decimal money helpers. Stored business values are Decimal; solvers may use floats internally,
but every reported amount is recomputed here from integer quantities (blueprint §7.3)."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

CENT = Decimal("0.01")
CURRENCY = "EUR"


def D(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def money(value: Any) -> Decimal:
    return D(value).quantize(CENT, rounding=ROUND_HALF_UP)


def money_str(value: Any) -> str:
    return f"{money(value):.2f}"
