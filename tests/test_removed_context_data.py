"""Removing fundamentals/news ingestion must not strand manifest records already written."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from algua.data.models import Dataset, Kind, SnapshotRecord
from algua.data.store import DataStore
from algua.data.store.identity import build_metadata, compute_snapshot_id


def _write_manifest_record(store: DataStore, *, dataset: Dataset) -> SnapshotRecord:
    kind = Kind.FUNDAMENTALS if dataset == Dataset.FUNDAMENTALS else Kind.NEWS
    metadata = build_metadata(
        dataset=dataset,
        provider="legacy",
        symbols=["AAPL"],
        start="2024-01-01",
        end="2024-03-01",
        as_of="2024-03-02T00:00:00Z",
        source="legacy",
        kind=kind,
        source_metadata=None,
    )
    snapshot_id = compute_snapshot_id(metadata, "0" * 64)
    rec = SnapshotRecord(
        snapshot_id=snapshot_id,
        metadata=metadata,
        row_count=1,
        content_hash="0" * 64,
        data_path=Path("snapshots") / dataset.value / snapshot_id / "legacy.parquet",
        created_at=datetime.now(UTC).isoformat(),
        storage_format="parquet",
    )
    return store.manifest.append_if_absent(rec)


def test_manifest_with_fundamentals_record_still_lists(tmp_path):
    store = DataStore(tmp_path)
    _write_manifest_record(store, dataset=Dataset.FUNDAMENTALS)
    assert [r.metadata.dataset for r in store.manifest.list_records(Dataset.FUNDAMENTALS)] == [
        Dataset.FUNDAMENTALS
    ]


def test_manifest_with_news_record_still_lists(tmp_path):
    store = DataStore(tmp_path)
    _write_manifest_record(store, dataset=Dataset.NEWS)
    assert [r.metadata.dataset for r in store.manifest.list_records(Dataset.NEWS)] == [Dataset.NEWS]
