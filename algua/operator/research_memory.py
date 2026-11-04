"""Cycle-bound retention before disposable worker cleanup, without importing authority."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from algua.operator.research_cycle import ResearchCycle
from algua.operator.research_memory_checkpoint import (
    memory_state,
    validate_retained_payload,
    validated_seed,
)
from algua.operator.research_memory_projection import (
    MemoryLimits as MemoryLimits,
)
from algua.operator.research_memory_projection import (
    canonical_bytes,
    public_evaluations,
    seed_evidence,
)
from algua.operator.research_memory_retention import model_store_retention_reason
from algua.primitives.atomic_io import write_bytes_durable
from algua.tracking.research_archive import LocalResearchArchive


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


class ResearchMemory:
    """Append seed/receipt fields to the existing controller metadata under its lock.

    Call seed after the actual backup and before launching the worker. Call capture after the
    worker stops, before finalizing attempts, and pass its reference to the existing outcome API.
    All cleanup callers must revalidate cleanup_allowed immediately before removal, under their
    existing worker/queue serialization. This class neither deletes a worktree nor changes an
    attempt, economic result, strategy, gate, search count, model or approval.
    """

    def __init__(self, cycle: ResearchCycle, archive: LocalResearchArchive, *,
                 limits: MemoryLimits | None = None) -> None:
        self.cycle, self.archive = cycle, archive
        self.limits = limits or MemoryLimits()

    def _state(self) -> dict[str, Any]:
        return memory_state(self.cycle._metadata())

    def _append(self, key: str, value: dict[str, Any]) -> None:
        metadata = self.cycle._metadata()
        state = metadata.setdefault("research_memory", {})
        if not isinstance(state, dict):
            raise ValueError("research memory metadata is malformed")
        if key in state:
            if state[key] != value:
                raise ValueError("research memory checkpoints are immutable")
            return
        state[key] = value
        write_bytes_durable(canonical_bytes(metadata), self.cycle.path)

    def _seed(self, worker_root: Path | None = None) -> dict[str, Any]:
        return validated_seed(self._state().get("seed"), worker_root)

    def seed(self, worker_root: Path) -> dict[str, Any]:
        """Record the actual copied run watermark once; retries never advance it."""
        with self.cycle._locked():
            if "seed" in self._state():
                return self._seed(worker_root)
            seed = seed_evidence(worker_root, self.limits)
            self._append("seed", seed)
            return seed

    def _payload(self, worker_root: Path, *, worker_exit: int,
                 source_commit: str) -> dict[str, Any]:
        if any(path.resolve().is_relative_to(worker_root.resolve()) for path in (
            self.cycle.path, self.archive.database, self.archive.artifact_root,
        )):
            raise ValueError("research memory must survive outside the disposable worker")
        if type(worker_exit) is not int or not -255 <= worker_exit <= 255:
            raise ValueError("research memory requires the actual worker exit code")
        if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", source_commit) is None:
            raise ValueError("research memory requires the driver result commit")
        seed = self._seed(worker_root)
        evaluations, coverage = public_evaluations(worker_root, seed, self.cycle.cycle_id,
                                                   self.limits)
        payload = {
            "schema_version": "research-memory/v1", "research_cycle_id": self.cycle.cycle_id,
            "evidence_mode": "UNVERIFIED_WORKER", "authority": "none",
            "source_commit": source_commit, "worker_exit": worker_exit,
            "controller_context_digest": _digest(self.cycle._metadata()["request"]["context"]),
            "seed": {key: value for key, value in seed.items() if key != "worker_root"},
            "attempt_refs": [{"evidence_id": f"idea_attempts:{row['id']}",
                              "idea_id": row["idea_id"]} for row in self.cycle.rows()],
            "evaluations": evaluations,
            "coverage": {**coverage, "evaluated_worktree_verified": False},
        }
        if len(canonical_bytes(payload)) > self.limits.max_archive_bytes:
            raise ValueError("research memory artifact exceeds its byte bound")
        return payload

    def capture(self, worker_root: Path, *, worker_exit: int,
                source_commit: str) -> dict[str, Any]:
        """Retain, independently read back and append a receipt; failures leave source intact."""
        with self.cycle._locked():
            payload = self._payload(worker_root, worker_exit=worker_exit,
                                    source_commit=source_commit)
            existing = self._state().get("receipt")
            if existing is not None:
                if self.read() != payload:
                    raise ValueError("research memory cycle evidence changed after publication")
                return existing
            receipt = self.archive.publish(payload)
            if self.archive.read(receipt) != payload:
                raise ValueError("research memory archive readback differs from capture")
            self._append("receipt", receipt)
            return receipt

    def read(self) -> dict[str, Any]:
        receipt = self._state().get("receipt")
        if not isinstance(receipt, dict):
            raise ValueError("research memory has no verified archive receipt")
        payload = self.archive.read(receipt)
        return validate_retained_payload(payload, metadata=self.cycle._metadata(),
                                         cycle_id=self.cycle.cycle_id)

    def cleanup_retention_reason(self, worker_root: Path) -> str | None:
        """Verify public evidence, then retain model-bearing or uncertain workers."""
        try:
            with self.cycle._locked():
                payload = self.read()
                current = self._payload(worker_root, worker_exit=payload["worker_exit"],
                                        source_commit=payload["source_commit"])
                if payload != current:
                    return "evidence_unverified"
                if any(row["model_refs"] for row in current["evaluations"]):
                    return "model_references"
                return model_store_retention_reason(worker_root)
        except Exception:  # noqa: BLE001 — cleanup must retain the worktree on every uncertainty
            return "evidence_unverified"

    def cleanup_allowed(self, worker_root: Path) -> bool:
        """Keep the boolean cleanup API; model bytes are not yet durably retained."""
        return self.cleanup_retention_reason(worker_root) is None
