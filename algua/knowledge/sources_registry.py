"""`_sources.yaml` — the venue registry of the inspirations domain (spec 2026-09-08 §4/§5).

Carved out of `inspirations.py`. With Drive enabled (spec 2026-11-12) the registry lives in the
Steering Sheet's Sources tab; reads honour a run-start snapshot like every other steering read.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import yaml

from algua.config.settings import Settings
from algua.knowledge.inspirations import inspirations_dir
from algua.knowledge.sync import kb_sync_lock
from algua.primitives.atomic_io import write_text_atomic


class SourcesRegistry:
    """`_sources.yaml`: `{venues: [...]}`. Only trusted code writes it.

    Every write goes through `write_text_atomic` under the vault's `kb_sync_lock`, exactly like
    the note writes above — the registry is a human-edited steering file, and a torn or
    interleaved write would corrupt a surface nobody is watching between runs.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.path = inspirations_dir(settings) / "_sources.yaml"

    def load(self) -> list[dict[str, Any]]:
        if self._settings.drive_folder_id:
            return _drive_sources(self._settings).load()
        if not self.path.exists():
            return []
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        return list(data.get("venues") or [])

    def _save(self, venues: list[dict[str, Any]]) -> None:
        if self._settings.drive_folder_id:
            _drive_sources(self._settings).save(venues)
            return
        write_text_atomic(yaml.safe_dump({"venues": venues}, sort_keys=False), self.path)

    def write_yields(self, yields: dict[str, dict[str, Any]]) -> None:
        """Stamp a yield object onto every named venue in ONE load + ONE save (a per-venue
        load/save loop re-read and rewrote the whole file once per venue)."""
        with kb_sync_lock(self._settings):
            venues = self.load()
            for v in venues:
                obj = yields.get(str(v.get("key")))
                if obj is not None:
                    v["yield"] = obj
            self._save(venues)

    def propose(self, venue: dict[str, Any]) -> None:
        with kb_sync_lock(self._settings):
            venues = self.load()
            if any(v.get("key") == venue.get("key") for v in venues):
                return
            venues.append({**venue, "added_by": "forage",
                           "added_at": datetime.now(UTC).date().isoformat()})
            self._save(venues)


def _drive_sources(settings: Settings) -> Any:
    from algua.knowledge.drive.tables import SourcesTable, client_for
    return SourcesTable(client_for(settings))
