"""`research inbox add | list | intake` on the registry `inbox_items` table (spec §7.3)."""
import json

import pytest
from typer.testing import CliRunner

from algua.cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("ALGUA_KNOWLEDGE_DIR", str(tmp_path / "kb"))
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("ALGUA_STEERING_DIR", raising=False)
    yield tmp_path


@pytest.fixture
def tmp_vault(tmp_path):
    return tmp_path / "kb" / "inspirations"


def cli(*args):
    r = runner.invoke(app, list(args))
    return json.loads(r.output)


def test_add_list_intake_exactly_once(tmp_vault):
    r = cli("research", "inbox", "add", "--url", "https://youtu.be/abc", "--note",
            "index deletions rebound")
    assert r["ok"] and r["duplicate"] is False
    assert cli("research", "inbox", "list")["items"][0]["journey"][0]["tone"] == "pending"
    first = cli("research", "inbox", "intake")["taken"]
    assert len(first) == 1 and (tmp_vault / f"{first[0]}.md").exists()
    assert cli("research", "inbox", "intake")["taken"] == []
    assert cli("research", "inbox", "list")["items"][0]["journey"][0]["label"] == "Inspiration"


def test_add_requires_exactly_one_source():
    assert cli("research", "inbox", "add")["code"] == "invalid_input"
    assert cli("research", "inbox", "add", "--url", "https://a.b/c", "--text", "x")["code"] == \
        "invalid_input"


def test_file_with_no_text_is_still_added(tmp_path):
    f = tmp_path / "scan.pdf"
    f.write_bytes(b"%PDF-1.4 no text")
    r = cli("research", "inbox", "add", "--file", str(f))
    assert r["ok"] and r["item"]["text"] is None
    assert r["item"]["kind"] == "file" and r["item"]["file_path"] == str(f)


def test_extracted_text_file_is_read(tmp_path):
    f = tmp_path / "paper.pdf"
    f.write_bytes(b"%PDF")
    t = tmp_path / "extracted.txt"
    t.write_text("Quiet stocks drift — résumé", encoding="utf-8")
    r = cli("research", "inbox", "add", "--file", str(f), "--extracted-text-file", str(t))
    assert r["item"]["text"] == "Quiet stocks drift — résumé"


def test_journey_follows_the_idea_outcome(tmp_vault):
    from algua.contracts.idea import IdeaStatus, Obscurity, SourceType
    from algua.registry.db import registry_conn
    from algua.registry.ideas import IdeaRepository, InspirationLink

    cli("research", "inbox", "add", "--text", "buy the dip in small caps")
    note_id = cli("research", "inbox", "intake")["taken"][0]
    with registry_conn() as conn:
        repo = IdeaRepository(conn)
        idea = repo.add(title="small cap dip", hypothesis="h", family=None, tags=[],
                        source_type=SourceType.INSPIRATION, source_ref=None, source_date=None,
                        source_note=None, required_data=[], status=IdeaStatus.OPEN,
                        inspirations=[InspirationLink(note_id, "inbox", Obscurity.HUMAN)],
                        created_by_run="r")
        conn.execute("INSERT INTO idea_attempts (idea_id, run_stamp, claim_token, claimed_at, "
                     "outcome, reason, outcome_at) VALUES (?, 'r', 't', 'x', "
                     "'walkforward_refuted', 'unstable windows', 'y')", (idea.id,))
        conn.execute("UPDATE ideas SET status = ? WHERE id = ?", (IdeaStatus.REFUTED, idea.id))
        conn.commit()
    journey = cli("research", "inbox", "list")["items"][0]["journey"]
    assert journey == [
        {"label": "Inspiration", "tone": "neutral"},
        {"label": f"Idea #{idea.id}", "tone": "neutral"},
        {"label": "Refuted: unstable windows", "tone": "refuted"},
    ]


def test_intake_adopts_a_note_written_before_a_crash(tmp_vault):
    from datetime import date

    from algua.config.settings import get_settings
    from algua.knowledge.inbox_notes import build_note
    from algua.knowledge.inspirations import write_note

    item = cli("research", "inbox", "add", "--text", "quiet drift")["item"]
    fm, body = build_note(item, today=date(2026, 11, 1), categories=set())
    write_note(get_settings(), fm, body)  # the note landed; mark_taken never ran
    r = cli("research", "inbox", "intake")
    assert r["taken"] == [fm["id"]] and r["warnings"] == []
    assert len(list(tmp_vault.glob("*.md"))) == 1
