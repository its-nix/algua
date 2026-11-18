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
from dataclasses import dataclass
from pathlib import Path

from algua.data.importers.sharadar_tables import TICKERS_COLUMNS
from algua.data.sharadar_identity import (
    MAX_ROWS,
    MAX_TICKERS_BYTES,
    IdentityCompileError,
    _capture,
)
from algua.data.sharadar_metadata_paths import MetadataPrepareError, publish_metadata

__all__ = [
    "MetadataArtifact",
    "MetadataPrepareError",
    "SCHEMA",
    "prepare_metadata",
    "publish_metadata",
]

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
