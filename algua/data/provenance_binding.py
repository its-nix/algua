from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import date

from algua.data.files import BARS_STREAMED_HASH_ALGO
from algua.data.models import Dataset, Kind, SnapshotMetadata, SnapshotRecord
from algua.data.research_provenance import (
    RESEARCH_PROVENANCE_KEY,
    DataTier,
    ProvenanceDeclaration,
    ResearchProvenanceError,
    build_envelope,
    encode_envelope,
    parse_envelope,
)


def refuse_reserved_key(source_metadata: Mapping[str, object] | None) -> None:
    if RESEARCH_PROVENANCE_KEY in (source_metadata or {}):
        raise ResearchProvenanceError(
            "research_provenance_reserved_key",
            f"{RESEARCH_PROVENANCE_KEY!r} may only be set by a typed declaration",
        )


def attach_declared_provenance(
    metadata: SnapshotMetadata,
    declaration: ProvenanceDeclaration,
    *,
    observed_start: str,
    observed_end: str,
    observed_symbols: set[str],
    exact_window: bool = False,
) -> SnapshotMetadata:
    if not observed_symbols:
        raise ResearchProvenanceError(
            "research_provenance_empty_bars", "declared snapshots require at least one bar"
        )
    if observed_symbols != set(metadata.symbols):
        raise ResearchProvenanceError(
            "research_provenance_symbol_mismatch",
            f"observed {sorted(observed_symbols)!r}, requested {list(metadata.symbols)!r}",
        )
    if exact_window:
        coverage_ok = metadata.start == observed_start and metadata.end == observed_end
    else:
        coverage_ok = metadata.start <= observed_start and observed_end < metadata.end
    if not coverage_ok:
        raise ResearchProvenanceError(
            "research_provenance_coverage_mismatch", "observed bars fall outside the declaration"
        )
    envelope = build_envelope(
        declaration,
        provider=metadata.provider,
        coverage_start=observed_start,
        coverage_end=observed_end,
    )
    source_metadata = dict(metadata.source_metadata or {})
    source_metadata[RESEARCH_PROVENANCE_KEY] = encode_envelope(envelope)
    return replace(metadata, source_metadata=source_metadata)


def validate_declared_manifest_record(rec: SnapshotRecord) -> None:
    source_metadata = rec.metadata.source_metadata or {}
    if RESEARCH_PROVENANCE_KEY not in source_metadata:
        return
    raw = source_metadata[RESEARCH_PROVENANCE_KEY]
    envelope = parse_envelope(raw)
    if envelope.data_tier is DataTier.VERIFIED_PIT:
        raise ResearchProvenanceError(
            "verified_pit_evidence_required", "no verified-PIT evidence verifier exists"
        )
    if (
        rec.dataset is not Dataset.BARS
        or rec.kind is not Kind.BARS
        or rec.storage_format != "parquet_dataset"
    ):
        raise ResearchProvenanceError(
            "research_provenance_unsupported_path", "provenance is supported only on bars datasets"
        )
    if envelope.provider != rec.provider:
        raise ResearchProvenanceError(
            "research_provenance_provider_mismatch", "envelope and metadata providers differ"
        )
    coverage_start = date.fromisoformat(envelope.coverage_start)
    coverage_end = date.fromisoformat(envelope.coverage_end)
    metadata_start = date.fromisoformat(rec.start)
    metadata_end = date.fromisoformat(rec.end)
    if source_metadata.get("content_hash_algorithm") == BARS_STREAMED_HASH_ALGO:
        coverage_ok = metadata_start == coverage_start and metadata_end == coverage_end
    else:
        coverage_ok = metadata_start <= coverage_start and coverage_end < metadata_end
    if not coverage_ok:
        raise ResearchProvenanceError(
            "research_provenance_coverage_mismatch", "envelope and metadata coverage differ"
        )
    from algua.data.store.identity import compute_snapshot_id

    if compute_snapshot_id(rec.metadata, rec.content_hash) != rec.snapshot_id:
        raise ResearchProvenanceError(
            "research_provenance_id_mismatch", "record identity does not bind its metadata"
        )
