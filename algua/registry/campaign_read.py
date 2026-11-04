"""Read-only campaign API over an existing registry, with no bootstrap or migration."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from algua.registry.idea_scorecard import campaign_scorecard
from algua.registry.read_snapshot import registry_snapshot


def read_campaign_scorecard(path: Path) -> dict:
    """Read a consistent snapshot. Missing/incompatible schemas refuse instead of migrating."""
    # SQLite mode=ro can still CREATE/WRITE source-side WAL/SHM files. Never connect to the
    # source. Copy DB + WAL (not SHM), checking inode/size/nanosecond change stamps across capture.
    # A busy writer causes a bounded refusal. immutable=1 would silently ignore committed WAL.
    with registry_snapshot(path, label="campaign registry") as snapshot:
        try:
            return campaign_scorecard(snapshot.connection)
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc) or "no such column" in str(exc):
                raise ValueError("campaign registry schema is missing or incompatible") from exc
            raise
