"""Private, serialized SQLite journal; never an Algua strategy or evidence registry."""
from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from algua.primitives.flock import file_lock
from algua.risk.layered import decimal

_APPLICATION_ID = 0x504D4543
_SCHEMA = """
CREATE TABLE smoke(id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
CREATE TABLE intents(kind TEXT PRIMARY KEY CHECK(kind IN ('buy','sell')),
 client_order_id TEXT UNIQUE NOT NULL, request TEXT NOT NULL,
 broker_order_id TEXT, response TEXT);
CREATE TABLE fills(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE events(id INTEGER PRIMARY KEY, kind TEXT NOT NULL,
 payload TEXT NOT NULL, recorded_at TEXT NOT NULL);
CREATE TRIGGER events_no_update BEFORE UPDATE ON events
 BEGIN SELECT RAISE(ABORT,'mechanics events are immutable'); END;
CREATE TRIGGER events_no_delete BEFORE DELETE ON events
 BEGIN SELECT RAISE(ABORT,'mechanics events are immutable'); END;
CREATE TRIGGER intent_no_delete BEFORE DELETE ON intents
 BEGIN SELECT RAISE(ABORT,'mechanics intents cannot be deleted'); END;
CREATE TRIGGER intent_identity BEFORE UPDATE ON intents
 WHEN NEW.kind IS NOT OLD.kind OR NEW.client_order_id IS NOT OLD.client_order_id
 OR NEW.request IS NOT OLD.request
 OR (OLD.broker_order_id IS NOT NULL AND NEW.broker_order_id IS NOT OLD.broker_order_id)
 BEGIN SELECT RAISE(ABORT,'mechanics intent identity is immutable'); END;
"""


@contextmanager
def ledger(path: Path) -> Iterator[sqlite3.Connection]:
    path = path.absolute()
    if path.is_symlink() or path.parent.resolve() != path.parent:
        raise ValueError("mechanics path must not contain symlinks")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with file_lock(path.with_suffix(path.suffix + ".lock"), blocking=False):
        created = not path.exists()
        if created:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            os.close(fd)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            app_id = conn.execute("PRAGMA application_id").fetchone()[0]
            if not created and app_id != _APPLICATION_ID:
                raise ValueError("not an isolated paper mechanics ledger")
            conn.execute("PRAGMA synchronous=FULL")
            if created:
                conn.executescript(f"PRAGMA application_id={_APPLICATION_ID};" + _SCHEMA)
                conn.commit()
                fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            yield conn
        finally:
            conn.close()


def event(conn, kind: str, payload: dict) -> None:
    conn.execute("INSERT INTO events(kind,payload,recorded_at) VALUES (?,?,?)",
                 (kind, json.dumps(payload, sort_keys=True), datetime.now(UTC).isoformat()))


def state(conn) -> dict:
    row = conn.execute("SELECT payload FROM smoke WHERE id=1").fetchone()
    if row is None:
        raise ValueError("paper mechanics state is not initialized")
    return json.loads(row[0])


def save(conn, current: dict, kind: str) -> None:
    with conn:
        conn.execute("INSERT INTO smoke VALUES (1,?) ON CONFLICT(id) DO UPDATE SET payload=?",
                     (json.dumps(current, sort_keys=True), json.dumps(current, sort_keys=True)))
        event(conn, kind, current)


def intent(conn, kind: str) -> dict | None:
    row = conn.execute("SELECT * FROM intents WHERE kind=?", (kind,)).fetchone()
    return dict(row) if row else None


def prepare(conn, current: dict, kind: str, coid: str, request: dict) -> None:
    """Burn the opening budget and commit the original identity BEFORE any venue POST."""
    if kind == "buy" and not 0 < decimal(request["notional"]) <= 5:
        raise ValueError("mechanics opening exceeds the USD5 lifetime cap")
    with conn:
        conn.execute("INSERT INTO intents(kind,client_order_id,request) VALUES (?,?,?)",
                     (kind, coid, json.dumps(request, sort_keys=True)))
        if kind == "buy":
            current["opening_budget_consumed"] = request["notional"]
        current["phase"] = kind + "_acceptance_unresolved"
        conn.execute("UPDATE smoke SET payload=? WHERE id=1", (json.dumps(current),))
        event(conn, "intent_committed", {"kind": kind, "coid": coid, **request})


def acknowledge(conn, kind: str, order_id: str) -> None:
    with conn:
        conn.execute("UPDATE intents SET broker_order_id=? WHERE kind=?", (order_id, kind))
        event(conn, "acknowledged", {"kind": kind, "broker_order_id": order_id})
