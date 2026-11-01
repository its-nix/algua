"""Read-only campaign API over an existing registry, with no bootstrap or migration."""
from __future__ import annotations

import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from algua.registry.idea_scorecard import campaign_scorecard


def read_campaign_scorecard(path: Path) -> dict:
    """Read a consistent snapshot. Missing/incompatible schemas refuse instead of migrating."""
    if not path.is_file():
        raise FileNotFoundError(f"campaign registry does not exist: {path}")
    # SQLite mode=ro can still CREATE/WRITE source-side WAL/SHM files. Never connect to the
    # source. Copy DB + WAL (not SHM), checking inode/size/nanosecond change stamps across capture.
    # A busy writer causes a bounded refusal. immutable=1 would silently ignore committed WAL.
    path = path.resolve()
    sources = [path, Path(str(path) + "-wal"), Path(str(path) + "-journal")]
    with TemporaryDirectory(prefix="algua-campaign-") as directory:
        target = Path(directory) / "registry.db"
        before = [_stamp(p) for p in sources]
        if before[2] is not None and before[2][2] > 0:
            raise sqlite3.OperationalError("campaign registry has a rollback journal; retry later")
        try:
            shutil.copyfile(path, target)
            if before[1] is not None:
                shutil.copyfile(sources[1], Path(str(target) + "-wal"))
        except FileNotFoundError as exc:
            raise sqlite3.OperationalError(
                "campaign registry changed during capture; retry") from exc
        if before != [_stamp(p) for p in sources]:
            raise sqlite3.OperationalError("campaign registry changed during capture; retry")
        with closing(sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            conn.execute("BEGIN")
            try:
                return campaign_scorecard(conn)
            except sqlite3.OperationalError as exc:
                if "no such table" in str(exc) or "no such column" in str(exc):
                    raise ValueError("campaign registry schema is missing or incompatible") from exc
                raise


def _stamp(path: Path) -> tuple[int, int, int, int, int] | None:
    try:
        s = path.stat()
        return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns
    except FileNotFoundError:
        return None
