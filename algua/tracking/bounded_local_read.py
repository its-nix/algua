"""Bounded ordinary-file reads; no whole-file copy, source mutation or retry."""
from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_CHUNK_BYTES = 64 * 1024
_MAX_FILE_BYTES = 16 * 1024 * 1024
_MAX_BUDGET_BYTES = 32 * 1024 * 1024


class LocalReadError(ValueError):
    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


class ReadBudget:
    """Actual source-content bytes consumed, including reads that subsequently refuse."""

    def __init__(self, limit_bytes: int) -> None:
        if type(limit_bytes) is not int or not 0 < limit_bytes <= _MAX_BUDGET_BYTES:
            raise ValueError("local read budget must be a positive bounded integer")
        self.limit_bytes = limit_bytes
        self._used_bytes = 0

    @property
    def used_bytes(self) -> int:
        return self._used_bytes

    @property
    def remaining_bytes(self) -> int:
        return self.limit_bytes - self._used_bytes

    def _charge(self, count: int) -> None:
        self._used_bytes += count


def _stamp(value: os.stat_result) -> tuple[int, ...]:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


@contextmanager
def _opened(path: Path, root: Path) -> Iterator[tuple[int, os.stat_result]]:
    descriptors = []
    try:
        if ".." in path.parts or ".." in root.parts:
            raise ValueError("parent traversal is unsupported")
        path, root = path.absolute(), root.absolute()
        if root.resolve(strict=True) != root:
            raise ValueError("linked source roots are unsupported")
        relative = path.relative_to(root)
        if not relative.parts:
            raise ValueError("source must be a file beneath its root")
        flags = os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW
        parent = os.open(root, flags | os.O_DIRECTORY)
        descriptors.append(parent)
        for part in relative.parts[:-1]:
            parent = os.open(part, flags | os.O_DIRECTORY, dir_fd=parent)
            descriptors.append(parent)
        descriptor = os.open(relative.name, flags, dir_fd=parent)
        descriptors.append(descriptor)
        captured = os.fstat(descriptor)
        if not stat.S_ISREG(captured.st_mode):
            raise ValueError("source is not a regular file")
    except (OSError, ValueError) as exc:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
        raise LocalReadError("artifact_location_unsupported",
                             "research memory source location is unsupported") from exc
    try:
        yield descriptor, captured
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def read_local_file(
    path: Path, *, root: Path, max_bytes: int, budget: ReadBudget | None = None,
    expected_sha256: str | None = None,
) -> bytes:
    """Preflight captured size, read only that size in capped chunks, then revalidate identity.

    The bound covers materialized source content, not kernel/database I/O. Ordinary filesystem
    reads remain under the caller's process deadline; this is not a universal return-time SLA.
    """
    if type(max_bytes) is not int or not 0 < max_bytes <= _MAX_FILE_BYTES:
        raise ValueError("local file ceiling must be a positive bounded integer")
    with _opened(path, root) as (descriptor, captured):
        size = captured.st_size
        if size > max_bytes or budget is not None and size > budget.remaining_bytes:
            raise LocalReadError("source_bytes_exceeded",
                                 "research memory source exceeds its byte bound")
        digest = hashlib.sha256()
        chunks = []
        remaining = size
        try:
            while remaining:
                count = min(_CHUNK_BYTES, remaining)
                if budget is not None:
                    count = min(count, budget.remaining_bytes)
                block = os.read(descriptor, count)
                if not block:
                    raise OSError("source ended before its captured length")
                if budget is not None:
                    budget._charge(len(block))
                remaining -= len(block)
                digest.update(block)
                chunks.append(block)
            if _stamp(os.fstat(descriptor)) != _stamp(captured):
                raise OSError("descriptor changed during read")
            with _opened(path, root) as (_, current):
                if _stamp(current) != _stamp(captured):
                    raise OSError("source path changed during read")
        except (OSError, LocalReadError) as exc:
            raise LocalReadError("artifact_changed",
                                 "research memory source changed during read") from exc
        if expected_sha256 is not None and digest.hexdigest() != expected_sha256:
            raise LocalReadError("artifact_integrity_mismatch",
                                 "research memory artifact digest mismatch")
        return b"".join(chunks)
