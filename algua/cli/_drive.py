"""Shared guard for the Drive ideation commands: a disabled backend or a `DriveError` becomes the
standard `{"ok": false, "error": <code>}` envelope with exit 1 (spec 2026-11-12 §7)."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import typer

from algua.cli.app import emit
from algua.config.settings import Settings, get_settings
from algua.knowledge.drive import DriveError, drive_enabled, tables
from algua.knowledge.drive.tables import Client


@contextmanager
def drive_session() -> Iterator[tuple[Settings, Client]]:
    settings = get_settings()
    if not drive_enabled(settings):
        emit({"ok": False, "error": "drive_disabled", "code": "drive_disabled"})
        raise typer.Exit(1)
    try:
        yield settings, tables.client_for(settings)
    except DriveError as exc:
        emit({"ok": False, "error": exc.code, "code": exc.code, "detail": str(exc)})
        raise typer.Exit(1) from None
