"""Closed request data for the explicitly labelled historical-proxy producer."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

REQUEST_SCHEMA = "price-linear-proxy-train/v1"
REQUEST_BYTES = 64 * 1024


def aware_utc(value: object, *, midnight: bool = False) -> datetime:
    if not isinstance(value, str):
        raise ValueError("an explicit aware ISO timestamp is required")
    try:
        stamp = datetime.fromisoformat(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError("an explicit aware ISO timestamp is required") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    stamp = stamp.astimezone(UTC)
    if midnight and any((stamp.hour, stamp.minute, stamp.second, stamp.microsecond)):
        raise ValueError("training bounds must be UTC-midnight event labels")
    return stamp


@dataclass(frozen=True)
class TrainRequest:
    bars_snapshot_id: str
    symbols: tuple[str, ...]
    train_start: datetime
    train_end: datetime
    l2: float
    raw_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {"schema": REQUEST_SCHEMA, "bars_snapshot_id": self.bars_snapshot_id,
                "symbols": list(self.symbols), "train_start": self.train_start.isoformat(),
                "train_end": self.train_end.isoformat(), "l2": self.l2}


def parse_request(raw: bytes) -> TrainRequest:
    if type(raw) is not bytes or len(raw) > REQUEST_BYTES:
        raise ValueError("training request exceeds its UTF-8 byte limit")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("training request contains a duplicate field")
            result[key] = value
        return result

    def constant(value: str) -> None:
        raise ValueError("training request contains a nonfinite number")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("training request must be bounded UTF-8 JSON") from exc
    fields = {"schema", "bars_snapshot_id", "symbols", "train_start", "train_end", "l2"}
    if not isinstance(value, dict) or set(value) != fields or value["schema"] != REQUEST_SCHEMA:
        raise ValueError("training request requires exactly the six proxy-v1 fields")
    snapshot, symbols, penalty = value["bars_snapshot_id"], value["symbols"], value["l2"]
    if (not isinstance(snapshot, str) or not snapshot or snapshot != snapshot.strip()
            or len(snapshot.encode("utf-8")) > 128):
        raise ValueError("an explicit bounded snapshot ID is required")
    if (not isinstance(symbols, list) or not 1 <= len(symbols) <= 512
            or any(not isinstance(s, str) or not s or s != s.strip() for s in symbols)
            or len(set(symbols)) != len(symbols)):
        raise ValueError("symbols must be explicit ordered unique nonempty strings")
    if type(penalty) not in (int, float):
        raise ValueError("l2 must be finite and positive, excluding booleans")
    try:
        penalty = float(penalty)
    except OverflowError as exc:
        raise ValueError("l2 exceeds float64 range") from exc
    if not math.isfinite(penalty) or penalty <= 0:
        raise ValueError("l2 must be finite and positive")
    start, end = (aware_utc(value[key], midnight=True) for key in ("train_start", "train_end"))
    if start >= end:
        raise ValueError("train_start must precede half-open train_end")
    return TrainRequest(snapshot, tuple(symbols), start, end, float(penalty),
                        hashlib.sha256(raw).hexdigest())
