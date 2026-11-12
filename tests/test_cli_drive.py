"""CLI surface of the Drive ideation backend: steering, inbox intake, idea publish."""
from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from algua.cli.main import app
from algua.knowledge.drive import tables
from tests._drive_fake import FakeDrive

runner = CliRunner()


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("ALGUA_KNOWLEDGE_DIR", str(tmp_path / "kb"))
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "data" / "algua.db"))
    monkeypatch.delenv("ALGUA_DRIVE_FOLDER_ID", raising=False)
    yield


@pytest.fixture
def drive(monkeypatch):
    fake = FakeDrive()
    fake.seed(*tables.CATEGORIES, tables.CATEGORY_HEADER, [{"slug": "momentum"}])
    monkeypatch.setenv("ALGUA_DRIVE_FOLDER_ID", "F")
    monkeypatch.setattr(tables, "client_for", lambda _s: fake)
    return fake


def _json(r):
    return json.loads(r.output)


def test_cli_export_disabled_without_folder(tmp_path):
    r = runner.invoke(app, ["research", "steering", "export", "--to", str(tmp_path / "s")])
    assert r.exit_code == 1
    body = _json(r)
    assert body["ok"] is False and body["code"] == "drive_disabled" and body["retryable"] is False


def test_cli_export_writes_snapshot(tmp_path, drive):
    r = runner.invoke(app, ["research", "steering", "export", "--to", str(tmp_path / "s")])
    assert r.exit_code == 0, r.output
    assert _json(r)["categories"] == 1
    assert (tmp_path / "s" / "categories.txt").exists()


def test_cli_drive_error_is_a_json_envelope(tmp_path, drive):
    drive.fail["read_tab"] = 1
    r = runner.invoke(app, ["research", "steering", "export", "--to", str(tmp_path / "s")])
    assert r.exit_code == 1
    body = _json(r)
    assert body["ok"] is False and body["code"] == "drive_unavailable" and body["retryable"]


def test_cli_inbox_intake(drive):
    drive.seed(*tables.INBOX, tables.INBOX_HEADER, [{"idea": "buy quiet small caps",
                                                     "category": "momentum"}])
    r = runner.invoke(app, ["research", "inbox", "intake"])
    assert r.exit_code == 0, r.output
    body = _json(r)
    assert body["ok"] is True and len(body["taken"]) == 1
    assert drive.rows(*tables.INSPIRATIONS)[0]["category"] == "momentum"


def _seed_idea(link_id: str) -> int:
    from algua.contracts.idea import (
        DataCapability,
        Horizon,
        IdeaStatus,
        Market,
        Obscurity,
        SourceType,
    )
    from algua.registry.db import registry_conn
    from algua.registry.ideas import IdeaRepository, InspirationLink
    with registry_conn() as conn:
        idea = IdeaRepository(conn).add(
            title="quiet drift alpha", hypothesis="quiet drift hypothesis words", family=None,
            tags=[], source_type=SourceType.INSPIRATION, source_ref=None, source_date=None,
            source_note=None, required_data=[DataCapability.OHLCV], status=IdeaStatus.OPEN,
            category="momentum", market=Market.US_EQUITIES, horizon=Horizon.DAILY,
            falsification="f", created_by_run="t",
            inspirations=[InspirationLink(link_id, "inbox", Obscurity.HUMAN)])
    return int(idea.id) if hasattr(idea, "id") else int(idea)


def test_publish_writes_ideas_and_only_changed_inbox_rows(drive):
    drive.seed(*tables.INBOX, tables.INBOX_HEADER, [
        {"id": "r1", "idea": "mine", "status": "taken → inspiration 2026-11-12-inbox-mine-aaaaaa"},
        {"id": "r2", "idea": "other", "status": "keep me"}])
    drive.seed(*tables.INSPIRATIONS, tables.INSPIRATION_HEADER, [
        {"id": "2026-11-12-inbox-mine-aaaaaa", "inbox_row_id": "r1"}])
    idea_id = _seed_idea("2026-11-12-inbox-mine-aaaaaa")
    r = runner.invoke(app, ["research", "idea", "publish"])
    assert r.exit_code == 0, r.output
    assert _json(r) == {"ok": True, "ideas": 1, "inbox_updated": 1}
    assert [row["id"] for row in drive.rows(*tables.IDEAS)] == [str(idea_id)]
    inbox = drive.rows(*tables.INBOX)
    assert inbox[0]["status"] == f"#{idea_id} open" and inbox[1]["status"] == "keep me"
    r = runner.invoke(app, ["research", "idea", "publish"])
    assert _json(r)["inbox_updated"] == 0


def test_publish_disabled_is_noop_exit_zero():
    r = runner.invoke(app, ["research", "idea", "publish"])
    assert r.exit_code == 0
    assert _json(r) == {"ok": True, "skipped": "drive_disabled"}


# --- review I8: the CLI (not the knowledge layer) routes inspiration writes to Drive -------------

def test_cli_mark_exhausted_and_write_yield_go_to_drive(tmp_path, drive):
    drive.seed(*tables.INSPIRATIONS, tables.INSPIRATION_HEADER,
               [{"id": "2026-11-12-foo", "status": "fresh", "source_url": "https://x"}])
    r = runner.invoke(app, ["research", "inspirations", "mark-exhausted", "2026-11-12-foo"])
    assert r.exit_code == 0, r.output
    assert drive.rows(*tables.INSPIRATIONS)[0]["status"] == "exhausted"
    drive.seed(*tables.SOURCES, tables.SOURCES_HEADER, [{"key": "ssrn", "kind": "paper"}])
    card = tmp_path / "card.json"
    card.write_text(json.dumps({"days": 90, "by_venue": {"ssrn": {"n": 6}}}))
    r = runner.invoke(app, ["research", "inspirations", "write-yield", "--from-scorecard",
                            str(card)])
    assert r.exit_code == 0, r.output
    assert json.loads(drive.rows(*tables.SOURCES)[0]["yield"])["n"] == 6
    assert not (tmp_path / "kb" / "inspirations").exists()


def test_cli_drive_failure_in_inspirations_is_a_coded_envelope(drive):
    drive.fail["read_tab"] = 1
    r = runner.invoke(app, ["research", "inspirations", "mark-exhausted", "2026-11-12-foo"])
    assert r.exit_code != 0
    assert _json(r)["code"] == "drive_unavailable"
