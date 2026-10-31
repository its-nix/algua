"""Exact-manifest provenance evidence for the opt-in strategy board."""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from algua.data.board_provenance import SnapshotProvenanceReader
from algua.data.manifest import SnapshotManifest
from algua.data.research_provenance import (
    RESEARCH_PROVENANCE_KEY,
    DataTier,
    ProvenanceDeclaration,
    ResearchProvenance,
    encode_envelope,
)
from algua.data.store import DataStore
from algua.data.store.identity import compute_snapshot_id
from tests.test_research_provenance import _bars, _declaration, _ingest


def _reader(tmp_path) -> tuple[DataStore, SnapshotProvenanceReader]:
    store = DataStore(tmp_path / "data")
    return store, SnapshotProvenanceReader(store.manifest)


def test_reader_returns_only_the_typed_bound_exact_snapshot_allowlist(tmp_path) -> None:
    store, reader = _reader(tmp_path)
    rec = _ingest(store)

    assert reader.resolve(rec.snapshot_id) == {
        "status": "VALID",
        "reason": None,
        "value": {
            "schema_version": "pilot-provenance/v1",
            "data_tier": "pilot_real_proxy",
            "universe_method": "dated-candidate-proxy/v1",
            "limitations": [
                "adjusted_close_vendor_revisable",
                "corporate_actions_unverified",
                "delisted_names_absent",
                "event_timing_unavailable",
                "historical_market_cap_unavailable",
                "point_in_time_universe_unavailable",
                "survivorship_biased_selection",
            ],
            "coverage_start": "2026-01-02",
            "coverage_end": "2026-01-05",
            "provider": "yfinance",
        },
    }


def test_reader_never_infers_provenance_from_provider_or_a_newer_snapshot(tmp_path) -> None:
    store, reader = _reader(tmp_path)
    unlabeled = _ingest(store, provenance=None)
    _ingest(store)  # a newer labeled record must not become fallback evidence

    assert reader.resolve(unlabeled.snapshot_id) == {
        "status": "UNAVAILABLE",
        "reason": "provenance_absent",
        "value": None,
    }
    assert reader.resolve("missing-exact-id") == {
        "status": "UNAVAILABLE",
        "reason": "snapshot_not_found",
        "value": None,
    }


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("not-json", "malformed_provenance"),
        ("unknown-schema", "unsupported_provenance_schema"),
    ],
)
def test_present_malformed_or_unknown_provenance_is_invalid(tmp_path, raw, reason) -> None:
    store, _reader_unused = _reader(tmp_path)
    rec = _ingest(store)
    payload = rec.to_dict()
    if raw == "unknown-schema":
        raw = payload["source_metadata"][RESEARCH_PROVENANCE_KEY].replace(
            "pilot-provenance/v1", "pilot-provenance/v2"
        )
    payload["source_metadata"][RESEARCH_PROVENANCE_KEY] = raw
    manifest = tmp_path / f"{reason}.jsonl"
    manifest.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    assert SnapshotProvenanceReader(SnapshotManifest(manifest)).resolve(rec.snapshot_id) == {
        "status": "INVALID",
        "reason": reason,
        "value": None,
    }


def test_reader_revalidates_snapshot_identity_binding(tmp_path) -> None:
    store, _reader_unused = _reader(tmp_path)
    rec = _ingest(store)
    payload = rec.to_dict()
    payload["content_hash"] = "forged"
    manifest = tmp_path / "forged.jsonl"
    manifest.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    assert SnapshotProvenanceReader(SnapshotManifest(manifest)).resolve(rec.snapshot_id) == {
        "status": "INVALID",
        "reason": "snapshot_binding_mismatch",
        "value": None,
    }


