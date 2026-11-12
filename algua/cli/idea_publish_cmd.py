"""`research idea publish` — project the idea pool into the Drive Ideas Sheet and tell the owner,
in their own Inbox row, what became of each idea (spec 2026-11-12 §6.5).

A pure projection: SQLite stays authoritative. Drivers call it unconditionally at the end of a
run and ignore its exit, so a disabled backend is a successful no-op.
"""
from __future__ import annotations

from datetime import UTC, datetime

import typer

from algua.cli._common import ok
from algua.cli._drive import drive_session
from algua.cli.app import emit
from algua.config.settings import get_settings
from algua.knowledge.drive import drive_enabled
from algua.knowledge.drive.tables import IDEAS, INBOX, INBOX_HEADER, InspirationsTable
from algua.registry.db import registry_conn
from algua.registry.idea_publish_rows import (
    IDEAS_HEADER,
    ideas_by_inspiration,
    inbox_status,
    publish_rows,
)

idea_publish_app = typer.Typer()


@idea_publish_app.command("publish")
def publish() -> None:
    """Rewrite the Ideas Sheet and update owner Inbox statuses (driver only)."""
    if not drive_enabled(get_settings()):
        emit(ok({"skipped": "drive_disabled"}))
        return
    with registry_conn() as conn:
        rows = publish_rows(conn)
        linked = ideas_by_inspiration(conn)
    with drive_session() as (_settings, client):
        client.replace_tab(*IDEAS, IDEAS_HEADER, rows)
        note_of = {r["inbox_row_id"]: r["id"] for r in InspirationsTable(client).rows()
                   if r.get("inbox_row_id")}
        client.ensure_header(*INBOX, INBOX_HEADER)
        now = datetime.now(UTC).isoformat(timespec="seconds")
        updated = 0
        for row in client.read_tab(*INBOX, required=["id"]):
            note = note_of.get(row.get("id", "").strip())
            status = inbox_status(linked.get(note, [])) if note else ""
            if status and status != row.get("status", ""):
                client.update_cells(*INBOX, int(row["_row"]), {"status": status, "updated": now})
                updated += 1
    emit(ok({"ideas": len(rows), "inbox_updated": updated}))
