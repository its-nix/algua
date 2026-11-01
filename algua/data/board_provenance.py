"""Bounded, exact-snapshot provenance read model for the strategy board."""
from __future__ import annotations

import json
from typing import Any

from algua.data.manifest import SnapshotManifest
from algua.data.models import SnapshotRecord
from algua.data.provenance_binding import validate_declared_manifest_record
from algua.data.research_provenance import (
    RESEARCH_PROVENANCE_KEY,
    SCHEMA_VERSION,
    DataTier,
    ResearchProvenanceError,
    decode_research_provenance,
)

__all__ = ["SnapshotProvenanceReader"]


def _wrapper(status: str, reason: str | None, value: dict[str, Any] | None) -> dict[str, Any]:
    return {"status": status, "reason": reason, "value": value}


class SnapshotProvenanceReader:
    """Resolve only an exact run-bound manifest ID; never infer a provider or newer snapshot."""

    def __init__(self, manifest: SnapshotManifest) -> None:
        self._manifest = manifest
        self._loaded = False
        self._source_unavailable = False
        self._payloads: list[dict[str, Any]] = []

    def resolve(self, snapshot_id: str) -> dict[str, Any]:
        self._load_payloads()
        if self._source_unavailable:
            return _wrapper("UNAVAILABLE", "source_unavailable", None)
        matches = [
            payload
            for payload in self._payloads
            if payload.get("snapshot_id") == snapshot_id
        ]
        if not matches:
            return _wrapper("UNAVAILABLE", "snapshot_not_found", None)
        if self._conflicting(matches):
            return _wrapper("INVALID", "conflicting_snapshot_records", None)
        payload = matches[0]
        raw_source_metadata = payload.get("source_metadata", {})
        if not isinstance(raw_source_metadata, dict):
            return _wrapper("INVALID", "malformed_provenance", None)
        if (
            RESEARCH_PROVENANCE_KEY in raw_source_metadata
            and not isinstance(raw_source_metadata[RESEARCH_PROVENANCE_KEY], str)
        ):
            return _wrapper("INVALID", "malformed_provenance", None)
        try:
            record = SnapshotRecord.from_dict(payload)
        except ResearchProvenanceError:
            return _wrapper("INVALID", "malformed_provenance", None)
        except (KeyError, TypeError, ValueError):
            return _wrapper("INVALID", "snapshot_binding_mismatch", None)
        source_metadata = record.metadata.source_metadata or {}
        if RESEARCH_PROVENANCE_KEY not in source_metadata:
            return _wrapper("UNAVAILABLE", "provenance_absent", None)
        try:
            value = decode_research_provenance(source_metadata)
        except ResearchProvenanceError as exc:
            reason = (
                "unsupported_provenance_schema"
                if exc.reason == "research_provenance_unknown_schema"
                else "malformed_provenance"
            )
            return _wrapper("INVALID", reason, None)
        if value is None:  # guarded above; keeps the atomic state explicit for type checkers
            return _wrapper("UNAVAILABLE", "provenance_absent", None)
        try:
            validate_declared_manifest_record(record)
        except ResearchProvenanceError as exc:
            if exc.reason == "verified_pit_evidence_required":
                return _wrapper("INVALID", "pit_verifier_unavailable", None)
            return _wrapper("INVALID", "snapshot_binding_mismatch", None)
        except ValueError:
            return _wrapper("INVALID", "snapshot_binding_mismatch", None)
        if value.data_tier is DataTier.VERIFIED_PIT:
            return _wrapper("INVALID", "pit_verifier_unavailable", None)
        return _wrapper(
            "VALID",
            None,
            {
                "schema_version": SCHEMA_VERSION,
                "data_tier": value.data_tier.value,
                "universe_method": value.universe_method,
                "limitations": list(value.limitations),
                "coverage_start": value.coverage_start,
                "coverage_end": value.coverage_end,
                "provider": value.provider,
            },
        )

    def _load_payloads(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            raw = self._manifest.path.read_bytes() if self._manifest.path.exists() else b""
            committed = SnapshotManifest._committed_prefix(raw).decode("utf-8")
            for line in committed.split("\n"):
                if not line.strip():
                    continue
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    self._source_unavailable = True
                    self._payloads.clear()
                    return
                self._payloads.append(payload)
        except (OSError, UnicodeError, json.JSONDecodeError):
            self._source_unavailable = True
            self._payloads.clear()

    @staticmethod
    def _conflicting(payloads: list[dict[str, Any]]) -> bool:
        first = payloads[0]
        return any(payload != first for payload in payloads[1:])
