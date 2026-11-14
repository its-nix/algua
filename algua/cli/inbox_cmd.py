"""`research inbox add | list | intake` — the owner's dashboard Inbox (spec 2026-11-14 §7.3).

The registry's `inbox_items` table is the Inbox; this CLI is its only writer. `intake` is
driver-facing: `leap.sh` runs it on every firing, before any gate, and turns each queued item into
exactly one `source_kind: human` inspiration in the vault."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer

from algua.cli._common import ok
from algua.cli.app import emit
from algua.cli.errors import json_errors
from algua.config.settings import get_settings
from algua.knowledge.inbox_notes import build_note
from algua.knowledge.inspirations import MAX_NOTE_BYTES, list_notes, write_note
from algua.primitives.timeparse import now_iso
from algua.registry.db import registry_conn
from algua.registry.idea_links import ideas_by_inspiration, journey
from algua.registry.inbox import add_item, list_items, mark_taken, queued_items
from algua.research.categories import categories_file_default, load_categories

inbox_app = typer.Typer(help="The owner's Inbox of ideas.", no_args_is_help=True)


def _bounded(text: str) -> str:
    raw = text.encode()
    return text if len(raw) <= MAX_NOTE_BYTES else raw[:MAX_NOTE_BYTES].decode(
        "utf-8", errors="ignore")


@inbox_app.command("add")
@json_errors
def add_cmd(
    url: str | None = typer.Option(None, "--url", help="A link to an idea."),
    file: Path | None = typer.Option(None, "--file", help="A saved file (e.g. a PDF)."),
    text: str | None = typer.Option(None, "--text", help="The idea as plain text."),
    title: str | None = typer.Option(None, "--title"),
    note: str | None = typer.Option(None, "--note", help="The owner's own words: why."),
    extracted_text_file: Path | None = typer.Option(
        None, "--extracted-text-file", help="UTF-8 file of text extracted from the source."),
) -> None:
    """Queue one item (exactly one of --url / --file / --text) for the next leap."""
    sources = [(k, v) for k, v in (("link", url), ("file", file), ("text", text)) if v]
    if len(sources) != 1:
        raise ValueError("give exactly one of --url, --file or --text")
    kind = sources[0][0]
    if kind == "link" and not str(url).startswith(("http://", "https://")):
        raise ValueError("--url must be an http(s) link")
    if file is not None and not file.is_file():
        raise ValueError(f"--file is not a file: {file}")
    body = text
    if extracted_text_file is not None:
        if kind == "text":
            raise ValueError("--extracted-text-file applies to --url or --file, not --text")
        body = extracted_text_file.read_text(encoding="utf-8")
    with registry_conn() as conn:
        item, duplicate = add_item(
            conn, kind=kind, url=url, title=title, note=note,
            file_path=str(file) if file is not None else None,
            text=_bounded(body) if body and body.strip() else None, now=now_iso())
    emit(ok({"item": item, "duplicate": duplicate}))


@inbox_app.command("list")
@json_errors
def list_cmd(limit: int = typer.Option(50, "--limit", min=1, max=500)) -> None:
    """Items newest first, each with its journey joined live from the idea pool."""
    with registry_conn() as conn:
        items = list_items(conn, limit=limit)
        ideas = ideas_by_inspiration(conn)
    emit(ok({"items": [{**item, "journey": journey(item, ideas)} for item in items]}))


@inbox_app.command("intake")
@json_errors
def intake_cmd() -> None:
    """Turn each queued item into one `source_kind: human` inspiration and mark it taken."""
    settings = get_settings()
    categories = set(load_categories(categories_file_default()))
    today = datetime.now(UTC).date()
    # A note written but not yet marked taken (a crash in between) is adopted, not rewritten.
    written = {str(fm["inbox_item_id"]): str(fm["id"])
               for fm in list_notes(settings, source_kind="human") if fm.get("inbox_item_id")}
    taken: list[str] = []
    warnings: list[dict[str, Any]] = []
    with registry_conn() as conn:
        for item in queued_items(conn):
            note_id = written.get(str(item["id"]))
            if note_id is None:
                try:
                    fm, body = build_note(item, today=today, categories=categories)
                    write_note(settings, fm, body)
                except Exception as exc:  # one bad item never blocks the rest
                    warnings.append({"item": item["id"], "error": str(exc)})
                    continue
                note_id = str(fm["id"])
            if mark_taken(conn, item["id"], inspiration_id=note_id, now=now_iso()):
                taken.append(note_id)
    emit(ok({"taken": taken, "warnings": warnings}))
