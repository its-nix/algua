"""Google Drive / Sheets as the ideation backend (spec 2026-11-12-drive-ideation-design.md).

Only the ideation component uses this: inbox, steering, inspirations and the ideas mirror. No
trading, gate, registry-authority, capital or market-data path may import it.
"""
from __future__ import annotations

from algua.config.settings import Settings
from algua.knowledge.drive.client import DriveClient, DriveError


def drive_enabled(settings: Settings) -> bool:
    return bool(settings.drive_folder_id)


__all__ = ["DriveClient", "DriveError", "drive_enabled"]
