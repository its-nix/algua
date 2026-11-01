"""Snapshot vocabulary reexports and the data-lane universe timeline value."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from algua.provenance.snapshot import (
    SCHEMA_VERSION as SCHEMA_VERSION,
)
from algua.provenance.snapshot import (
    Dataset as Dataset,
)
from algua.provenance.snapshot import (
    Kind as Kind,
)
from algua.provenance.snapshot import (
    SnapshotMetadata as SnapshotMetadata,
)
from algua.provenance.snapshot import (
    SnapshotRecord as SnapshotRecord,
)


@dataclass(frozen=True)
class UniverseSnapshot:
    """One point-in-time universe-membership snapshot: the set of `symbols` that constituted a
    named universe as of `effective_date`. A time-varying universe is a timeline of these (one
    per effective date) sharing the same universe NAME. Data-layer-only value object — it never
    crosses into the backtest engine (the engine receives a plain date->symbols mapping)."""

    snapshot_id: str
    effective_date: date
    symbols: frozenset[str]
