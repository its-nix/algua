"""Strict recorded JSON: duplicate keys and nonfinite numbers are invalid evidence."""
from __future__ import annotations

import json
import math
from typing import Any


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _bad_constant(value: str) -> Any:
    raise ValueError(f"nonfinite JSON constant: {value}")


def _finite_float(raw: str) -> float:
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError("nonfinite JSON number")
    return value


def decode_json(raw: str) -> Any:
    return json.loads(raw, object_pairs_hook=_unique, parse_constant=_bad_constant,
                      parse_float=_finite_float)


