"""Offline TICKERS metadata preparation. Unqualified source capture, not a PIT certificate.

Reads one local TICKERS CSV through the existing bounded capture helper and writes nothing.
Every table row is kept, before any SEP/SF1 join. Cell text is copied exactly: no trim, case
fold, integer or date conversion. An empty CSV field becomes null; the literal strings NA and
NULL stay literal. ``source_columns`` is the export header, so a column that was not in the file
is distinct from a present empty cell. Required names are the existing ``TICKERS_COLUMNS``
contract. Optional columns are not required. Refusals are fixed text: errors reach stdout and
the inputs are licensed vendor data.
"""

from __future__ import annotations

import csv
import functools
import hashlib
import io
import json
import os
from dataclasses import dataclass
from pathlib import Path

from algua.data.importers.sharadar_tables import TICKERS_COLUMNS
from algua.data.sharadar_identity import (
    MAX_ROWS,
    MAX_TICKERS_BYTES,
    IdentityCompileError,
    _capture,
)

SCHEMA = "algua.sharadar.tickers_metadata.v1"
_BOM = b"\xef\xbb\xbf"
_NOTES = (
    "unqualified source preparation; verified_pit is false",
    "rows are every TICKERS table row before any SEP or SF1 join",
    "text is exact: no trim, case fold, integer or date conversion",
    "empty CSV fields are null; literal NA and NULL strings stay literal",
    "a column absent from source_columns was not in the export; a present null was an empty cell",
    "no interval, membership, point-in-time certification or feed publication is inferred",
)


class MetadataPrepareError(ValueError):
    """Refusal with fixed, value-free text."""


@dataclass(frozen=True)
class MetadataArtifact:
    body: bytes
    artifact_sha256: str
    tickers_sha256: str
    row_count: int


def _guard(message: str):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except MetadataPrepareError:
                raise
            except IdentityCompileError as exc:
                raise MetadataPrepareError(str(exc)) from None
            except Exception:
                raise MetadataPrepareError(message) from None

        return wrapper

    return deco


def _decode(data: bytes) -> str:
    body = data[len(_BOM) :] if data.startswith(_BOM) else data
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        raise MetadataPrepareError("TICKERS export is not valid UTF-8") from None


def _parse_csv(data: bytes) -> tuple[list[str], list[dict[str, str | None]]]:
    try:
        reader = csv.reader(io.StringIO(_decode(data), newline=""))
        header = next(reader)
    except StopIteration:
        raise MetadataPrepareError("TICKERS export is missing required columns") from None
    except MetadataPrepareError:
        raise
    except csv.Error:
        raise MetadataPrepareError("TICKERS export could not be parsed") from None
    if len(header) != len(set(header)):
        raise MetadataPrepareError("TICKERS export has duplicate headers")
    if any(name == "" for name in header):
        raise MetadataPrepareError("TICKERS export has a malformed header")
    missing = [name for name in TICKERS_COLUMNS if name not in header]
    if missing:
        raise MetadataPrepareError("TICKERS export is missing required columns")
    width = len(header)
    rows: list[dict[str, str | None]] = []
    try:
        for record in reader:
            if len(record) != width:
                raise MetadataPrepareError("TICKERS export has a malformed row")
            if len(rows) >= MAX_ROWS:
                raise MetadataPrepareError("TICKERS export exceeds the row limit")
            rows.append(
                {
                    name: None if value == "" else value
                    for name, value in zip(header, record, strict=True)
                }
            )
    except csv.Error:
        raise MetadataPrepareError("TICKERS export could not be parsed") from None
    return header, rows


@_guard("TICKERS metadata preparation failed")
def prepare_metadata(path: Path) -> MetadataArtifact:
    """Capture one TICKERS export and return an unqualified metadata artifact body."""
    data = _capture(path, MAX_TICKERS_BYTES)
    digest = hashlib.sha256(data).hexdigest()
    header, rows = _parse_csv(data)
    doc = {
        "schema": SCHEMA,
        "status": "unqualified",
        "verified_pit": False,
        "coverage": "unverified",
        "completeness": "unverified",
        "notes": list(_NOTES),
        "inputs": {"tickers_sha256": digest},
        "source_columns": header,
        "row_count": len(rows),
        "rows": rows,
    }
    body = (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return MetadataArtifact(body, hashlib.sha256(body).hexdigest(), digest, len(rows))


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        raise MetadataPrepareError("could not confirm output is outside every worktree") from None


def _pointer(text: str, base: Path) -> Path:
    raw = text.strip()
    prefix = "gitdir:"
    if raw.startswith(prefix):
        raw = raw[len(prefix) :].strip()
    if not raw:
        raise MetadataPrepareError("could not confirm output is outside every worktree")
    path = Path(raw)
    if not path.is_absolute():
        path = base / path
    return Path(os.path.abspath(path))


def checkout_roots(repo_root: Path) -> tuple[Path, ...]:
    """Running checkout, the main worktree, and every linked worktree this git dir lists.

    A checkout with no ``.git`` entry yields only ``repo_root``. An unreadable git layout
    refuses rather than guessing: the output must be outside every repository and worktree.
    """
    root = Path(os.path.abspath(repo_root))
    roots = {root}
    git_entry = root / ".git"
    try:
        is_file = git_entry.is_file()
        is_dir = git_entry.is_dir()
    except OSError:
        raise MetadataPrepareError("could not confirm output is outside every worktree") from None
    if is_file:
        gitdir = _pointer(_read_text(git_entry), root)
        common = _pointer(_read_text(gitdir / "commondir"), gitdir)
        roots.add(common.parent)
        worktrees = common / "worktrees"
    elif is_dir:
        worktrees = git_entry / "worktrees"
    else:
        return (root,)
    try:
        entries = list(worktrees.iterdir()) if worktrees.is_dir() else []
    except OSError:
        raise MetadataPrepareError("could not confirm output is outside every worktree") from None
    for entry in entries:
        pointer = entry / "gitdir"
        if not pointer.is_file():
            continue
        roots.add(_pointer(_read_text(pointer), entry).parent)
    return tuple(roots)


def assert_output_outside_checkouts(path: Path, repo_root: Path) -> None:
    """Refuse an output path inside this checkout, the main repo, or a linked worktree."""
    absolute = Path(os.path.abspath(path.expanduser()))
    for root in checkout_roots(repo_root):
        if absolute == root or root in absolute.parents:
            raise MetadataPrepareError("output must be outside the repository")
