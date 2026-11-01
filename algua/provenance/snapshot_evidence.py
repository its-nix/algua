"""Pure projection shared by snapshot inspection, captured research inputs and run readback."""
from __future__ import annotations

from typing import Any

from algua.provenance.research import (
    RESEARCH_PROVENANCE_KEY,
    SCHEMA_VERSION,
    DataTier,
    ResearchProvenanceError,
    decode_research_provenance,
)
from algua.provenance.snapshot import SnapshotRecord, validate_declared_manifest_record


def _wrapper(status: str, reason: str | None, value: dict[str, Any] | None) -> dict[str, Any]:
    return {"status": status, "reason": reason, "value": value}


def project_snapshot_record(snapshot_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Same metadata/binding validation for manifest and detached run records."""
    if payload.get("snapshot_id") != snapshot_id:
        return _wrapper("INVALID", "snapshot_binding_mismatch", None)
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
