"""Closed, detached public-memory vocabulary shared by the parent and batch reader."""
from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime
from typing import Any

from algua.operator.research_memory_checkpoint import canonical, strict_json, validated_seed
from algua.operator.research_memory_inputs import (
    context_input_limit,
    public_memory_inputs,
    validate_portfolio_bindings,
)
from algua.operator.research_memory_model_refs import public_model_refs
from algua.registry.store.run_public import WINDOW_METRICS
from algua.tracking.research_archive import valid_run_id

KINDS = {"backtest", "walk_forward", "sweep", "sweep_trial"}
IS_METRICS = {"sharpe_is", "sortino_is", "total_return_is", "max_drawdown_is", "ann_vol_is",
              "cagr_is", "calmar_is", "n_obs_is"}
PROVENANCE = {"code_hash", "config_hash", "dependency_hash", "data_source", "snapshot_id",
              "universe_name", "fundamentals_snapshot", "news_snapshot", "delisting_snapshot",
              "seed", "timeframe", "period_start", "period_end"}
COVERAGE = {"candidate_attempts_considered", "candidate_cycles", "selected_cycles",
            "cycles_without_receipt", "retained_public_observations", "included_observations",
            "omitted_observations", "omitted_for_input_bytes", "omitted_for_context_bytes",
            "omitted_for_count", "omitted_truncation_markers", "truncated_sweeps",
            "unrecorded_variant_failures", "evaluated_worktree_verified"}
VIEW_FIELDS = {"source_ref", "archive_ref", "kind", "strategy_name", "parent_refs", "model_refs",
               "provenance", "inputs", "metrics", "extra_metrics"}
CYCLE = r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}"
ATTEMPT = re.compile(r"idea_attempts:([1-9][0-9]*)\Z")
SOURCE = re.compile(rf"scratch:({CYCLE}):runs:([1-9][0-9]*)\Z")
REFERENCE = re.compile(r"mlflow:(.+)/public-evidence\.json#sha256=([0-9a-f]{64})\Z", re.DOTALL)


def memory_reference(value: Any) -> re.Match[str] | None:
    match = REFERENCE.fullmatch(value) if isinstance(value, str) else None
    return match if match is not None and valid_run_id(match[1]) else None


class MemoryContextError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"public_memory_context:{reason}")


def require(condition: Any, reason: str = "artifact_payload_invalid") -> None:
    if not condition:
        raise MemoryContextError(reason)


def integer(value: Any, minimum: int = 0) -> bool:
    return type(value) is int and minimum <= value <= 2**63 - 1