def test_readable_verified_pit_is_not_certified_without_a_verifier(tmp_path) -> None:
    store, _reader_unused = _reader(tmp_path)
    rec = _ingest(store)
    verified = ResearchProvenance(
        data_tier=DataTier.VERIFIED_PIT,
        universe_method="verified/v1",
        limitations=(),
        coverage_start="2026-01-02",
        coverage_end="2026-01-05",
        provider="yfinance",
    )
    source_metadata = dict(rec.metadata.source_metadata or {})
    source_metadata[RESEARCH_PROVENANCE_KEY] = encode_envelope(verified)
    metadata = replace(rec.metadata, source_metadata=source_metadata)
    snapshot_id = compute_snapshot_id(metadata, rec.content_hash)
    payload = replace(rec, snapshot_id=snapshot_id, metadata=metadata).to_dict()
    manifest = tmp_path / "verified.jsonl"
    manifest.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    assert SnapshotProvenanceReader(SnapshotManifest(manifest)).resolve(snapshot_id) == {
        "status": "INVALID",
        "reason": "pit_verifier_unavailable",
        "value": None,
    }


def test_reader_validates_the_existing_streamed_metadata_binding(tmp_path) -> None:
    store, reader = _reader(tmp_path)
    rec = store.ingest_bars_streamed(
        provider="fixture",
        symbols=["AAPL", "MSFT"],
        as_of="2026-01-07T00:00:00+00:00",
        source="fixture",
        chunks=[_bars()],
        provenance=_declaration(),
    )

    evidence = reader.resolve(rec.snapshot_id)

    assert evidence["status"] == "VALID"
    assert evidence["value"]["coverage_start"] == rec.start
    assert evidence["value"]["coverage_end"] == rec.end


def test_reader_bounds_source_failures_and_conflicting_exact_records(tmp_path) -> None:
    unavailable = SnapshotProvenanceReader(SnapshotManifest(tmp_path))
    assert unavailable.resolve("anything") == {
        "status": "UNAVAILABLE",
        "reason": "source_unavailable",
        "value": None,
    }

    store, _reader_unused = _reader(tmp_path / "store")
    rec = _ingest(store)
    first = rec.to_dict()
    conflict = {**first, "content_hash": "different"}
    manifest = tmp_path / "conflicting.jsonl"
    manifest.write_text(
        json.dumps(first) + "\n" + json.dumps(conflict) + "\n", encoding="utf-8"
    )
    assert SnapshotProvenanceReader(SnapshotManifest(manifest)).resolve(rec.snapshot_id) == {
        "status": "INVALID",
        "reason": "conflicting_snapshot_records",
        "value": None,
    }


def test_exact_non_string_envelope_is_invalid_not_source_unavailable(tmp_path) -> None:
    store, _reader_unused = _reader(tmp_path / "store")
    rec = _ingest(store)
    payload = rec.to_dict()
    payload["source_metadata"][RESEARCH_PROVENANCE_KEY] = {"not": "a string"}
    manifest = tmp_path / "non-string.jsonl"
    manifest.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    assert SnapshotProvenanceReader(SnapshotManifest(manifest)).resolve(rec.snapshot_id) == {
        "status": "INVALID",
        "reason": "malformed_provenance",
        "value": None,
    }


@pytest.mark.parametrize("source_metadata", [None, []])
def test_exact_null_or_list_source_metadata_is_bounded_malformed_provenance(
    tmp_path, source_metadata
) -> None:
    store, _reader_unused = _reader(tmp_path / "store")
    rec = _ingest(store)
    payload = rec.to_dict()
    payload["source_metadata"] = source_metadata
    manifest = tmp_path / "bad-source-metadata.jsonl"
    manifest.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    assert SnapshotProvenanceReader(SnapshotManifest(manifest)).resolve(rec.snapshot_id) == {
        "status": "INVALID",
        "reason": "malformed_provenance",
        "value": None,
    }


def test_malformed_exact_metadata_date_is_bounded_binding_mismatch(tmp_path) -> None:
    store, _reader_unused = _reader(tmp_path / "store")
    rec = _ingest(store)
    payload = rec.to_dict()
    payload["start"] = "not-a-date"
    manifest = tmp_path / "bad-date.jsonl"
    manifest.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    assert SnapshotProvenanceReader(SnapshotManifest(manifest)).resolve(rec.snapshot_id) == {
        "status": "INVALID",
        "reason": "snapshot_binding_mismatch",
        "value": None,
    }


