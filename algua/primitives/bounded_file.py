"""Bounded regular-file reads through a directory descriptor, without following symlinks."""
from __future__ import annotations

import os
import stat
from pathlib import Path


def read_relative_regular(root: Path, relative: str, limit: int) -> bytes:
    """Walk trusted fixed paths with no symlink following, including directory components."""
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parts = relative.split("/")
        for component in parts[:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
                raise ValueError("frozen model file is not a bounded regular file")
            with os.fdopen(fd, "rb", closefd=False) as handle:
                content = handle.read(limit + 1)
            if len(content) != info.st_size or len(content) > limit:
                raise ValueError("frozen model file size changed during capture")
            return content
        finally:
            os.close(fd)
    finally:
        os.close(directory)
