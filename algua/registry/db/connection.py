"""``connect()`` -- the sqlite handle every registry caller opens, and its pragma posture.

Deliberately does NOT call ``migrate()``: callers pair the two (see ``registry_conn`` in this
package's ``__init__.py``).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from algua.registry.db.constants import SCHEMA_VERSION


def check_schema_version(conn: sqlite3.Connection) -> None:
    """Refuse newer registries before connection setup or migration can mutate them."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise ValueError(
            f"registry schema version {version} is newer than supported {SCHEMA_VERSION}; "
            "upgrade Algua before opening this registry")


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        check_schema_version(conn)
    except (ValueError, sqlite3.Error):
        conn.close()
        raise
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000;")  # WAL + busy_timeout = deliberate concurrency posture
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    # recursive_triggers is OFF by default, and with it OFF the implicit row-delete SQLite performs
    # to resolve an `INSERT/REPLACE ... OR REPLACE` conflict does NOT fire BEFORE DELETE triggers.
    # The v37 append-only triggers on families/family_members/family_parents/family_events/
    # backtest_returns (#524) would therefore be silently bypassed by a REPLACE — an in-place row
    # rewrite masquerading as an append. Turn it ON so the append-only invariant also covers the
    # implicit-delete path. NB: this is a PER-CONNECTION pragma, not schema-resident: a raw
    # sqlite3.connect() that skips this helper does NOT inherit it (see the narrowed trigger comment
    # in family.py). Explicit DELETE/UPDATE stay aborted through ANY connection regardless.
    conn.execute("PRAGMA recursive_triggers=ON;")
    return conn
