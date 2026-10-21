"""Canonical JSON digests used for snapshot hashes, offer terms and approvals."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def _default(o: Any) -> Any:
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    raise TypeError(f"not serialisable: {type(o)!r}")


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_default)


def sha256_digest(payload: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(payload).encode()).hexdigest()
