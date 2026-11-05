"""Bounded public exploration from a worker-owned registry, never imported gate authority."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from algua.operator.research_memory_checkpoint import strict_json
from algua.operator.research_memory_inputs import public_memory_inputs, validate_portfolio_bindings
from algua.operator.research_memory_model_refs import public_model_refs
from algua.registry.db.constants import METRIC_SCHEMA_VERSION, SCHEMA_VERSION
from algua.registry.read_snapshot import registry_snapshot
from algua.registry.store.run_public import (
    WINDOW_METRICS,
    public_extra,
    public_number,
    public_rows,
)

_KINDS = ("backtest", "walk_forward", "sweep", "sweep_trial")
_IS_METRICS = (
    "sharpe_is", "sortino_is", "total_return_is", "max_drawdown_is", "ann_vol_is",
    "cagr_is", "calmar_is", "n_obs_is",
)
_PROVENANCE = (
    "code_hash", "config_hash", "dependency_hash", "data_source", "snapshot_id",
    "universe_name", "fundamentals_snapshot", "news_snapshot", "delisting_snapshot", "seed",
    "timeframe", "period_start", "period_end",
)
_COLUMNS = (
    "id", "kind", "strategy_name", "strategy_id", "created_at", "metric_schema_version",
    "derived_from", "components", "config_json", "trials_truncated_at",
    *_PROVENANCE, *_IS_METRICS, *sorted(WINDOW_METRICS),
)


@dataclass(frozen=True)
class MemoryLimits:
    max_rows: int = 20_000
    max_database_bytes: int = 128 * 1024 * 1024
    max_config_bytes: int = 64 * 1024
    max_archive_bytes: int = 16 * 1024 * 1024

    def __post_init__(self) -> None:
        ceilings = (20_000, 128 * 1024 * 1024, 64 * 1024, 16 * 1024 * 1024)
        values = (self.max_rows, self.max_database_bytes, self.max_config_bytes,
                  self.max_archive_bytes)
        if any(type(v) is not int or not 1 <= v <= cap
               for v, cap in zip(values, ceilings, strict=True)):
            raise ValueError("research memory limits must be positive bounded integers")


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, allow_nan=False,
                      separators=(",", ":"), ensure_ascii=False).encode()


def _source(worker_root: Path) -> Path:
    root = worker_root.resolve(strict=True)
    source = root / ".funnel-scratch/data/algua.db"
    if source.is_symlink() or not source.resolve().is_relative_to(root):
        raise ValueError("research memory source escapes its worker root")
    return source


def _schema(conn: Any) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    table = conn.execute("SELECT type FROM sqlite_master WHERE name='runs'").fetchone()
    columns = {row[1] for row in conn.execute("PRAGMA table_info(runs)")}
    if version != SCHEMA_VERSION or table is None or table[0] != "table":
        raise ValueError("research memory source schema is unsupported")
    if not set(_COLUMNS) <= columns:
        raise ValueError("research memory source columns are missing")
    metrics_table = conn.execute(
        "SELECT type FROM sqlite_master WHERE name='run_metrics'").fetchone()
    metric_columns = {row[1] for row in conn.execute("PRAGMA table_info(run_metrics)")}
    if (metrics_table is None or metrics_table[0] != "table"
            or not {"run_id", "key", "value"} <= metric_columns):
        raise ValueError("research memory source metrics schema is unsupported")


def _prefix(conn: Any, watermark: int, limits: MemoryLimits) -> tuple[int, str]:
    """Fingerprint inherited rows plus the known public overflow, without exporting values.

    A high-water mark alone loses new experiments after an accidental registry reset/ID reuse.
    Require the seeded prefix to remain identical before classifying those IDs as inherited.
    """
    digest = hashlib.sha256()
    count = size = 0
    queries = (
        ("runs", "SELECT * FROM runs WHERE id<=? ORDER BY id LIMIT ?"),
        ("run_metrics", "SELECT m.run_id,m.key,m.value FROM run_metrics m "
         "JOIN runs r ON r.id=m.run_id WHERE r.id<=? AND r.kind='sweep' "
         "AND m.key='mean_trial_sharpe' ORDER BY m.run_id,m.key LIMIT ?"),
    )
    inherited_count = 0
    for table, sql in queries:
        for row in conn.execute(sql, (watermark, limits.max_rows + 1)):
            count += 1
            if count > limits.max_rows:
                raise ValueError("research memory inherited prefix exceeds its row bound")
            raw = canonical_bytes({"table": table, "row": dict(row)})
            size += len(raw)
            if size > limits.max_database_bytes:
                raise ValueError("research memory inherited prefix exceeds its byte bound")
            digest.update(len(raw).to_bytes(8, "big"))
            digest.update(raw)
            inherited_count += table == "runs"
    return inherited_count, digest.hexdigest()


def seed_evidence(worker_root: Path, limits: MemoryLimits) -> dict[str, Any]:
    with registry_snapshot(_source(worker_root), max_bytes=limits.max_database_bytes,
                           timeout_seconds=5) as snapshot:
        conn = snapshot.connection
        _schema(conn)
        row = conn.execute("SELECT coalesce(max(id),0),count(*) FROM runs").fetchone()
        count, digest = _prefix(conn, row[0], limits)
        if count != row[1]:
            raise ValueError("research memory seed prefix is incomplete")
        return {"worker_root": str(worker_root.resolve()), "runs_max_id": row[0],
                "inherited_run_count": row[1], "registry_digest": snapshot.source_digest,
                "inherited_runs_digest": digest, "schema_version": SCHEMA_VERSION}


def _model_refs(value: Any, kind: str) -> list[dict[str, Any]]:
    return public_model_refs(value, kind=kind)


def public_evaluations(
    worker_root: Path, seed: dict[str, Any], cycle_id: str, limits: MemoryLimits,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if seed["worker_root"] != str(worker_root.resolve()):
        raise ValueError("research memory seed belongs to another worker")
    with registry_snapshot(_source(worker_root), max_bytes=limits.max_database_bytes,
                           timeout_seconds=5) as snapshot:
        conn = snapshot.connection
        _schema(conn)
        count, digest = _prefix(conn, seed["runs_max_id"], limits)
        if count != seed["inherited_run_count"] or digest != seed["inherited_runs_digest"]:
            raise ValueError("research memory inherited prefix changed after seeding")
        placeholders = ",".join("?" for _ in _KINDS)
        sql = (f"SELECT {','.join(_COLUMNS)} FROM runs WHERE id>? AND kind IN ({placeholders}) "
               "ORDER BY id LIMIT ?")
        args = (seed["runs_max_id"], *_KINDS, limits.max_rows + 1)
        raw_rows = conn.execute(sql, args).fetchall()
        if len(raw_rows) > limits.max_rows:
            raise ValueError("research memory row bound exceeded; no evidence truncated")
        models = {}
        total_bytes = 0
        for row in raw_rows:
            parsed = {}
            for key in ("config_json", "components", "derived_from"):
                raw = row[key]
                if not isinstance(raw, str) or len(raw.encode()) > limits.max_config_bytes:
                    raise ValueError("research memory input JSON exceeds its bound")
                total_bytes += len(raw.encode())
                if total_bytes > limits.max_archive_bytes:
                    raise ValueError("research memory inputs exceed the archive byte bound")
                parsed[key] = strict_json(raw)
            if not isinstance(parsed["config_json"], dict):
                raise ValueError("research memory config must be an object")
            config = parsed["config_json"]
            if (canonical_bytes(public_memory_inputs(row["kind"], config))
                    != canonical_bytes(config)):
                raise ValueError("research memory input config shape is unsupported")
            parents = parsed["derived_from"]
            if (not isinstance(parents, list)
                    or any(type(parent) is not int or parent < 1 for parent in parents)):
                raise ValueError("research memory source lineage is malformed")
            models[row["id"]] = _model_refs(parsed["components"], row["kind"])
        extra_rows = conn.execute(
            "SELECT m.run_id,m.value FROM run_metrics m JOIN runs r ON r.id=m.run_id "
            "WHERE r.id>? AND r.kind='sweep' AND m.key='mean_trial_sharpe' "
            "ORDER BY r.id LIMIT ?", (seed["runs_max_id"], limits.max_rows + 1)).fetchall()
        if len(extra_rows) > limits.max_rows:
            raise ValueError("research memory public overflow exceeds its row bound")
        extras = {row["run_id"]: public_extra("sweep", {"mean_trial_sharpe": row["value"]})
                  for row in extra_rows}
        # Project only after bounded raw JSON validation: legacy readers intentionally salvage
        # malformed WF config, which is insufficient evidence to admit destructive cleanup.
        rows = public_rows(conn.execute(sql, args))
    evaluations = []
    truncated = []
    for row in rows:
        if row["metric_schema_version"] != METRIC_SCHEMA_VERSION:
            raise ValueError("research memory metric vocabulary is unsupported")
        raw_config = row["config_json"]
        if not isinstance(raw_config, str) or len(raw_config.encode()) > limits.max_config_bytes:
            raise ValueError("research memory config exceeds its bound")
        config = json.loads(raw_config)
        if not isinstance(config, dict):
            raise ValueError("research memory config must be an object")
        parents = json.loads(row["derived_from"])
        if (not isinstance(parents, list)
                or any(type(parent) is not int or parent < 1 for parent in parents)):
            raise ValueError("research memory source lineage is malformed")
        ref = f"scratch:{cycle_id}:runs:{row['id']}"
        metrics = _IS_METRICS if row["kind"] == "backtest" else sorted(WINDOW_METRICS)
        observation = {
            "source_ref": ref, "source_run_id": row["id"], "kind": row["kind"],
            "strategy_name": row["strategy_name"], "strategy_local_id": row["strategy_id"],
            "created_at": row["created_at"],
            "parent_refs": [f"scratch:{cycle_id}:runs:{parent}" for parent in parents],
            "provenance": {key: row[key] for key in _PROVENANCE},
            "model_refs": models[row["id"]],
            "inputs": public_memory_inputs(row["kind"], config),
            "metrics": {key: public_number(row[key]) for key in metrics},
            "extra_metrics": extras.get(row["id"], {}),
        }
        validate_portfolio_bindings(row["kind"], observation["inputs"],
            strategy_name=row["strategy_name"], strategy_local_id=row["strategy_id"],
            provenance=observation["provenance"], metrics=observation["metrics"],
            model_refs=observation["model_refs"], parent_refs=observation["parent_refs"],
            extra_metrics=observation["extra_metrics"])
        evaluations.append(observation)
        if row["kind"] == "sweep" and row["trials_truncated_at"] is not None:
            truncated.append({"source_ref": ref, "retained_limit": row["trials_truncated_at"]})
    return evaluations, {
        "retained_evaluations": len(evaluations),
        "kind_counts": dict(Counter(row["kind"] for row in evaluations)),
        "inherited_run_count": seed["inherited_run_count"], "truncated_sweeps": truncated,
        "unrecorded_variant_failures": "UNKNOWN", "model_bytes_preserved": False,
    }
