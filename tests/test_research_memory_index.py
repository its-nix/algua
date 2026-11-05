"""Read-only metadata index; no archive/model execution or registry migration."""
from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from algua.contracts.idea import AttemptOutcome
from algua.operator.research_memory_index import list_retained_research
from algua.registry.db import connect, migrate
from algua.registry.idea_attempts import IdeaAttemptsRepository
from tests.campaign_fixtures import add_idea

REFERENCE = "mlflow:legacy-run/public-evidence.json#sha256=" + "a" * 64


def terminal(conn, title, run, reference=REFERENCE):
    idea = add_idea(conn, title)
    repository = IdeaAttemptsRepository(conn)
    (claimed,) = repository.claim(run_stamp=run, limit=1, ttl_minutes=60, category=idea.category)
    repository.record_outcome(idea.id, token=claimed.claim_token,
                              outcome=AttemptOutcome.INTEGRITY_FAIL,
                              reason="fixture qualification limit", evidence_ref=reference)
    return claimed


def fingerprint(path):
    return {str(p): (p.stat().st_size, p.stat().st_mtime_ns,
                    hashlib.sha256(p.read_bytes()).hexdigest())
            for p in (path, path.with_name(path.name + "-wal"),
                      path.with_name(path.name + "-shm")) if p.exists()}


def test_terminal_metadata_is_bounded_ordered_and_never_contains_credentials(tmp_path):
    database = tmp_path / "authority.db"
    conn = connect(database)
    migrate(conn)
    first = terminal(conn, "first", "cycle-first")
    second = terminal(conn, "second", "cycle-second")
    terminal(conn, "legacy", "cycle-legacy", "legacy-note")
    add_idea(conn, "unfinished")
    IdeaAttemptsRepository(conn).claim(run_stamp="unfinished", limit=1, ttl_minutes=60)
    before = fingerprint(database)
    payload = list_retained_research(database, limit=1)
    assert fingerprint(database) == before
    assert payload["count"] == 1 and payload["has_more"] is True
    assert payload["metadata_verified"] is False and payload["authority"] == "none"
    assert payload["evidence_mode"] == "UNVERIFIED_WORKER"
    assert payload["association"] == "cycle_only"
    row = payload["attempts"][0]
    assert row["research_cycle_id"] == "cycle-second"
    assert row["idea_id"] == second.id and row["evidence_id"].startswith("idea_attempts:")
    assert row["outcome"] == "integrity_fail" and row["archive_reference"] == REFERENCE
    raw = json.dumps(payload)
    assert first.claim_token not in raw and second.claim_token not in raw
    assert "claim_token" not in raw and "request" not in raw
    conn.close()


@pytest.mark.parametrize("limit", [0, -1, 101, True, 1.5, "2"])
def test_invalid_limit_refuses_before_source_access(tmp_path, limit):
    with pytest.raises(ValueError):
        list_retained_research(tmp_path / "missing.db", limit=limit)
    assert not list(tmp_path.iterdir())


def test_missing_or_incompatible_database_is_not_created_or_migrated(tmp_path):
    database = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError):
        list_retained_research(database)
    assert not database.exists()
    database.write_bytes(b"invalid SQLite")
    before = fingerprint(database)
    with pytest.raises(sqlite3.DatabaseError):
        list_retained_research(database)
    assert fingerprint(database) == before


@pytest.mark.parametrize("run,reference", [
    ("../escape", REFERENCE),
    ("valid-cycle", "mlflow:bad/public-evidence.json#sha256=bad"),
])
def test_malformed_matching_metadata_refuses_whole_index(tmp_path, run, reference):
    database = tmp_path / "authority.db"
    conn = connect(database)
    migrate(conn)
    terminal(conn, "malformed", run, reference)
    with pytest.raises(ValueError):
        list_retained_research(database)
    conn.close()


def test_empty_registry_is_a_successful_empty_index(tmp_path):
    database = tmp_path / "empty.db"
    conn = connect(database)
    migrate(conn)
    assert list_retained_research(database)["attempts"] == []
    conn.close()
