"""Trusted bounded controller over the existing idea-attempt ledger.

Only immutable cycle context is stored outside SQLite; attempts and fencing remain owned by
IdeaAttemptsRepository. A restart closes unfinished attempts, never launches their work again.
The caller holds the existing research-loop flock across setup, worker and finalization.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from algua.contracts.idea import AttemptOutcome, Idea
from algua.operator.research_cycle_results import report_outcomes
from algua.registry.campaign_selection import menu_from_history, selection_ids
from algua.registry.idea_attempts import ClaimTokenMismatch, IdeaAttemptsRepository
from algua.registry.idea_scorecard import campaign_scorecard


@dataclass(frozen=True)
class CycleLimits:
    max_hypotheses: int = 3
    max_wall_seconds: int = 2700
    worker_limit: int = 1
    cpu_seconds: int = 2700
    memory_mb: int = 16384
    file_mb: int = 512
    max_cost: float | None = None

    def __post_init__(self) -> None:
        bounds = {"max_hypotheses": 40, "max_wall_seconds": 86400, "worker_limit": 1,
                  "cpu_seconds": 86400, "memory_mb": 65536, "file_mb": 1024}
        for key, ceiling in bounds.items():
            value = getattr(self, key)
            if type(value) is not int or not 1 <= value <= ceiling:
                raise ValueError(f"{key} must be an integer in [1, {ceiling}]")
        if self.max_cost is not None and (
            not math.isfinite(self.max_cost) or self.max_cost < 0
        ):
            raise ValueError("max_cost must be finite and nonnegative")


def duration_seconds(value: str) -> int:
    match = re.fullmatch(r"([1-9][0-9]*)([smh]?)", value)
    if match is None:
        raise ValueError("timeout must be a positive integer with optional s/m/h suffix")
    seconds = int(match[1]) * {"": 1, "s": 1, "m": 60, "h": 3600}[match[2]]
    if seconds > 86400:
        raise ValueError("timeout cannot exceed 24h")
    return seconds


def file_hash(path: Path) -> str | None:
    if not path.is_file():
        return None
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class ResearchCycle:
    def __init__(self, conn: sqlite3.Connection, directory: Path, cycle_id: str) -> None:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", cycle_id) is None:
            raise ValueError("invalid research_cycle_id")
        self.conn, self.directory, self.cycle_id = conn, directory, cycle_id
        self.path = directory / f"{cycle_id}.json"
        self.attempts = IdeaAttemptsRepository(conn)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def rows(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.conn.execute(
            "SELECT * FROM idea_attempts WHERE run_stamp=? ORDER BY id", (self.cycle_id,))]

    def _metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = json.loads(self.path.read_text())
        database = str(Path(self.conn.execute("PRAGMA database_list").fetchone()[2]).resolve())
        if metadata["request"]["database"] != database:
            raise ValueError("cycle context belongs to another registry")
        return metadata

    def _request(self, *, limits: CycleLimits, context: dict[str, Any], ttl_minutes: int,
                 category: str | None = None, preview_hold_hours: int = 72) -> dict[str, Any]:
        database = str(Path(self.conn.execute("PRAGMA database_list").fetchone()[2]).resolve())
        if ttl_minutes * 60 < limits.max_wall_seconds:
            raise ValueError("claim TTL must cover the complete cycle wall-time budget")
        return {"research_cycle_id": self.cycle_id, "database": database,
                "limits": asdict(limits), "context": context, "category": category,
                "claim_ttl_minutes": ttl_minutes, "preview_hold_hours": preview_hold_hours}

    def campaign_menu(self, **kwargs: Any) -> dict[str, Any]:
        """Read one consistent feedback snapshot for an explicit chooser; claim nothing."""
        if self.conn.in_transaction:
            raise RuntimeError("campaign_menu requires a top-level connection")
        with self.conn:
            self.conn.execute("BEGIN")
            return menu_from_history(campaign_scorecard(self.conn), self._request(**kwargs))

    def start(self, *, limits: CycleLimits, context: dict[str, Any], ttl_minutes: int,
              category: str | None = None, preview_hold_hours: int = 72,
              campaign: dict | None = None) -> tuple[list[Idea], dict[str, Any]]:
        """Persist intent before claiming. Repeating an ID only reconciles existing work."""
        request = self._request(limits=limits, context=context, ttl_minutes=ttl_minutes,
                                category=category, preview_hold_hours=preview_hold_hours)
        if campaign is not None:
            selection_ids(campaign)
            if campaign["menu"]["request"] != request:
                raise ValueError("campaign resource/source context changed")
            request["campaign"] = campaign
        # Round-trip detaches caller-owned mutable objects and enforces serializable context.
        request = json.loads(json.dumps(request, allow_nan=False))
        with self._locked():
            if self.path.exists():
                previous = self._metadata()
                if previous["request"] != request:
                    raise ValueError("cycle identity/context is immutable")
                return [], self._finish(phase="controller_restart", worker_exit=1)
            if self.rows():
                raise ValueError("cycle ID already has attempts without this controller's context")
            # A driver killed after claim commit but before stdout was received is recovered
            # from the SAME attempt rows. Only cycles with this helper's context are adopted.
            pending = self.conn.execute(
                "SELECT DISTINCT run_stamp FROM idea_attempts WHERE outcome IS NULL").fetchall()
            for row in pending:
                if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", row[0]) is None:
                    continue  # unrelated legacy run stamps are not ours to adopt
                prior = ResearchCycle(self.conn, self.directory, row[0])
                if prior.path.exists():
                    recovered = prior._finish(phase="controller_restart", worker_exit=1)
                    if recovered["unfinished_count"] or recovered["write_errors"]:
                        raise RuntimeError("prior cycle recovery unfinished; refusing new claims")
            now = time.time()
            metadata = {"request": request, "created_at": now,
                        "deadline": now + limits.max_wall_seconds}
            # The directory lock excludes readers until a fully flushed context is published.
            temp = self.path.with_suffix(".tmp")
            with temp.open("w") as stream:
                json.dump(metadata, stream, allow_nan=False, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            temp.replace(self.path)
            directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            if limits.max_cost is not None:
                return [], self.summary(phase="cost_unknown")
            campaign_args: dict[str, Any] = (
                {} if campaign is None else {"campaign": request["campaign"]})
            claimed = self.attempts.claim(
                run_stamp=self.cycle_id, limit=limits.max_hypotheses,
                ttl_minutes=ttl_minutes, category=category,
                preview_hold_hours=preview_hold_hours, **campaign_args)
            return claimed, self.summary(phase="running" if claimed else "pool_empty")

    def finish(self, *, phase: str, worker_exit: int, report: Path | None = None,
               evidence_ref: str | None = None) -> dict[str, Any]:
        with self._locked():
            if not self.path.exists():
                raise ValueError("cycle context does not exist")
            return self._finish(phase=phase, worker_exit=worker_exit, report=report,
                                evidence_ref=evidence_ref)

    def verify_context(self, *, context: dict[str, Any], scratch_data: Path) -> None:
        """Refuse source/data drift during scratch setup, before invoking the runtime."""
        with self._locked():
            expected = self._metadata()["request"]["context"]
            if context != expected:
                raise ValueError("cycle source/data context changed during setup")
            if file_hash(scratch_data / "manifest.jsonl") != expected["data_manifest_sha256"]:
                raise ValueError("scratch data manifest differs from immutable cycle context")

    def _finish(self, *, phase: str, worker_exit: int, report: Path | None = None,
                evidence_ref: str | None = None) -> dict[str, Any]:
        metadata = self._metadata()
        expired = time.time() >= metadata["deadline"]
        entries = report_outcomes(report) if phase == "completed" and worker_exit == 0 else {}
        if phase == "completed" and worker_exit != 0:
            phase = "worker_failed"
        if expired:
            entries, phase = {}, "wall_time_exhausted"
        write_errors = []
        for row in self.rows():
            if row["outcome"] is not None:
                continue  # never spend a token twice or rewrite a drainer's result
            outcome, reason = entries.get(row["idea_id"], (
                AttemptOutcome.RUN_ERROR,
                f"{phase}:{worker_exit}" if phase != "completed" or worker_exit else
                "missing_or_invalid_report_entry"))
            try:
                self.attempts.record_outcome(
                    row["idea_id"], token=row["claim_token"], outcome=outcome,
                    reason=reason, evidence_ref=evidence_ref)
            except (ClaimTokenMismatch, sqlite3.Error) as exc:
                write_errors.append({"idea_id": row["idea_id"], "error": str(exc)})
        return self.summary(phase=phase, write_errors=write_errors)

    def summary(self, *, phase: str, write_errors: list[dict[str, Any]] | None = None,
                ) -> dict[str, Any]:
        rows = self.rows()
        errors = sum(row["outcome"] in {"run_error", "abandoned", "integrity_fail"}
                     for row in rows)
        unfinished = sum(row["outcome"] is None for row in rows)
        invalid = sum(row["outcome"] == "run_error" and row["reason"] in {
                          "duplicate_report_entry", "invalid_report_outcome",
                          "invalid_report_reason", "missing_or_invalid_report_entry"}
                      for row in rows)
        metadata = self._metadata()
        cost_blocked = metadata["request"]["limits"]["max_cost"] is not None
        # A running response is an acknowledgement, not a successful terminal result.
        terminal_phase = phase in {"completed", "pool_empty", "controller_restart"}
        good = not cost_blocked and (
            phase == "running" or (terminal_phase and not errors and not unfinished))
        return {"ok": good and not write_errors, "research_cycle_id": self.cycle_id,
                "phase": phase, "attempts_total": len(rows), "error_count": errors,
                "invalid_count": invalid, "ok_count": len(rows) - unfinished - errors,
                "unfinished_count": unfinished, "terminal_count": len(rows) - unfinished,
                "monetary_cost": None, "cost_status": "unknown", "cost_gate_passed": False,
                "write_errors": write_errors or [],
                "campaign": metadata["request"].get("campaign"),
                "attempts": [{"evidence_id": f"idea_attempts:{row['id']}",
                              **{k: row[k] for k in (
                                  "idea_id", "outcome", "reason", "evidence_ref")}}
                             for row in rows]}
