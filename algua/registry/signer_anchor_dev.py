"""Credential-free development loader; OMITTED from the installed live artifact."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

ALLOWED_SIGNERS_PATH = Path(__file__).resolve().parents[2] / 'approvers' / 'allowed_signers'
SSH_KEYGEN = '/usr/bin/ssh-keygen'


class AnchorError(RuntimeError):
    """The development anchor is unavailable."""


@dataclass(frozen=True)
class AnchorSnapshot:
    content: bytes
    path: Path
    pass_fds: tuple[int, ...] = ()


def require_enrollment_allowed() -> None:
    """Development enrollment still requires human code-owner review."""


@contextmanager
def open_anchor(path: Path) -> Iterator[AnchorSnapshot]:
    try:
        content = path.read_bytes()
        with NamedTemporaryFile('wb', prefix='algua-dev-signers-') as stream:
            stream.write(content)
            stream.flush()
            yield AnchorSnapshot(content, Path(stream.name))
    except OSError as exc:
        raise AnchorError(f'allowed_signers trust anchor unavailable: {path}') from exc


def operator_lock_path() -> Path | None:
    """Development/paper keep their existing per-checkout lock resolution."""
    return None
