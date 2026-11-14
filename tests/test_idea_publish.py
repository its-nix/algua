"""The Ideas mirror and the Inbox status write-back (spec 2026-11-12 §6.5)."""
from __future__ import annotations

from algua.contracts.idea import (
    AttemptOutcome,
    DataCapability,
    Horizon,
    IdeaStatus,
    Market,
    Obscurity,
    SourceType,
)
from algua.registry.db import connect, migrate
from algua.registry.idea_attempts import IdeaAttemptsRepository
from algua.registry.idea_publish_rows import (
    IDEAS_HEADER,
    ideas_by_inspiration,
    inbox_status,
    publish_rows,
)
from algua.registry.ideas import IdeaRepository, InspirationLink


def _db(tmp_path):
    conn = connect(tmp_path / "r.db")
    migrate(conn)
    return conn


def _add(conn, title: str, links: list[InspirationLink]):
    return IdeaRepository(conn).add(
        title=title, hypothesis=f"{title} hypothesis words", family=None, tags=[],
        source_type=SourceType.INSPIRATION, source_ref=None, source_date=None, source_note=None,
        required_data=[DataCapability.OHLCV], status=IdeaStatus.OPEN, category="momentum",
        market=Market.US_EQUITIES, horizon=Horizon.DAILY, falsification="f",
        created_by_run="t", inspirations=links)


def _refute(conn, reason: str) -> None:
    att = IdeaAttemptsRepository(conn)
    [claimed] = att.claim(run_stamp="r", limit=1, ttl_minutes=180)
    att.record_outcome(claimed.id, token=claimed.claim_token,
                       outcome=AttemptOutcome.WALKFORWARD_REFUTED, reason=reason)


def test_publish_rows_include_latest_attempt_and_sources(tmp_path):
    conn = _db(tmp_path)
    _add(conn, "quiet drift alpha", [InspirationLink("2026-11-12-inbox-q-abc123", "inbox",
                                                     Obscurity.HUMAN)])
    _refute(conn, "all four windows lost net of costs")
    rows = publish_rows(conn)
    assert len(rows) == 1 and set(rows[0]) == set(IDEAS_HEADER)
    row = rows[0]
    assert row["title"] == "quiet drift alpha" and row["source"] == "inbox"
    assert row["inspirations"] == "2026-11-12-inbox-q-abc123"
    assert row["latest_outcome"] == "walkforward_refuted"
    assert row["latest_reason"] == "all four windows lost net of costs"


def test_inbox_status_reflects_refuted_idea(tmp_path):
    conn = _db(tmp_path)
    _add(conn, "quiet drift alpha", [InspirationLink("2026-11-12-inbox-q-abc123", "inbox",
                                                     Obscurity.HUMAN)])
    _refute(conn, "all four windows lost net of costs")
    linked = ideas_by_inspiration(conn)["2026-11-12-inbox-q-abc123"]
    status = inbox_status(linked)
    assert status.startswith(f"#{linked[0]['id']} ")
    assert "walkforward_refuted — all four windows lost net of costs" in status
    assert inbox_status([]) == ""
