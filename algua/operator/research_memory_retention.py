"""Metadata-only admission for removal of the known scratch model-store location."""
from __future__ import annotations

import stat
from pathlib import Path


def _directory_stamp(path: Path) -> tuple[int, int, int, int, int]:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("model-store ancestor is not a real directory")
    return info.st_dev, info.st_ino, info.st_mode, info.st_mtime_ns, info.st_ctime_ns


def model_store_retention_reason(worker_root: Path) -> str | None:
    """Require stable absence; any object, alias or failed inspection retains the worker.

    The existing seed binds the canonical worker. From there, never follow scratch/data
    aliases or inspect model contents. Empty directories and dangling leaf symlinks count
    as presence. Unknown opaque bytes elsewhere are outside this known-location guard.
    Callers retain their existing worker/queue serialization and fresh fallback checks.
    """
    try:
        root = worker_root.resolve(strict=True)
        ancestors = (root, root / ".funnel-scratch", root / ".funnel-scratch/data")
        before = tuple(_directory_stamp(path) for path in ancestors)
        try:
            (ancestors[-1] / "models").lstat()
        except FileNotFoundError:
            after = tuple(_directory_stamp(path) for path in ancestors)
            return None if before == after else "model_store_unverified"
        return "model_store_present"
    except (OSError, RuntimeError, ValueError):
        return "model_store_unverified"
