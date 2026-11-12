"""Shared guard for the Drive ideation commands: a disabled backend or a `DriveError` becomes the
standard `{"ok": false, "error": <code>}` envelope with exit 1 (spec 2026-11-12 §7)."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import typer

from algua.cli.app import emit
from algua.cli.errors import error_envelope
from algua.config.settings import Settings, get_settings
from algua.knowledge.drive import DriveError, drive_enabled, tables
from algua.knowledge.drive.tables import Client


@contextmanager
def drive_session() -> Iterator[tuple[Settings, Client]]:
    settings = get_settings()
    if not drive_enabled(settings):
        emit({"ok": False, "error": "ALGUA_DRIVE_FOLDER_ID is not set",
              "code": "drive_disabled", "retryable": False})
        raise typer.Exit(1)
    try:
        yield settings, tables.client_for(settings)
    except DriveError as exc:
        emit(error_envelope(exc))
        raise typer.Exit(1) from None


def inspirations_store(settings: Settings) -> object | None:
    """The Drive Inspirations table when the backend is on, else None (the vault files)."""
    if not drive_enabled(settings):
        return None
    return tables.InspirationsTable(tables.client_for(settings))


def sources_backend(settings: Settings) -> object | None:
    """The Drive Sources table when the backend is on, else None (`_sources.yaml`)."""
    if not drive_enabled(settings):
        return None
    return tables.SourcesTable(tables.client_for(settings))
