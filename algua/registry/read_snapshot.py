"""Stable private copies for registry readers; never open SQLite on the source files."""
from __future__ import annotations

import hashlib
import shutil
import sqlite3
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory


@dataclass(frozen=True)
class RegistrySnapshot:
    connection: sqlite3.Connection
    source_digest: str


def _stamp(path: Path) -> tuple[int, int, int, int, int] | None:
    try:
        s = path.stat()
        return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns
    except FileNotFoundError:
        return None


@contextmanager
def registry_snapshot(
    path: Path, *, max_bytes: int | None = None, timeout_seconds: float | None = None,
    label: str = "registry",
) -> Iterator[RegistrySnapshot]:
    """Copy DB and committed WAL, refusing a changing source or a hot rollback journal.

    SQLite's read-only mode may write WAL/SHM beside its input, so SQLite sees only the copy.
    The fingerprint covers the captured DB/WAL bytes; it grants no authority to their contents.
    """
    if not path.is_file():
        raise FileNotFoundError(f"{label} does not exist: {path}")
    path = path.resolve()
    sources = [path, Path(str(path) + "-wal"), Path(str(path) + "-journal")]
    before = [_stamp(p) for p in sources]
    if before[2] is not None and before[2][2] > 0:
        raise sqlite3.OperationalError(f"{label} has a rollback journal; retry later")
    if max_bytes is not None and sum(s[2] for s in before if s) > max_bytes:
        raise ValueError("registry snapshot exceeds its byte bound")
    with TemporaryDirectory(prefix="algua-registry-read-") as directory:
        target = Path(directory) / "registry.db"
        copied = [target]
        try:
            shutil.copyfile(path, target)
            if before[1] is not None:
                wal = Path(str(target) + "-wal")
                shutil.copyfile(sources[1], wal)
                copied.append(wal)
        except FileNotFoundError as exc:
            raise sqlite3.OperationalError(f"{label} changed during capture; retry") from exc
        if before != [_stamp(p) for p in sources]:
            raise sqlite3.OperationalError(f"{label} changed during capture; retry")
        digest = hashlib.sha256()
        for item in copied:
            digest.update(item.name.encode())
            with item.open("rb") as stream:
                digest.update(hashlib.file_digest(stream, "sha256").digest())
        with closing(sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            conn.execute("PRAGMA trusted_schema=OFF")
            if timeout_seconds is not None:
                deadline = time.monotonic() + timeout_seconds
                conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            conn.execute("BEGIN")
            yield RegistrySnapshot(conn, digest.hexdigest())
