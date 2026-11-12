"""Owner inbox intake: each row becomes one `source_kind: human` inspiration, exactly once
(spec 2026-11-12 §6.4)."""
from __future__ import annotations

from datetime import date

import pytest

from algua.knowledge.drive import DriveError, tables
from algua.knowledge.drive.inbox import intake
from algua.knowledge.frontmatter import render_doc
from algua.knowledge.inspirations import MAX_NOTE_BYTES, NOTE_ID_RE, RESERVED_HUMAN_CATEGORY
from tests._drive_fake import FakeDrive

TODAY = date(2026, 11, 12)
CATS = {"momentum", "seasonality"}


def _drive(*rows: dict) -> FakeDrive:
    d = FakeDrive()
    d.seed(*tables.INBOX, tables.INBOX_HEADER, list(rows))
    return d


def _run(d: FakeDrive) -> dict:
    return intake(d, today=TODAY, categories=CATS)


def _notes(d: FakeDrive) -> list[dict]:
    return d.rows(*tables.INSPIRATIONS)


def test_intake_assigns_ids_and_creates_one_inspiration_per_row():
    d = _drive({"idea": "Buy small caps after quiet weeks", "why / notes": "volume dries up",
                "links": "https://a.example", "category": "momentum"},
               {"idea": "Turn of month in Dec"})
    result = _run(d)
    inbox = d.rows(*tables.INBOX)
    assert result["assigned_ids"] == 2 and len(result["taken"]) == 2
    assert all(r["id"] for r in inbox)
    notes = _notes(d)
    assert [n["inbox_row_id"] for n in notes] == [r["id"] for r in inbox]
    first = notes[0]
    assert NOTE_ID_RE.match(first["id"]) and "-inbox-buy-small-caps" in first["id"]
    assert (first["source_kind"], first["venue"], first["obscurity"], first["status"]) == \
        ("human", "inbox", "human", "fresh")
    assert first["category"] == "momentum" and first["source_url"] == f"inbox:{inbox[0]['id']}"
    assert "volume dries up" in first["body"] and "https://a.example" in first["body"]
    assert inbox[0]["status"] == f"taken → inspiration {first['id']}"
    assert notes[1]["category"] == RESERVED_HUMAN_CATEGORY


def test_intake_is_exactly_once():
    d = _drive({"idea": "one"}, {"idea": "two"})
    _run(d)
    again = _run(d)
    assert again["taken"] == [] and again["assigned_ids"] == 0
    assert len(_notes(d)) == 2


def test_edited_taken_row_is_ignored():
    d = _drive({"idea": "original"})
    _run(d)
    d.tabs[tables.INBOX]["rows"][0]["idea"] = "edited text"
    assert _run(d)["taken"] == []
    assert len(_notes(d)) == 1


def test_clearing_id_resubmits():
    d = _drive({"idea": "retry me"})
    _run(d)
    d.tabs[tables.INBOX]["rows"][0].update(id="", status="")
    result = _run(d)
    assert len(result["taken"]) == 1 and len(_notes(d)) == 2


def test_status_written_by_publish_is_not_overwritten():
    d = _drive({"idea": "x"})
    _run(d)
    d.tabs[tables.INBOX]["rows"][0]["status"] = "#4 refuted: lost money"
    _run(d)
    assert d.rows(*tables.INBOX)[0]["status"] == "#4 refuted: lost money"


def test_blank_and_why_only_rows_skipped():
    d = _drive({"idea": "  ", "why / notes": "only a why"}, {})
    result = _run(d)
    assert result["taken"] == [] and _notes(d) == []
    assert d.rows(*tables.INBOX)[0]["id"] == ""


def test_unknown_category_falls_back_to_reserved_and_warns():
    d = _drive({"idea": "x", "category": "astrology"})
    result = _run(d)
    assert _notes(d)[0]["category"] == RESERVED_HUMAN_CATEGORY
    assert result["warnings"] == [{"row": 2, "warning": "unknown category 'astrology'"}]


def test_long_and_unicode_idea_truncated_within_note_cap():
    idea = ("קנה מניות קטנות 🚀 " * 400)[:5000]
    d = _drive({"idea": idea, "why / notes": "y" * 20000})
    _run(d)
    note = _notes(d)[0]
    assert NOTE_ID_RE.match(note["id"]) and "-inbox-idea-" in note["id"]
    fm = {k: note[k] for k in ("id", "found_at", "source_url", "venue", "source_kind",
                               "category", "market", "horizon", "mechanism", "obscurity",
                               "status")}
    assert len(render_doc(fm, note["body"]).encode()) <= MAX_NOTE_BYTES
    assert "קנה מניות קטנות 🚀" in note["body"]
    assert len(note["mechanism"]) <= 500


def test_drive_failure_mid_intake_rerun_converges():
    d = _drive({"idea": "flaky"})
    d.fail["update_cells"] = 2  # 1 = id assignment, 2 = the status write
    with pytest.raises(DriveError):
        _run(d)
    d.fail.clear()
    _run(d)
    assert len(_notes(d)) == 1
    assert d.rows(*tables.INBOX)[0]["status"] == f"taken → inspiration {_notes(d)[0]['id']}"
