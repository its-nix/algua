"""Fixed trusted batch reader. No strategy execution, settings reads or model operations."""
from __future__ import annotations

import hashlib
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

from algua.operator.campaign_memory_schema import (
    LEGACY_SELECTION_PROTOCOL,
    SELECTION_PROTOCOLS,
    VIEW_FIELDS,
    MemoryContextError,
    context_limit,
    exact,
    integer,
    require,
    validate_payload,
    validate_snapshot,
    window_protocol,
)
from algua.operator.research_memory_checkpoint import (
    MAX_CHECKPOINT_BYTES,
    CheckpointError,
    canonical,
    load_checkpoint,
    strict_json,
    validate_retained_payload,
)
from algua.operator.research_memory_inputs import context_input_limit
from algua.tracking.bounded_local_read import ReadBudget
from algua.tracking.research_archive import ArchiveReadError, LocalResearchArchive
from algua.tracking.uri import sqlite_tracking_uri


def normalized_store(uri: str) -> str:
    uri = sqlite_tracking_uri(uri)
    require(uri.startswith("sqlite:///") and uri[10:] not in ("", ":memory:")
            and not any(c in uri[10:] for c in "?#"), "archive_store_unavailable")
    return "sqlite:///" + str(Path(uri[10:]).resolve())


class _Projection:
    """Keep only a detached bounded prefix while each verified full archive is in scope."""

    def __init__(self, selection_protocol: str) -> None:
        self.window_records = window_protocol(selection_protocol)
        self.context_bytes = context_limit(selection_protocol)
        self.receipts: list[dict] = []
        self.observations: list[dict] = []
        self.truncations: list[dict] = []
        self.total_markers = self.retained = self.omitted_inputs = 0
        self.omitted_count = self.omitted_context = 0
        self.slots = 24
        self.prefix_closed = False

    def add(self, item: dict) -> None:
        receipt, payload = item["receipt"], item["payload"]
        cycle_id = receipt["research_cycle_id"]
        validate_payload(payload, cycle_id)
        self.receipts.append({"research_cycle_id": cycle_id,
            "evidence_ref": receipt["reference"], "archive_sha256": receipt["sha256"],
            "attempt_evidence_ids": sorted((r["evidence_id"] for r in payload["attempt_refs"]),
                key=lambda ref: int(ref.rsplit(":", 1)[1]))})
        self.retained += len(payload["evaluations"])
        def priority(row: dict) -> tuple:
            window = row["kind"] in {"walk_forward", "sweep_trial"} \
                and "public_window_record" in row["inputs"]
            return (self.window_records and not window, row["source_run_id"])

        for row in sorted(payload["evaluations"], key=priority):
            if len(canonical(row["inputs"])) > context_input_limit(
                    row["kind"], row["inputs"], window_records=self.window_records):
                self.omitted_inputs += 1
                continue
            if not self.slots:
                self.omitted_count += 1
                continue
            self.slots -= 1
            if self.prefix_closed:
                self.omitted_context += 1
                continue
            view = {k: row[k] for k in VIEW_FIELDS if k != "archive_ref"}
            raw = canonical(view | {"archive_ref": receipt["reference"]})
            if len(raw) > self.context_bytes:
                # This record and every later candidate must leave via tail trimming; no backfill.
                self.prefix_closed = True
                self.omitted_context += 1
            else:
                self.observations.append(strict_json(raw))
        included = {r["source_ref"] for r in self.observations if r["kind"] == "sweep"}
        self.total_markers += len(payload["coverage"]["truncated_sweeps"])
        self.truncations.extend(dict(m) for m in payload["coverage"]["truncated_sweeps"]
                                if m["source_ref"] in included)

    def finish(self, coverage: dict, cutoff: int, tracking_uri: str,
               selection_protocol: str = LEGACY_SELECTION_PROTOCOL) -> dict:
        counts = {**coverage, "selected_cycles": len(self.receipts),
            "retained_public_observations": self.retained,
            "omitted_for_input_bytes": self.omitted_inputs,
            "omitted_for_count": self.omitted_count,
            "omitted_for_context_bytes": self.omitted_context,
            "unrecorded_variant_failures": "UNKNOWN", "evaluated_worktree_verified": False}
        snapshot = {"schema_version": "campaign-public-memory/v1", "status": "unavailable",
            "evidence_mode": "UNVERIFIED_WORKER", "authority": "none", "association": "cycle_only",
            "scorecard_attempt_cutoff": cutoff,
            "archive_store_sha256": hashlib.sha256(
                normalized_store(tracking_uri).encode()).hexdigest(),
            "selection_protocol": selection_protocol, "receipts": self.receipts,
            "observations": self.observations, "coverage": counts}
        while True:
            included = {r["source_ref"] for r in self.observations if r["kind"] == "sweep"}
            markers = [m for m in self.truncations if m["source_ref"] in included]
            counts.update(included_observations=len(self.observations),
                omitted_observations=self.retained - len(self.observations),
                truncated_sweeps=markers,
                omitted_truncation_markers=self.total_markers - len(markers))
            snapshot["status"] = "available" if self.observations else "unavailable"
            if len(canonical(snapshot)) <= self.context_bytes:
                return validate_snapshot(snapshot)
            require(self.observations, "context_bytes_exceeded")
            self.observations.pop()
            counts["omitted_for_context_bytes"] += 1


