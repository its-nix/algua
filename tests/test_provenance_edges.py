"""Adversarial self-verification for the admitted ingest-only provenance slice."""
from __future__ import annotations

import json
from dataclasses import replace

import pandas as pd
import pytest

from algua.data.files import BARS_STREAMED_HASH_ALGO
from algua.data.manifest import SnapshotManifest
from algua.data.models import Dataset, Kind, SnapshotMetadata
from algua.data.provenance_binding import attach_declared_provenance
from algua.data.refresh import _reusable
from algua.data.research_provenance import (
    DataTier,
    ResearchProvenanceError,
    decode_research_provenance,
    encode_envelope,
    parse_envelope,
)
from algua.data.store import DataStore
from tests.test_research_provenance import _bars, _declaration, _ingest


def _valid_payload(tmp_path):
    rec = _ingest(DataStore(tmp_path / "source"))
    return json.loads(rec.metadata.source_metadata["research_provenance"])


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("data_tier", "unknown"), ("data_tier", True),
        ("universe_method", "contains spaces"), ("universe_method", None),
        ("provider", "contains spaces"), ("provider", 1),
        ("coverage_start", "20260102"), ("coverage_start", "2026-01-06"),
        ("coverage_end", None), ("coverage_end", "2026-02-30"),
        ("limitations", []), ("limitations", ["unknown"]),
        ("limitations", [True]), ("schema_version", "pilot-provenance/v2"),
    ],
)
def test_present_invalid_fields_never_become_legacy(tmp_path, field, bad):
    payload = _valid_payload(tmp_path)
    payload[field] = bad
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    with pytest.raises(ResearchProvenanceError):
        decode_research_provenance({"research_provenance": raw})


@pytest.mark.parametrize("raw", [None, 1, True, {}, [], "x" * 4097])
def test_raw_invalid_values_fail_closed(raw):
    with pytest.raises(ResearchProvenanceError):
        parse_envelope(raw)


def test_full_envelope_rejects_duplicate_unknown_missing_and_noncanonical(tmp_path):
    payload = _valid_payload(tmp_path)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    candidates = [
        canonical.replace('{', '{"provider":"forged",', 1),
        json.dumps({**payload, "snapshot_id": "forbidden"}, sort_keys=True, separators=(",", ":")),
        json.dumps({k: v for k, v in payload.items() if k != "provider"}),
        json.dumps(payload, indent=2),
    ]
    for raw in candidates:
        with pytest.raises(ResearchProvenanceError):
            parse_envelope(raw)


def test_legacy_snapshot_reads_unknown_and_relabel_leaves_old_line_exact(tmp_path):
    store = DataStore(tmp_path / "data")
    legacy = _ingest(store, provenance=None)
    original_bytes = store.manifest.path.read_bytes()
    assert decode_research_provenance(legacy.metadata.source_metadata) is None
    assert store.get_snapshot(legacy.snapshot_id) == legacy
    declared = _ingest(store)
    assert declared.snapshot_id != legacy.snapshot_id
    assert declared.content_hash == legacy.content_hash
    assert store.manifest.path.read_bytes().startswith(original_bytes)
    assert _ingest(store) == declared
    assert len(store.list_snapshots()) == 2


def test_streamed_declaration_roundtrip_and_dedup(tmp_path):
    store = DataStore(tmp_path / "data")
    kwargs = dict(provider="yfinance", symbols=["AAPL", "MSFT"],
                  as_of="2026-01-07T00:00:00+00:00", source="pilot", provenance=_declaration())
    first = store.ingest_bars_streamed(chunks=[_bars()], **kwargs)
    again = store.ingest_bars_streamed(chunks=[_bars()], **kwargs)
    decoded = decode_research_provenance(first.metadata.source_metadata)
    assert first == again
    assert decoded.data_tier is DataTier.PILOT_REAL_PROXY
    assert (decoded.coverage_start, decoded.coverage_end) == ("2026-01-02", "2026-01-05")
    assert first.metadata.source_metadata["content_hash_algorithm"] == BARS_STREAMED_HASH_ALGO
    assert len(store.list_snapshots()) == 1


def test_half_open_declaration_accepts_equivalent_basic_date_bounds(tmp_path):
    store = DataStore(tmp_path / "data")

    rec = _ingest(store, start="20260101", end="20260106")

    assert (rec.start, rec.end) == ("20260101", "20260106")
    decoded = decode_research_provenance(rec.metadata.source_metadata)
    assert (decoded.coverage_start, decoded.coverage_end) == ("2026-01-02", "2026-01-05")


def test_streamed_exact_window_compares_iso_dates_without_changing_identity_fields():
    metadata = SnapshotMetadata(
        dataset=Dataset.BARS,
        provider="yfinance",
        symbols=("AAPL", "MSFT"),
        start="2026-W01-5",
        end="20260105",
        as_of="2026-01-07T00:00:00+00:00",
        source="pilot",
        kind=Kind.BARS,
    )

    attached = attach_declared_provenance(
        metadata,
        _declaration(),
        observed_start="2026-01-02",
        observed_end="2026-01-05",
        observed_symbols={"AAPL", "MSFT"},
        exact_window=True,
    )

    assert (attached.start, attached.end) == ("2026-W01-5", "20260105")
    with pytest.raises(
        ResearchProvenanceError, match="research_provenance_coverage_mismatch"
    ):
        attach_declared_provenance(
            replace(metadata, end="2026-W02-2"),
            _declaration(),
            observed_start="2026-01-02",
            observed_end="2026-01-05",
            observed_symbols={"AAPL", "MSFT"},
            exact_window=True,
        )


def test_half_open_end_boundary_alias_is_rejected_before_publication(tmp_path):
    store = DataStore(tmp_path / "data")

    with pytest.raises(
        ResearchProvenanceError, match="research_provenance_coverage_mismatch"
    ):
        _ingest(store, end="20260105")

    assert not (store.data_dir / "snapshots").exists()
    assert not store.manifest.path.exists()


def test_manifest_refuses_verified_pit_and_mismatched_id_before_write(tmp_path):
    rec = _ingest(DataStore(tmp_path / "source"))
    manifest = SnapshotManifest(tmp_path / "target" / "manifest.jsonl")
    with pytest.raises(ResearchProvenanceError, match="research_provenance_id_mismatch"):
        manifest.append_if_absent(replace(rec, snapshot_id="forged"))
    value = decode_research_provenance(rec.metadata.source_metadata)
    pit_raw = encode_envelope(replace(value, data_tier=DataTier.VERIFIED_PIT, limitations=()))
    metadata = replace(rec.metadata, source_metadata={"research_provenance": pit_raw})
    with pytest.raises(ResearchProvenanceError, match="verified_pit_evidence_required"):
        manifest.append_if_absent(replace(rec, metadata=metadata))
    assert not manifest.path.exists()


def test_same_row_count_price_corruption_is_not_reusable(tmp_path):
    store = DataStore(tmp_path / "data")
    rec = _ingest(store)
    part = next((store.data_dir / rec.data_path).rglob("*.parquet"))
    frame = pd.read_parquet(part)
    frame.loc[frame.index[0], "close"] += 0.25
    frame.to_parquet(part, index=False)
    assert not _reusable(store, rec, ["AAPL", "MSFT"], "2026-01-05", {})
    # This checks the existing refresh hash wall, not data verify's row-count-only check.
