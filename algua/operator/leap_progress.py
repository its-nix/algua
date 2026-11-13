"""Bound clean zero-yield retries by actual input identity; no hypothesis/economic authority."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from algua.operator.research_memory_checkpoint import canonical, strict_json
from algua.primitives.atomic_io import write_bytes_durable
from algua.tracking.bounded_local_read import read_local_file


def context_key(context: dict) -> str:
    return hashlib.sha256(canonical(context)).hexdigest()


def _count(directory: Path, key: str) -> int:
    if not isinstance(key, str) or re.fullmatch('[0-9a-f]{64}', key) is None:
        raise ValueError('leap_progress:invalid_key')
    path = directory / 'leap-progress.json'
    if not path.exists() and not path.is_symlink():
        return 0
    try:
        state = strict_json(read_local_file(path, root=directory.absolute(), max_bytes=4096))
        if (not isinstance(state, dict) or set(state) != {'key', 'clean_empty_passes'}
                or not isinstance(state['key'], str)
                or re.fullmatch('[0-9a-f]{64}', state['key']) is None
                or type(state['clean_empty_passes']) is not int
                or not 0 <= state['clean_empty_passes'] <= 2):
            raise ValueError
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        raise ValueError('leap_progress:invalid_state') from exc
    return state['clean_empty_passes'] if state['key'] == key else 0


def ready(directory: Path, key: str) -> bool:
    """Caller holds the existing leap.lock over check, model work and result recording."""
    return _count(directory, key) < 2


def record_result(directory: Path, key: str, *, clean: bool, imported: int) -> None:
    count = _count(directory, key)
    if not clean:
        return
    count = min(2, count + 1) if imported == 0 else 0
    write_bytes_durable(canonical({'key': key, 'clean_empty_passes': count}) + b'\n',
                        directory / 'leap-progress.json')
