from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

from algua.provenance.research import (
    RESEARCH_PROVENANCE_KEY,
    DataTier,
    ResearchProvenanceError,
    parse_envelope,
)

SCHEMA_VERSION = 2


class Dataset(StrEnum):
    """Dataset routing key — the manifest `dataset` field and snapshot path component."""

    BARS = "bars"
    UNIVERSES = "universes"
    FUNDAMENTALS = "fundamentals"
    NEWS = "news"
    DELISTINGS = "delistings"


class Kind(StrEnum):
    """Snapshot `kind` — the provenance of a snapshot's payload."""

    BARS = "bars"
    UNIVERSE = "universe"
    FILE = "file"
    FUNDAMENTALS = "fundamentals"
    NEWS = "news"
    DELISTING = "delisting"


@dataclass(frozen=True)
class SnapshotMetadata:
    dataset: Dataset
    provider: str
    symbols: tuple[str, ...]
    start: str
    end: str
    as_of: str
    source: str
    kind: Kind = Kind.FILE
    timeframe: str | None = None
    adjustment: str | None = None
    universe: str | None = None
    source_metadata: dict[str, str] | None = None

    def __post_init__(self) -> None:
        # Construction backstop: every snapshot's dataset/kind is ALWAYS a valid enum member.
        # A raw/invalid string reaching the dataclass (a direct ingest call, untyped caller)
        # fails closed here with ValueError — which, because metadata is built before any
        # staging/publish side effect, prevents an orphan payload from a typo'd dataset.
        object.__setattr__(self, "dataset", Dataset(self.dataset))
        object.__setattr__(self, "kind", Kind(self.kind))


@dataclass(frozen=True)
class SnapshotRecord:
    snapshot_id: str
    metadata: SnapshotMetadata
    row_count: int | None
    content_hash: str
    data_path: Path
    created_at: str
    storage_format: str = "file"
    schema_version: int = SCHEMA_VERSION

    @property
    def dataset(self) -> Dataset:
        return self.metadata.dataset

    @property
    def provider(self) -> str:
        return self.metadata.provider

    @property
    def symbols(self) -> tuple[str, ...]:
        return self.metadata.symbols

    @property
    def start(self) -> str:
        return self.metadata.start

    @property
    def end(self) -> str:
        return self.metadata.end

    @property
    def as_of(self) -> str:
        return self.metadata.as_of

    @property
    def source(self) -> str:
        return self.metadata.source

    @property
    def kind(self) -> Kind:
        return self.metadata.kind

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "dataset": self.dataset.value,
            "provider": self.provider,
            "symbols": list(self.symbols),
            "start": self.start,
            "end": self.end,
            "as_of": self.as_of,
            "source": self.source,
            "kind": self.kind.value,
            "timeframe": self.metadata.timeframe,
            "adjustment": self.metadata.adjustment,
            "universe": self.metadata.universe,
            "source_metadata": self.metadata.source_metadata or {},
            "row_count": self.row_count,
            "content_hash": self.content_hash,
            "data_path": self.data_path.as_posix(),
            "storage_format": self.storage_format,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SnapshotRecord:
        row_count = payload["row_count"]
        raw_source_metadata = payload.get("source_metadata", {})
        if (
            RESEARCH_PROVENANCE_KEY in raw_source_metadata
            and not isinstance(raw_source_metadata[RESEARCH_PROVENANCE_KEY], str)
        ):
            raise ResearchProvenanceError(
                "research_provenance_malformed", "stored envelope must be a string"
            )
        metadata = SnapshotMetadata(
            dataset=Dataset(str(payload["dataset"])),
            provider=str(payload["provider"]),
            symbols=tuple(str(s) for s in payload["symbols"]),
            start=str(payload["start"]),
            end=str(payload["end"]),
            as_of=str(payload["as_of"]),
            source=str(payload["source"]),
            kind=Kind(str(payload.get("kind", Kind.FILE.value))),
            timeframe=_optional_str(payload.get("timeframe")),
            adjustment=_optional_str(payload.get("adjustment")),
            universe=_optional_str(payload.get("universe")),
            source_metadata={str(k): str(v) for k, v in raw_source_metadata.items()},
        )
        return cls(
            snapshot_id=str(payload["snapshot_id"]),
            metadata=metadata,
            row_count=None if row_count is None else int(row_count),
            content_hash=str(payload["content_hash"]),
            data_path=Path(str(payload["data_path"])),
            created_at=str(payload["created_at"]),
            storage_format=str(payload.get("storage_format", "file")),
            schema_version=int(payload["schema_version"]),
        )




def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


BARS_STREAMED_HASH_ALGO = "bars-symbol-merkle-v1"


def compute_snapshot_id(metadata: SnapshotMetadata, content_hash: str) -> str:
    payload: dict[str, Any] = {
        "dataset": metadata.dataset,
        "provider": metadata.provider,
        "symbols": list(metadata.symbols),
        "start": metadata.start,
        "end": metadata.end,
        "as_of": metadata.as_of,
        "source": metadata.source,
        "kind": metadata.kind,
        "timeframe": metadata.timeframe,
        "adjustment": metadata.adjustment,
        "universe": metadata.universe,
        "source_metadata": metadata.source_metadata or {},
        "content_hash": content_hash,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]



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
    if compute_snapshot_id(rec.metadata, rec.content_hash) != rec.snapshot_id:
        raise ResearchProvenanceError(
            "research_provenance_id_mismatch", "record identity does not bind its metadata"
        )
