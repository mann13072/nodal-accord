"""Number fidelity: every number in an AI answer should come from a tool result.

Numbers that are part of identifiers (CASE-000004, LANE-000006) or ISO dates are ignored. Values are compared in
canonical form (1,234.50 == 1234.5; 0.2 == 20%). Unmatched numbers are reported as "unverified", not removed.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:T[\d:.]+Z?)?\b")
_ID = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)*[-_]\d+[A-Za-z0-9]*\b")
_NUM = re.compile(r"(?<![\w.])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:\s?%)?")
SMALL_INTEGER_ALLOWANCE = 12  # "3 options", "week 5": too common to flag


def _strip_ids_and_dates(text: str) -> str:
    return _ID.sub(" ", _DATE.sub(" ", text))


def _canon(d: Decimal) -> str:
    d = d.normalize()
    s = format(d, "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def extract_numbers(text: str) -> list[tuple[str, Decimal, bool]]:
    """Returns (token, value, is_percent) for every free-standing number in text."""
    out = []
    for m in _NUM.finditer(_strip_ids_and_dates(text)):
        tok = m.group(0).strip()
        pct = tok.endswith("%")
        raw = tok.rstrip("%").strip().replace(",", "")
        try:
            out.append((tok, Decimal(raw), pct))
        except InvalidOperation:
            continue
    return out


def _walk(obj: Any) -> Iterable[Any]:
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _walk(v)
    else:
        yield obj


def allowed_values(tool_outputs: Iterable[Any]) -> set[str]:
    allowed: set[str] = set()

    def add(d: Decimal) -> None:
        allowed.add(_canon(d))
        allowed.add(_canon(abs(d)))
        if abs(d) <= 1:
            allowed.add(_canon(d * 100))  # fraction shown as percent
        allowed.add(_canon(d / 100))  # percent shown as fraction
        if d != d.to_integral_value():
            allowed.add(_canon(d.quantize(Decimal("1"))))  # rounded for prose
            allowed.add(_canon(d.quantize(Decimal("0.1"))))
            allowed.add(_canon(d.quantize(Decimal("0.01"))))

    for out in tool_outputs:
        for leaf in _walk(out):
            if isinstance(leaf, bool) or leaf is None:
                continue
            if isinstance(leaf, (int, float, Decimal)):
                try:
                    add(Decimal(str(leaf)))
                except InvalidOperation:
                    pass
            elif isinstance(leaf, str):
                for _, val, _ in extract_numbers(leaf):
                    add(val)
    return allowed


def unverified_numbers(answer: str, tool_outputs: Iterable[Any]) -> list[str]:
    allowed = allowed_values(tool_outputs)
    flagged = []
    for tok, val, pct in extract_numbers(answer or ""):
        if not pct and val == val.to_integral_value() and 0 <= val <= SMALL_INTEGER_ALLOWANCE:
            continue
        candidates = {_canon(val), _canon(abs(val))}
        if pct:
            candidates.add(_canon(val / 100))
        if not candidates & allowed:
            flagged.append(tok)
    return sorted(set(flagged), key=flagged.index)
