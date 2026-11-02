"""Recorded input disclosure for a gate's explicitly linked walk-forward evaluation."""
from __future__ import annotations

import json
import math
import sqlite3
from typing import Any

from algua.data.board_provenance import project_snapshot_record
from algua.registry.store import SqliteStrategyRepository

_CANONICAL_IDENTITIES = ("config_hash", "dependency_hash")
_CONTEXT = ("strategy_id", "snapshot_id", "data_source", "timeframe", "seed",
            "period_start", "period_end", "universe_name", "fundamentals_snapshot",
            "news_snapshot", "delisting_snapshot")


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


def _wrapper(status: str, reason: str | None, value: dict[str, Any] | None) -> dict[str, Any]:
    return {"status": status, "reason": reason, "value": value}


def _costs_valid(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "model", "fees", "fees_unit", "slippage", "slippage_unit",
    }:
        return False
    try:
        return _valid_cost_values(value)
    except OverflowError:
        return False


def _valid_cost_values(value: dict[str, Any]) -> bool:
    return (
        value["schema_version"] == "execution-costs/v1"
        and value["model"] == "vectorbt.from_orders"
        and value["fees_unit"] == "fraction_of_trade_notional_per_side"
        and value["slippage_unit"] == "adverse_fill_price_fraction_per_side"
        and all(not isinstance(value[k], bool) and isinstance(value[k], (int, float))
                and math.isfinite(value[k]) and value[k] >= 0 for k in ("fees", "slippage"))
    )


def recorded_run_evidence(
    repo: SqliteStrategyRepository, gate: sqlite3.Row,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Never guess a sibling by recency/name or read a current strategy config."""
    absent = _wrapper("UNAVAILABLE", "run_provenance_absent", None)
    snapshot_absent = _wrapper("UNAVAILABLE", "provenance_absent", None)
    invalid = _wrapper("INVALID", "snapshot_binding_mismatch", None)
    try:
        lineage = decode_json(gate["derived_from"])
        if not isinstance(lineage, list) or not lineage:
            return absent, snapshot_absent
        if len(lineage) != 1 or type(lineage[0]) is not int:
            return invalid, invalid
        sibling = repo.get_run(lineage[0])
        if sibling is None or sibling["kind"] != "walk_forward" or any(
            sibling[k] != gate[k] for k in _CONTEXT
        ):
            return invalid, invalid
        # Gate code hashes use artifact closure; WF stamps use runtime source. Only these two
        # canonical identities share an algorithm across both paths (including model pins).
        if any(value is not None and not isinstance(value, str)
               for key in _CANONICAL_IDENTITIES for value in (sibling[key], gate[key])):
            return invalid, invalid
        for key in _CANONICAL_IDENTITIES:
            if sibling[key] and gate[key] and sibling[key] != gate[key]:
                return invalid, invalid
        if any(not sibling[key] or not gate[key] for key in _CANONICAL_IDENTITIES):
            missing = _wrapper("UNAVAILABLE", "missing_fields", None)
            return missing, missing
        config = decode_json(sibling["config_json"])
        if not isinstance(config, dict):
            return invalid, invalid
        if "run_provenance" not in config:
            return absent, snapshot_absent
        recorded = config["run_provenance"]
        if not isinstance(recorded, dict) or set(recorded) != {"bars", "execution_costs"}:
            return invalid, invalid
        bars, costs = recorded["bars"], recorded["execution_costs"]
        snapshot = (_wrapper("UNAVAILABLE", "provenance_absent", None) if bars is None else
                    project_snapshot_record(gate["snapshot_id"], bars)
                    if isinstance(bars, dict) else invalid)
        if snapshot["status"] == "INVALID" or (costs is not None and not _costs_valid(costs)):
            return invalid, snapshot if snapshot["status"] == "INVALID" else invalid
        value = {"bars_snapshot_id": gate["snapshot_id"],
                 "bars_content_hash": bars["content_hash"] if bars is not None else None,
                 "execution_costs": costs}
        return _wrapper("VALID" if costs is not None else "UNAVAILABLE",
                        None if costs is not None else "execution_costs_absent", value), snapshot
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        return invalid, invalid
