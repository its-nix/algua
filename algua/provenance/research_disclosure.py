"""Closed public input-metadata projection; no outcome fields or authority flags."""
from __future__ import annotations

import json
import math
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from algua.provenance.research import RESEARCH_PROVENANCE_KEY, ResearchProvenanceError
from algua.provenance.snapshot import (
    BARS_STREAMED_HASH_ALGO,
    SnapshotRecord,
    compute_snapshot_id,
    validate_declared_manifest_record,
)

_COST_CONSTANTS = {
    "schema_version": "execution-costs/v1", "model": "vectorbt.from_orders",
    "fees_unit": "fraction_of_trade_notional_per_side",
    "slippage_unit": "adverse_fill_price_fraction_per_side",
}


def _scalars(value: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {k: value[k] for k in keys if k in value
            and (value[k] is None or isinstance(value[k], (str, int, float, bool)))}


def public_bars(value: Any) -> dict[str, Any] | None:
    """Preserve a complete canonical input; never salvage malformed evidence by stripping it."""
    if value is None:
        return None
    if not isinstance(value, dict):
        return {"invalid_fields": True}
    try:
        metadata = value.get("source_metadata")
        if not isinstance(metadata, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in metadata.items()
        ):
            raise ValueError("malformed source metadata")
        record = SnapshotRecord.from_dict(value)
        canonical = record.to_dict()
        if json.dumps(value, sort_keys=True, allow_nan=False) != json.dumps(
            canonical, sort_keys=True, allow_nan=False
        ):
            raise ValueError("noncanonical snapshot record")
        validate_declared_manifest_record(record)
        if compute_snapshot_id(record.metadata, record.content_hash) != record.snapshot_id:
            raise ValueError("snapshot identity mismatch")
        if not _known_input_metadata(record):
            raise ValueError("unsupported public input metadata")
    except (ValueError, TypeError, KeyError, OverflowError, ResearchProvenanceError):
        return {"invalid_fields": True}
    return canonical


def _known_input_metadata(record: SnapshotRecord) -> bool:
    """Admit whole shipped producer shapes, independently of canonical/hash validity.

    This local view selects a shape only; the returned canonical record is never stripped.
    Arbitrary INTERNAL metadata remains legal in the store but has no public admission.
    """
    source = dict(record.metadata.source_metadata or {})
    source.pop(RESEARCH_PROVENANCE_KEY, None)  # Independently validated by the envelope parser.
    streamed = {"observed_start", "observed_end", "content_hash_algorithm"}
    requested = {"requested_start", "requested_end"}
    if source.keys() & (streamed | requested):
        if not streamed <= source.keys():
            return False
        if (source.pop("content_hash_algorithm") != BARS_STREAMED_HASH_ALGO
                or source.pop("observed_start") != record.start
                or source.pop("observed_end") != record.end):
            return False
        for key in requested & source.keys():
            raw = source.pop(key)
            day = date.fromisoformat(raw)
            if day.isoformat() != raw:
                return False
            if (key == "requested_start" and day < date.fromisoformat(record.start)
                    or key == "requested_end" and day > date.fromisoformat(record.end)):
                return False
    for key in ("raw_dir", "adjusted_dir", "raw_file", "adjusted_file", "corp_actions_file"):
        if key not in source:
            continue
        raw = source[key]
        if Path(raw).name != raw:
            return False
        try:
            decoded = json.loads(raw)
        except ValueError:
            continue
        if isinstance(decoded, (dict, list)):
            return False
    keys = set(source)
    if not keys:
        return True  # Generic local bars/file ingestion supplies no producer extras.
    if keys == {"library", "timeframe", "adjustment"}:
        return (record.provider == "yfinance" and source["library"] == "yfinance"
                and source["timeframe"] == record.metadata.timeframe
                and source["adjustment"] == "none")
    if keys == {"api", "base_url", "timeframe", "adjustment"}:
        url = urlsplit(source["base_url"])
        return (record.provider == "alpaca" and source["api"] == "alpaca"
                and source["timeframe"] == record.metadata.timeframe
                and source["adjustment"] == "raw+all" and url.scheme == "https"
                and url.hostname == "data.alpaca.markets")
    # CLI importers consolidate chunk metadata into directory/corporate-action input metadata.
    if source.get("vendor") == "firstratedata" and record.provider == "firstrate":
        return (keys == {"vendor", "raw_dir", "adjusted_dir"}
                or keys == {"vendor", "symbol", "raw_file", "adjusted_file"}
                and source["symbol"] in record.symbols)
    if source.get("vendor") == "databento" and record.provider == "databento":
        return (keys == {"vendor", "symbol", "raw_file"} and source["symbol"] in record.symbols
                or keys == {"vendor", "raw_dir", "corp_actions_file", "corp_actions_sha256",
                            "ca_schema_version"} and source["ca_schema_version"] == "1"
                and re.fullmatch(r"[0-9a-f]{64}", source["corp_actions_sha256"]) is not None)
    return False


def public_number(value: Any) -> float | int | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        return value if math.isfinite(value) else None
    except OverflowError:
        return None


def public_numbers(value: Any, keys: tuple[str, ...],
                   integers: tuple[str, ...] = ()) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {k: (value[k] if type(value[k]) is int else None) if k in integers
            else public_number(value[k]) for k in keys if k in value}


def public_run_provenance(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - {"bars", "execution_costs"}:
        return {"invalid_fields": True}
    costs = value.get("execution_costs")
    if costs is not None:
        valid = (isinstance(costs, dict)
                 and set(costs) == set(_COST_CONSTANTS) | {"fees", "slippage"}
                 and all(costs[k] == v for k, v in _COST_CONSTANTS.items())
                 and all(public_number(costs[k]) is not None and costs[k] >= 0
                         for k in ("fees", "slippage")))
        costs = dict(costs) if valid else {"invalid_fields": True}
    return {"bars": public_bars(value.get("bars")), "execution_costs": costs}


STABILITY_KEYS = ("mean_sharpe", "std_sharpe", "min_sharpe", "pct_positive_windows")
_WINDOW_NUMBERS = ("index", "n_bars", "total_return", "ann_return",
                "ann_volatility", "max_drawdown", "hit_rate", "tail_ratio", "sharpe",
                "sortino", "cagr", "calmar", "skewness", "kurtosis")


def public_stability(value: Any) -> dict[str, Any]:
    return public_numbers(value, STABILITY_KEYS)


def public_window_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Project WF/sweep result namespaces, leaving explicit user params/grid opaque."""
    out = _scalars(payload, (
        "strategy", "config_hash", "data_source", "snapshot_id", "timeframe",
        "code_hash", "dependency_hash",
        "universe_name", "fundamentals_snapshot", "news_snapshot", "rank_by",
    ))
    out.update(public_numbers(payload, (
        "seed", "windows", "holdout_frac", "embargo", "n_combos", "trial_sharpe_count",
        "trial_sharpe_mean", "trial_sharpe_var_ann",
    ), ("seed", "windows", "embargo", "n_combos", "trial_sharpe_count")))
    out["period"] = _scalars(payload.get("period"), ("start", "end"))
    snapshots = payload.get("universe_snapshots")
    out["universe_snapshots"] = ([_scalars(s, ("snapshot_id", "effective_date")) for s in snapshots]
                                 if isinstance(snapshots, list) else None)
    if "stability" in payload:
        out["stability"] = public_stability(payload["stability"])
    if "window_metrics" in payload:
        out["window_metrics"] = [
            _scalars(w, ("start", "end")) | public_numbers(w, _WINDOW_NUMBERS, ("index", "n_bars"))
            for w in payload["window_metrics"]]
    if "ranked" in payload:
        out["grid"] = payload["grid"]
        out["ranked"] = [public_trial(r) for r in payload["ranked"]]
        out["best"] = public_trial(payload["best"]) if payload.get("best") is not None else None
    out["bars_provenance"] = public_bars(payload.get("bars_provenance"))
    out["execution_costs"] = public_run_provenance({
        "execution_costs": payload.get("execution_costs")})["execution_costs"]
    return out


def public_trial(value: dict[str, Any]) -> dict[str, Any]:
    out = _scalars(value, ("config_hash",))
    out.update(public_numbers(value, ("n_windows", "score"), ("n_windows",)))
    if "params" in value:
        out["params"] = value["params"]
    out["stability"] = public_stability(value.get("stability"))
    for key, projected in public_run_provenance({
        "bars": value.get("bars_provenance"), "execution_costs": value.get("execution_costs"),
    }).items():
        out["bars_provenance" if key == "bars" else key] = projected
    return out
