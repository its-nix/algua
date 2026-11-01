from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import date

from algua.data.models import SnapshotMetadata
from algua.data.research_provenance import (
    RESEARCH_PROVENANCE_KEY,
    ProvenanceDeclaration,
    ResearchProvenanceError,
    build_envelope,
    encode_envelope,
)
from algua.provenance.snapshot import (
    validate_declared_manifest_record as validate_declared_manifest_record,
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
    metadata_start = date.fromisoformat(metadata.start)
    metadata_end = date.fromisoformat(metadata.end)
    coverage_start = date.fromisoformat(observed_start)
    coverage_end = date.fromisoformat(observed_end)
    if exact_window:
        coverage_ok = metadata_start == coverage_start and metadata_end == coverage_end
    else:
        coverage_ok = metadata_start <= coverage_start and coverage_end < metadata_end
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