def exact(value: Any, keys: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == keys


def model_refs(value: Any, kind: str) -> None:
    try:
        public_model_refs(value, kind=kind)
    except ValueError as exc:
        raise MemoryContextError("artifact_payload_invalid") from exc


def observation(value: Any, cycle_id: str, *, archived: bool) -> None:
    keys = VIEW_FIELDS - {"archive_ref"}
    if archived:
        keys |= {"source_run_id", "strategy_local_id", "created_at"}
    else:
        keys |= {"archive_ref"}
    require(exact(value, keys))
    match = SOURCE.fullmatch(value["source_ref"]) if isinstance(value["source_ref"], str) else None
    if match is None or match[1] != cycle_id:
        raise MemoryContextError("artifact_payload_invalid")
    if archived:
        require(integer(value["source_run_id"], 1) and int(match[2]) == value["source_run_id"])
        require(value["strategy_local_id"] is None or integer(value["strategy_local_id"], 1))
        require(isinstance(value["created_at"], str) and len(value["created_at"]) <= 128)
        datetime.fromisoformat(value["created_at"])
    require(value["kind"] in KINDS and isinstance(value["strategy_name"], str)
            and bool(value["strategy_name"]))
    require(isinstance(value["parent_refs"], list) and all(
        isinstance(p, str) and (m := SOURCE.fullmatch(p)) is not None and m[1] == cycle_id
        for p in value["parent_refs"]))
    require(exact(value["provenance"], PROVENANCE))
    require(all(v is None or (type(v) is int and -(2**63) <= v < 2**63
                             if k == "seed" else isinstance(v, str))
                for k, v in value["provenance"].items()))
    require(isinstance(value["inputs"], dict)
            and canonical(public_memory_inputs(value["kind"], value["inputs"]))
            == canonical(value["inputs"]))
    metrics = IS_METRICS if value["kind"] == "backtest" else set(WINDOW_METRICS)
    require(exact(value["metrics"], metrics))
    require(all(v is None or type(v) in (int, float) and math.isfinite(v)
                for v in value["metrics"].values()))
    extra = value["extra_metrics"]
    require(isinstance(extra, dict) and set(extra) <= (
        {"mean_trial_sharpe"} if value["kind"] == "sweep" else set()))
    require(all(v is None or type(v) in (int, float) and math.isfinite(v) for v in extra.values()))
    model_refs(value["model_refs"], value["kind"])
    validate_portfolio_bindings(value["kind"], value["inputs"],
        strategy_name=value["strategy_name"], strategy_local_id=value.get("strategy_local_id"),
        provenance=value["provenance"], metrics=value["metrics"], model_refs=value["model_refs"],
        parent_refs=value["parent_refs"], extra_metrics=value["extra_metrics"])


def _validate_payload(payload: Any, cycle_id: str) -> None:
    require(exact(payload, {"schema_version", "research_cycle_id", "evidence_mode", "authority",
        "source_commit", "worker_exit", "controller_context_digest", "seed", "attempt_refs",
        "evaluations", "coverage"}))
    require(payload["schema_version"] == "research-memory/v1"
            and payload["research_cycle_id"] == cycle_id
            and payload["evidence_mode"] == "UNVERIFIED_WORKER" and payload["authority"] == "none")
    require(isinstance(payload["source_commit"], str)
            and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", payload["source_commit"]))
    require(type(payload["worker_exit"]) is int and -255 <= payload["worker_exit"] <= 255)
    require(isinstance(payload["controller_context_digest"], str)
            and re.fullmatch(r"[0-9a-f]{64}", payload["controller_context_digest"]))
    require(isinstance(payload["seed"], dict) and "worker_root" not in payload["seed"])
    validated_seed({"worker_root": "", **payload["seed"]})
    refs = payload["attempt_refs"]
    require(isinstance(refs, list) and len(refs) <= 40)
    require(all(exact(r, {"evidence_id", "idea_id"}) and integer(r["idea_id"], 1)
                and isinstance(r["evidence_id"], str) and ATTEMPT.fullmatch(r["evidence_id"])
                for r in refs))
    require(len({r["evidence_id"] for r in refs}) == len(refs))
    evaluations = payload["evaluations"]
    require(isinstance(evaluations, list) and len(evaluations) <= 20_000)
    for row in evaluations:
        observation(row, cycle_id, archived=True)
    require(len({r["source_run_id"] for r in evaluations}) == len(evaluations))
    coverage = payload["coverage"]
    require(exact(coverage, {"retained_evaluations", "kind_counts", "inherited_run_count",
        "truncated_sweeps", "unrecorded_variant_failures", "model_bytes_preserved",
        "evaluated_worktree_verified"}))
    require(integer(coverage["retained_evaluations"])
            and coverage["retained_evaluations"] == len(evaluations)
            and integer(coverage["inherited_run_count"]))
    require(isinstance(coverage["kind_counts"], dict)
            and all(k in KINDS and integer(v, 1) for k, v in coverage["kind_counts"].items()))
    require(coverage["kind_counts"] == dict(Counter(r["kind"] for r in evaluations)))
    require(coverage["unrecorded_variant_failures"] == "UNKNOWN"
            and coverage["model_bytes_preserved"] is False
            and coverage["evaluated_worktree_verified"] is False)
    sweep_refs = {r["source_ref"] for r in evaluations if r["kind"] == "sweep"}
    markers(coverage["truncated_sweeps"], sweep_refs)


def validate_payload(payload: Any, cycle_id: str) -> None:
    try:
        _validate_payload(payload, cycle_id)
    except MemoryContextError:
        raise
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        raise MemoryContextError("artifact_payload_invalid") from exc


def markers(value: Any, sweeps: set[str]) -> None:
    require(isinstance(value, list) and len(value) <= len(sweeps))
    require(all(exact(m, {"source_ref", "retained_limit"}) and m["source_ref"] in sweeps
                and integer(m["retained_limit"]) for m in value))
    require(len({m["source_ref"] for m in value}) == len(value))


def validate_snapshot(value: Any) -> dict:
    try:
        require(len(canonical(value)) <= 24 * 1024)
        value = strict_json(canonical(value))
        require(exact(value, {"schema_version", "status", "evidence_mode", "authority",
            "association",
            "scorecard_attempt_cutoff", "archive_store_sha256", "selection_protocol", "receipts",
            "observations", "coverage"}))
        require(value["schema_version"] == "campaign-public-memory/v1"
                and value["evidence_mode"] == "UNVERIFIED_WORKER" and value["authority"] == "none"
                and value["association"] == "cycle_only"
                and value["selection_protocol"] == "relevant_attempts_desc/v1")
        require(integer(value["scorecard_attempt_cutoff"]))
        require(isinstance(value["archive_store_sha256"], str)
                and re.fullmatch(r"[0-9a-f]{64}", value["archive_store_sha256"]))
        receipts = value["receipts"]
        require(isinstance(receipts, list) and len(receipts) <= 2)
        cycles: dict[str, str] = {}
        for receipt in receipts:
            require(exact(receipt, {"research_cycle_id", "evidence_ref", "archive_sha256",
                                    "attempt_evidence_ids"}))
            cycle = receipt["research_cycle_id"]
            require(isinstance(cycle, str) and re.fullmatch(CYCLE, cycle) and cycle not in cycles)
            reference = receipt["evidence_ref"]
            require(isinstance(reference, str) and (m := memory_reference(reference)) is not None
                    and m[2] == receipt["archive_sha256"])
            require(reference not in cycles.values())
            ids = receipt["attempt_evidence_ids"]
            require(isinstance(ids, list) and len(ids) <= 40 and len(set(ids)) == len(ids))
            require(all(isinstance(i, str) and (a := ATTEMPT.fullmatch(i)) is not None
                        and int(a[1]) <= value["scorecard_attempt_cutoff"] for i in ids))
            cycles[cycle] = reference
        observations = value["observations"]
        require(isinstance(observations, list) and len(observations) <= 24)
        order = []
        for row in observations:
            require(isinstance(row, dict) and isinstance(row.get("source_ref"), str)
                    and (source := SOURCE.fullmatch(row["source_ref"])) is not None)
            if source is None:
                raise MemoryContextError("worker_result_invalid")
            require(source[1] in cycles and row.get("archive_ref") == cycles[source[1]])
            observation(row, source[1], archived=False)
            require(len(canonical(row["inputs"]))
                    <= context_input_limit(row["kind"], row["inputs"]))
            order.append((list(cycles).index(source[1]), int(source[2])))
        require(order == sorted(set(order)))
        coverage = value["coverage"]
        require(exact(coverage, COVERAGE))
        require(all(integer(v) for k, v in coverage.items() if k not in {
            "truncated_sweeps", "unrecorded_variant_failures", "evaluated_worktree_verified"}))
        require(coverage["candidate_attempts_considered"] <= 64
                and coverage["candidate_cycles"] <= coverage["candidate_attempts_considered"]
                and coverage["selected_cycles"] == len(receipts)
                and coverage["cycles_without_receipt"] <= coverage["candidate_cycles"]
                and coverage["selected_cycles"] <= coverage["candidate_cycles"])
        require(coverage["included_observations"] == len(observations)
                and coverage["omitted_observations"] == sum(coverage[k] for k in (
                    "omitted_for_input_bytes", "omitted_for_count", "omitted_for_context_bytes"))
                and coverage["retained_public_observations"] == len(observations)
                    + coverage["omitted_observations"])
        require(coverage["unrecorded_variant_failures"] == "UNKNOWN"
                and coverage["evaluated_worktree_verified"] is False)
        markers(coverage["truncated_sweeps"], {r["source_ref"] for r in observations
                                               if r["kind"] == "sweep"})
        require(value["status"] == ("available" if observations else "unavailable"))
        return value
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        raise MemoryContextError("worker_result_invalid") from exc
