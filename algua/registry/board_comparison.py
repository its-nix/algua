"""Recorded, bounded research cohorts for display only; no promotion consumer."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from algua.provenance.snapshot import SCHEMA_VERSION, SnapshotRecord
from algua.registry.gate_comparison_context import (
    METRICS as METRICS,
)
from algua.registry.gate_comparison_context import (
    decode_context as decode_context,
)
from algua.registry.gate_comparison_context import (
    integer,
    number,
)
from algua.registry.gate_comparison_validation import validate_gate_record
from algua.registry.run_provenance import decode_json
from algua.registry.store import SqliteStrategyRepository


def _strict_bars(bars: Any) -> bool:
    if not isinstance(bars, dict):
        return False
    try:
        decoded = SnapshotRecord.from_dict(bars)
        return (decoded.to_dict() == bars and type(bars["schema_version"]) is int
                and bars["schema_version"] == SCHEMA_VERSION
                and re.fullmatch(r"[a-f0-9]{64}", decoded.content_hash) is not None
                and integer(bars["row_count"]) and isinstance(bars["symbols"], list)
                and all(isinstance(s, str) and s for s in bars["symbols"])
                and len(set(bars["symbols"])) == len(bars["symbols"])
                and isinstance(bars["source_metadata"], dict)
                and all(isinstance(k, str) and isinstance(v, str)
                        for k, v in bars["source_metadata"].items())
                and all(k not in bars["source_metadata"]
                        or bars["source_metadata"][k] == bars[k]
                        for k in ("timeframe", "adjustment")))
    except (ValueError, KeyError, TypeError, OverflowError):
        return False


def _unknown(reason: str) -> dict[str, Any]:
    return {"status": "UNKNOWN", "observed_metric_sort_enabled": False,
            "reasons": [reason], "cohort_id": None, "context": None}


def comparison_evidence(
    repo: SqliteStrategyRepository, row: Any, evidence: dict[str, Any],
    recorded: dict[str, Any],
) -> dict[str, Any]:
    """Validate a row independently before computing a cohort; never use present-day inputs."""
    if recorded["status"] != "VALID":
        return _unknown("recorded_inputs_unavailable")
    if any(evidence[k]["status"] != "VALID" for k in (
        "evaluation", "oos_interval", "snapshot_provenance",
    )):
        return _unknown("lineage_or_source_unavailable")
    try:
        # recorded_run_evidence already checked the single sibling and canonical identities.
        sibling = repo.get_run(decode_json(row["derived_from"])[0])
        if sibling is None:
            return _unknown("invalid_recorded_context")
        config = decode_json(sibling["config_json"])
        gate = repo.get_run(row["run_id"])
        if gate is None:
            return _unknown("invalid_recorded_context")
        record = decode_json(gate["config_json"]).get("gate_comparison_record")
        if record is None:
            return _unknown("comparison_context_absent")
        raw = record.get("context") if isinstance(record, dict) else None
        context = decode_context(raw)
        if context is None:
            return _unknown("execution_context_absent" if isinstance(raw, dict)
                            and raw.get("execution", "absent") is None
                            else "invalid_recorded_context")
        snapshot = evidence["snapshot_provenance"]["value"]
        if snapshot["data_tier"] not in ("pilot_real_proxy", "synthetic_fixture"):
            return _unknown("unsupported_data_tier")
        bars = config["run_provenance"]["bars"]
        if (not _strict_bars(bars) or bars["timeframe"] != context["timeframe"]
            or sibling["data_source"] != "StoreBackedProvider"
            or not set(context["execution"]["symbol_order"]) <= set(bars["symbols"])
            or context["windows"][0]["start"] < snapshot["coverage_start"]
            or context["oos"]["end"] > snapshot["coverage_end"]):
            return _unknown("invalid_source_metadata")
        if any(sibling[k] is not None for k in (
            "universe_name", "fundamentals_snapshot", "news_snapshot", "delisting_snapshot",
        )) or decode_json(sibling["components"]) != []:
            return _unknown("unsupported_modal_inputs")
        if any(not isinstance(sibling[k], str) or not sibling[k].strip()
               for k in ("code_hash", "config_hash", "dependency_hash")):
            return _unknown("missing_artifact_identity")
        if not isinstance(gate["code_hash"], str) or not gate["code_hash"].strip():
            return _unknown("missing_artifact_identity")
        # These code hashes deliberately retain different schemes; config/dependencies were
        # matched upstream. Modal components must agree independently, including empty lists.
        if decode_json(gate["components"]) != decode_json(sibling["components"]):
            return _unknown("invalid_recorded_context")
        if sibling["metric_schema_version"] != 1 or row["metric_schema_version"] != 1:
            return _unknown("unsupported_metric_schema")
        for key in ("period_start", "period_end", "timeframe"):
            if context[key] != row[key]:
                return _unknown("invalid_recorded_context")
        oos = evidence["oos_interval"]["value"]
        if context["oos"] != {"start": oos["holdout_start"], "end": oos["holdout_end"],
                              "n_bars": oos["n_bars"]}:
            return _unknown("invalid_recorded_context")
        if not validate_gate_record(repo, record, gate, sibling):
            return _unknown("invalid_canonical_lineage")
        for key in ("sharpe_oos", "total_return_oos", "max_drawdown_oos", "n_obs_oos"):
            if row[key] is not None and not number(row[key]):
                return _unknown("metric_binding_mismatch")
        if (row["total_return_oos"] is not None and row["total_return_oos"] < -1
            or row["max_drawdown_oos"] is not None and not -1 <= row["max_drawdown_oos"] <= 0):
            return _unknown("metric_binding_mismatch")
        cohort = {**context, "execution_costs": recorded["value"]["execution_costs"],
                  "snapshot_id": bars["snapshot_id"], "content_hash": bars["content_hash"],
                  "data_tier": snapshot["data_tier"], "source": snapshot,
                  "dependency_hash": sibling["dependency_hash"]}
        # JSON gives stable equality for numbers written as int or float by different callers.
        costs = cohort["execution_costs"]
        cohort["execution_costs"] = {**costs, "fees": float(costs["fees"]),
                                     "slippage": float(costs["slippage"])}
        encoded = json.dumps(cohort, sort_keys=True, allow_nan=False).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        return {"status": "COMPARABLE", "observed_metric_sort_enabled": True, "reasons": [],
                "cohort_id": digest, "context": cohort}
    except (ValueError, KeyError, TypeError, IndexError, OverflowError, RecursionError):
        return _unknown("invalid_recorded_context")
