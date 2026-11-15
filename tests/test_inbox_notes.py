"""Pure note builder for owner inbox items (spec 2026-11-14 §7.3)."""
from datetime import date

from algua.knowledge.frontmatter import render_doc
from algua.knowledge.inbox_notes import build_note
from algua.knowledge.inspirations import (
    MAX_NOTE_BYTES,
    NOTE_ID_RE,
    RESERVED_HUMAN_CATEGORY,
    validate_note,
)

TODAY = date(2026, 11, 14)


def _item(**kw):
    base = {"id": 7, "kind": "text", "url": None, "title": None, "note": None,
            "file_path": None, "text": None}
    return {**base, **kw}


def test_note_id_is_stable_and_valid():
    item = _item(title="Index deletions rebound!", note="why not")
    fm1, _ = build_note(item, today=TODAY, categories={"momentum"})
    fm2, _ = build_note(item, today=TODAY, categories={"momentum"})
    assert NOTE_ID_RE.match(fm1["id"]) and fm1["id"] == fm2["id"]
    assert fm1["id"].startswith("2026-11-14-inbox-index-deletions-rebound-")
    assert fm1["inbox_item_id"] == 7 and fm1["source_url"] == "inbox:7"
    assert (fm1["source_kind"], fm1["venue"], fm1["obscurity"], fm1["status"]) == (
        "human", "inbox", "human", "fresh")
    assert validate_note(fm1, stem=fm1["id"], categories={"momentum"}) == []


def test_unknown_category_falls_back_to_reserved():
    fm, _ = build_note(_item(note="x y", category="nonsense"), today=TODAY,
                       categories={"momentum"})
    assert fm["category"] == RESERVED_HUMAN_CATEGORY
    fm, _ = build_note(_item(note="x y", category="momentum"), today=TODAY,
                       categories={"momentum"})
    assert fm["category"] == "momentum"


def test_long_extracted_text_fits_max_note_bytes():
    fm, body = build_note(_item(kind="file", file_path="/d/inbox/7/paper.pdf",
                                text="é" * 100_000), today=TODAY, categories=set())
    assert len(render_doc(fm, body).encode()) <= MAX_NOTE_BYTES
    assert "## Extracted text" in body and "(truncated)" in body


def test_link_only_item_has_link_section():
    fm, body = build_note(_item(kind="link", url="https://youtu.be/abc"), today=TODAY,
                          categories=set())
    assert "## Link\n\nhttps://youtu.be/abc" in body
    assert fm["source_url"] == "https://youtu.be/abc"
    assert NOTE_ID_RE.match(fm["id"]) and fm["mechanism"]