def project_snapshot(items: Iterable[dict], *, coverage: dict, cutoff: int,
                     tracking_uri: str, selection_protocol: str = LEGACY_SELECTION_PROTOCOL,
                     ) -> dict:
    projection = _Projection(selection_protocol)
    for item in items:
        projection.add(item)
        del item  # Release the previous full payload before advancing a producer to its next read.
    return projection.finish(coverage, cutoff, tracking_uri, selection_protocol)


def _verified_items(request: dict) -> Iterator[dict]:
    archive_budget = ReadBudget(32 * 1024 * 1024)
    checkpoint_budget = ReadBudget(2 * MAX_CHECKPOINT_BYTES)
    archive = None
    for cycle in request["cycles"]:
        require(exact(cycle, {"research_cycle_id", "evidence_ref", "attempts"}), "request_invalid")
        require(isinstance(cycle["research_cycle_id"], str)
                and isinstance(cycle["evidence_ref"], str)
                and isinstance(cycle["attempts"], list) and len(cycle["attempts"]) <= 40,
                "request_invalid")
        metadata = load_checkpoint(Path(request["cycle_directory"]), cycle["research_cycle_id"],
                                   database=request["database"], budget=checkpoint_budget)
        receipt = metadata["research_memory"]["receipt"]
        require(receipt.get("reference") == cycle["evidence_ref"], "receipt_invalid")
        if archive is None:
            archive = LocalResearchArchive(request["tracking_uri"],
                backend=request["tracking_backend"], existing_only=True)
        payload = archive.read(receipt, budget=archive_budget)
        try:
            validate_retained_payload(payload, metadata=metadata,
                                      cycle_id=cycle["research_cycle_id"])
        except (ValueError, KeyError, TypeError) as exc:
            raise MemoryContextError("checkpoint_invalid") from exc
        validate_payload(payload, cycle["research_cycle_id"])
        for attempt in cycle["attempts"]:
            require(exact(attempt, {"evidence_id", "idea_id"})
                    and attempt in payload["attempt_refs"], "artifact_payload_invalid")
        yield {"receipt": receipt, "payload": payload}
        del payload, metadata


def read_batch(request: dict) -> dict:
    fields = {"schema_version", "phase", "database", "cycle_directory", "tracking_uri",
              "tracking_backend", "cutoff", "cycles", "coverage"}
    require(exact(request, fields) or exact(request, fields | {"selection_protocol"}),
            "request_invalid")
    protocol = request.get("selection_protocol", LEGACY_SELECTION_PROTOCOL)
    require(isinstance(protocol, str) and protocol in SELECTION_PROTOCOLS, "request_invalid")
    require(request["schema_version"] == "campaign-public-memory-request/v1"
            and request["phase"] in ("capture", "revalidate") and integer(request["cutoff"]),
            "request_invalid")
    require(all(isinstance(request[k], str) for k in (
        "database", "cycle_directory", "tracking_uri", "tracking_backend")), "request_invalid")
    require(request["tracking_backend"] == "mlflow-sqlite", "archive_store_unavailable")
    cycles = request["cycles"]
    require(isinstance(cycles, list) and len(cycles) <= 2, "request_invalid")
    coverage = request["coverage"]
    require(exact(coverage, {"candidate_attempts_considered", "candidate_cycles",
                           "cycles_without_receipt"}) and all(integer(v) for v in coverage.values())
            and coverage["candidate_attempts_considered"] <= 64, "request_invalid")
    return project_snapshot(_verified_items(request), coverage=coverage, cutoff=request["cutoff"],
                            tracking_uri=request["tracking_uri"], selection_protocol=protocol)


def main() -> None:
    try:
        require(len(sys.argv) == 2 and len(sys.argv[1].encode()) <= 64 * 1024, "request_invalid")
        request = strict_json(sys.argv[1])
        result = {"schema_version": "campaign-public-memory-result/v1", "ok": True,
                  "snapshot": read_batch(request)}
    except (MemoryContextError, ArchiveReadError, CheckpointError) as exc:
        result = {"schema_version": "campaign-public-memory-result/v1", "ok": False,
                  "reason": exc.reason}
    except (ValueError, TypeError, KeyError, OSError, OverflowError, RecursionError):
        result = {"schema_version": "campaign-public-memory-result/v1", "ok": False,
                  "reason": "worker_result_invalid"}
    sys.stdout.buffer.write(canonical(result))


if __name__ == "__main__":
    main()
