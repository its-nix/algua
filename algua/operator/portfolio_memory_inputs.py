"""Closed whole-input admission of declared in-sample portfolio replay evidence only."""
from __future__ import annotations

import copy
import hashlib
import json

from algua.evaluation.portfolio_manifest import _Manifest
from algua.operator.portfolio_memory_schema import (
    BOOK,
    encoded,
    exact,
    require,
    same,
    validate_metrics,
    validate_provenance,
)
from algua.provenance.research_disclosure import public_bars
from algua.provenance.snapshot_evidence import project_snapshot_record

_LIMITATIONS = ["static_universe_not_verified_pit", "no_delisting_records",
               "no_promotion_or_trading_authority", "replay_not_elapsed_forward_test"]


def _plain_json(value: object) -> None:
    pending = [value]
    while pending:
        item = pending.pop()
        if type(item) is dict:
            require(all(type(key) is str for key in item))
            pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)
        else:
            require(item is None or type(item) in (str, int, float, bool))


def _validate(config: object) -> dict:
    require(exact(config, {"portfolio_replay"}))
    # JSON detachment excludes non-JSON objects and every non-finite opaque parameter too.
    raw = encoded(config)  # Also refuse cycles before walking the original input.
    _plain_json(config)
    value = json.loads(raw)
    payload = value["portfolio_replay"]
    require(exact(payload, {"schema_version", "portfolio_name", "evidence_class", "is_forward_test",
        "data_tier", "data_provenance", "limitations", "manifest", "provenance", "metrics"}))
    require(payload["schema_version"] == "portfolio-replay-result/v1"
            and payload["evidence_class"] == "in_sample_research_replay"
            and payload["is_forward_test"] is False)
    manifest = payload["manifest"]
    normalized = _Manifest.model_validate(copy.deepcopy(manifest)).model_dump()
    require(same(manifest, normalized))
    provenance = payload["provenance"]
    validate_provenance(manifest, provenance)
    validate_metrics(payload["metrics"], manifest, provenance)
    bars = provenance["bars_provenance"]
    require(same(public_bars(bars), bars))
    evidence: dict
    if bars is None:
        evidence = {"status": "UNAVAILABLE", "reason": "provenance_absent", "value": None}
    else:
        require(bars["snapshot_id"] == manifest["snapshot_id"] and bars["dataset"] == "bars"
                and bars["kind"] == "bars" and bars["timeframe"] == "1d"
                and set(manifest["symbols"]) <= set(bars["symbols"]))
        evidence = project_snapshot_record(manifest["snapshot_id"], bars)
        require(evidence["status"] == "VALID")
    source = evidence["value"]
    require(same(payload["data_provenance"], evidence)
            and payload["data_tier"] == (source["data_tier"] if source is not None else "unknown")
            and same(payload["limitations"], _LIMITATIONS + (
                source["limitations"] if source is not None else ["data_provenance_unavailable"])))
    require(provenance["config_hash"] == hashlib.sha256(encoded(
        {k: provenance[k] for k in BOOK})).hexdigest())
    require(payload["portfolio_name"] == "portfolio-replay:" + hashlib.sha256(encoded({
        "manifest": manifest, "provenance": provenance})).hexdigest())
    return value


def public_portfolio_inputs(config: object) -> dict:
    """Return detached original input or refuse; perform no runtime/source/store resolution.

    The caller admits only a backtest row and separately binds its ledger metadata/metrics.
    Validated declarations and internal hashes remain unverified worker evidence, never authority.
    """
    try:
        return _validate(config)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise ValueError("portfolio_memory:invalid_input") from None
