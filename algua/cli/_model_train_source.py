"""Read-only capture of one declared, identity-checked local price vintage."""
from __future__ import annotations

import hashlib
import stat
import struct
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from algua.calendar.market_calendar import MarketCalendar
from algua.cli._model_train_request import TrainRequest, aware_utc
from algua.data.board_provenance import SnapshotProvenanceReader
from algua.data.files import compose_bars_symbol_hash, logical_bars_hash, sha256_file
from algua.data.store import DataStore
from algua.provenance.snapshot import BARS_STREAMED_HASH_ALGO, Dataset, compute_snapshot_id
from algua.provenance.snapshot_evidence import project_snapshot_record


def _inventory(root: Path) -> dict[str, tuple[int, ...]]:
    result: dict[str, tuple[int, ...]] = {}
    for count, path in enumerate(root.rglob("*"), 1):
        if count > 4096 or path.is_symlink():
            raise ValueError("unsupported snapshot inventory or symlink")
        info = path.stat()
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode) or len(result) >= 2048:
            raise ValueError("snapshot requires bounded regular payload files")
        result[str(path.relative_to(root))] = (
            info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    if not result:
        raise ValueError("snapshot payload is empty")
    return result


def consumed_prices_digest(prices: pd.DataFrame) -> str:
    """Evidence only: event-major/supplied-symbol float64 cells, not a new snapshot identity."""
    digest = hashlib.sha256(b"price-linear-consumed-prices/v1\0")
    digest.update(struct.pack("<QQ", *prices.shape))
    for symbol in prices.columns:
        raw = symbol.encode("utf-8")
        digest.update(struct.pack("<Q", len(raw)) + raw)
    for stamp, row in prices.iterrows():
        raw = stamp.isoformat().encode("utf-8")
        digest.update(struct.pack("<Q", len(raw)) + raw)
        for number in row:
            digest.update(struct.pack("<d", float(number) + 0.0))
    return digest.hexdigest()


@dataclass
class CapturedSource:
    store: DataStore
    record: dict[str, Any]
    provenance: dict[str, Any]
    payload_root: Path
    inventory: dict[str, tuple[int, ...]]
    physical: list[dict[str, Any]]
    prices: pd.DataFrame
    verified_at: str
    consumed_sha256: str

    def revalidate(self) -> None:
        current = self.store.get_snapshot(self.record["snapshot_id"]).to_dict()
        if current != self.record or _inventory(self.payload_root) != self.inventory:
            raise ValueError("captured source vintage changed")
        captured = SnapshotProvenanceReader(self.store.manifest).capture(current["snapshot_id"])
        if captured != self.record:
            raise ValueError("source manifest binding changed")


def capture_source(store: DataStore, request: TrainRequest) -> CapturedSource:
    rec = store.get_snapshot(request.bars_snapshot_id)
    record = rec.to_dict()
    evidence = project_snapshot_record(rec.snapshot_id, record)
    if (rec.dataset is not Dataset.BARS or rec.storage_format != "parquet_dataset"
            or rec.metadata.timeframe != "1d" or evidence["status"] != "VALID"):
        raise ValueError("training requires declared local daily bars provenance")
    provenance = evidence["value"]
    if provenance["data_tier"] not in ("pilot_real_proxy", "synthetic_fixture"):
        raise ValueError("unsupported training data tier")
    if SnapshotProvenanceReader(store.manifest).capture(rec.snapshot_id) != record:
        raise ValueError("source record is ambiguous")
    if (type(rec.row_count) is not int or not 0 < rec.row_count <= 2_000_000
            or not 0 < len(rec.symbols) <= 512 or not set(request.symbols) <= set(rec.symbols)):
        raise ValueError("unsupported source dimensions or missing requested symbols")
    now = datetime.now(UTC)
    if aware_utc(rec.as_of) > now or aware_utc(rec.created_at) > now:
        raise ValueError("source declaration contains future clocks")
    base, target = store.data_dir.resolve(), (store.data_dir / rec.data_path).resolve()
    if rec.data_path.is_absolute() or not target.is_relative_to(base) or not target.is_dir():
        raise ValueError("snapshot payload must be a local dataset beneath the data store")
    inventory = _inventory(target)
    store.verify_snapshot(rec)  # Existing readability/row-count check, separately from hashing.
    frame = store.read_bars(rec.snapshot_id)
    if len(frame) != rec.row_count or set(frame["symbol"]) != set(rec.symbols):
        raise ValueError("source payload dimensions differ from its record")
    canon = frame.reset_index().rename(columns={"timestamp": "ts"})
    algorithm = (rec.metadata.source_metadata or {}).get("content_hash_algorithm")
    if algorithm == BARS_STREAMED_HASH_ALGO:
        logical = compose_bars_symbol_hash([
            (symbol, len(group), logical_bars_hash(group))
            for symbol, group in canon.groupby("symbol", sort=True)])
    elif algorithm is None:
        logical = logical_bars_hash(canon)
    else:
        raise ValueError("unsupported existing source hash algorithm")
    if logical != rec.content_hash or compute_snapshot_id(rec.metadata, logical) != rec.snapshot_id:
        raise ValueError("source payload does not match its pinned content identity")
    physical = [{"path": name, "size": stamp[2], "sha256": sha256_file(target / name)}
                for name, stamp in sorted(inventory.items())]
    if _inventory(target) != inventory:
        raise ValueError("source payload changed during verification")

    # Future rows may be verified as source bytes, but never enter the numerical price view.
    selected = frame[(frame.index < request.train_end) & frame["symbol"].isin(request.symbols)]
    if selected.empty:
        raise ValueError("training window has no source observations")
    wide = selected.reset_index().pivot(index="timestamp", columns="symbol", values="adj_close")
    wide = wide.reindex(columns=list(request.symbols))
    calendar = MarketCalendar("XNYS")
    coverage_start = datetime.fromisoformat(provenance["coverage_start"]).date()
    past = (calendar.sessions_in_range(coverage_start,
             request.train_start.date() - timedelta(days=1))
            if coverage_start < request.train_start.date() else [])
    window = calendar.sessions_in_range(request.train_start.date(),
                                       request.train_end.date() - timedelta(days=1))
    expected = pd.DatetimeIndex(past[-5:] + window, tz="UTC", name="timestamp")
    consumed = wide.loc[wide.index >= (expected[0] if len(expected) else request.train_start)]
    if (not len(window) or not consumed.index.equals(expected) or consumed.isna().any().any()):
        raise ValueError("consumed prices require a complete common XNYS daily grid")
    if len(consumed) > 100_000 or consumed.size > 2_000_000:
        raise ValueError("consumed numerical price slice exceeds supported dimensions")
    captured = CapturedSource(store, record, provenance, target, inventory, physical,
        consumed.copy(), datetime.now(UTC).isoformat(), consumed_prices_digest(consumed))
    captured.revalidate()
    return captured