def test_malformed_unrelated_record_does_not_poison_valid_exact_record(tmp_path) -> None:
    store, _reader_unused = _reader(tmp_path / "store")
    valid = _ingest(store)
    valid_payload = valid.to_dict()
    unrelated = deepcopy(valid_payload)
    unrelated["snapshot_id"] = "unrelated"
    unrelated["source_metadata"][RESEARCH_PROVENANCE_KEY] = ["malformed"]
    manifest = tmp_path / "isolated.jsonl"
    manifest.write_text(
        json.dumps(unrelated) + "\n" + json.dumps(valid_payload) + "\n",
        encoding="utf-8",
    )

    evidence = SnapshotProvenanceReader(SnapshotManifest(manifest)).resolve(valid.snapshot_id)

    assert evidence["status"] == "VALID"
    assert evidence["value"]["provider"] == "yfinance"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("dataset", "universes"),
        ("kind", "file"),
        ("storage_format", "file"),
        ("provider", "other-provider"),
        ("start", "2026-01-03"),
        ("content_hash", "identity-mismatch"),
    ],
)
def test_wrong_exact_record_binding_is_invalid(tmp_path, field, value) -> None:
    store, _reader_unused = _reader(tmp_path / "store")
    rec = _ingest(store)
    payload = rec.to_dict()
    payload[field] = value
    manifest = tmp_path / f"wrong-{field}.jsonl"
    manifest.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    assert SnapshotProvenanceReader(SnapshotManifest(manifest)).resolve(rec.snapshot_id) == {
        "status": "INVALID",
        "reason": "snapshot_binding_mismatch",
        "value": None,
    }


def test_direct_synthetic_manifest_retains_test_only_limitation(tmp_path) -> None:
    store, reader = _reader(tmp_path)
    rec = _ingest(
        store,
        provider="fixture",
        provenance=ProvenanceDeclaration(
            data_tier=DataTier.SYNTHETIC_FIXTURE,
            universe_method="fixture/v1",
            limitations=("synthetic_not_market_data",),
        ),
    )

    evidence = reader.resolve(rec.snapshot_id)

    assert evidence["status"] == "VALID"
    assert evidence["value"]["data_tier"] == "synthetic_fixture"
    assert evidence["value"]["limitations"] == ["synthetic_not_market_data"]


def test_reader_loads_manifest_once_without_reading_payload_or_writing(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, reader = _reader(tmp_path)
    first = _ingest(store)
    second = _ingest(store, provenance=_declaration("dated-candidate-proxy/v2"))
    manifest_before = store.manifest.path.read_bytes()
    read_paths: list[Path] = []
    original_read_bytes = Path.read_bytes

    def tracked_read_bytes(path: Path) -> bytes:
        read_paths.append(path)
        if path != store.manifest.path:
            raise AssertionError(f"reader touched snapshot payload: {path}")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", tracked_read_bytes)

    assert reader.resolve(first.snapshot_id)["status"] == "VALID"
    assert reader.resolve(second.snapshot_id)["status"] == "VALID"
    assert read_paths == [store.manifest.path]
    assert original_read_bytes(store.manifest.path) == manifest_before


def test_committed_malformed_json_is_bounded_whole_source_failure(tmp_path) -> None:
    manifest = tmp_path / "malformed-json.jsonl"
    manifest.write_text('{"snapshot_id":"wanted"\n', encoding="utf-8")

    assert SnapshotProvenanceReader(SnapshotManifest(manifest)).resolve("wanted") == {
        "status": "UNAVAILABLE",
        "reason": "source_unavailable",
        "value": None,
    }


def test_reader_does_not_swallow_unexpected_runtime_errors(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text("", encoding="utf-8")

    def bug(_path: Path) -> bytes:
        raise RuntimeError("unexpected reader bug")

    monkeypatch.setattr(Path, "read_bytes", bug)

    with pytest.raises(RuntimeError, match="unexpected reader bug"):
        SnapshotProvenanceReader(SnapshotManifest(manifest)).resolve("wanted")
