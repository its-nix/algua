"""Compile PRIVATE stable-security identities and dated ticker-change events from local exports.

Unqualified input preparation only. It reads the TICKERS and ACTIONS CSV exports through the
existing `sharadar_tables` readers and writes one private artifact. It infers NOTHING beyond the
vendor rows: no alias intervals, listing history, membership or completeness. The TICKERS `ticker`
is the vendor's CURRENT storage key (a restated key, not proof of what the security traded as on
any past date). Coverage and completeness are recorded as unverified.

Semantics (vendor `actiontypes` definitions): a `tickerchangefrom` / `tickerchangeto` pair shares
the SAME current ticker and effective date; `contraticker` is the old / new symbol. The current
ticker need not equal the new symbol (later renames). Every refusal message is fixed text with no
vendor values: errors reach stdout and the inputs are licensed data.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from algua.data.importers.sharadar_tables import read_actions, read_tickers
from algua.primitives.atomic_io import fsync_dir, fsync_file

SCHEMA = "algua.sharadar.identity_events.v1"
_FROM, _TO = "tickerchangefrom", "tickerchangeto"


class IdentityCompileError(ValueError):
    """Refusal with fixed, value-free text."""


@dataclass(frozen=True)
class IdentityArtifact:
    body: bytes
    artifact_sha256: str
    tickers_sha256: str
    actions_sha256: str
    identity_count: int
    event_count: int


def _sha256_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise IdentityCompileError("input must be a regular file")
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_hashed(path: Path, reader, label: str) -> tuple[pd.DataFrame, str]:
    before = _sha256_file(path)
    try:
        frame = reader(path)
    except Exception:  # vendor/pandas messages can quote cell text
        raise IdentityCompileError(f"{label} export failed schema validation") from None
    if _sha256_file(path) != before:
        raise IdentityCompileError(f"{label} export changed while being read")
    return frame, before


def _stable_key(permaticker: int) -> str:
    return f"sharadar:permaticker:{permaticker}"


def _identities(tickers: pd.DataFrame) -> dict[str, int]:
    """current storage ticker -> permaticker; refuses empty, non-positive, duplicate."""
    out: dict[str, int] = {}
    for perma, ticker in zip(tickers["permaticker"], tickers["ticker"], strict=True):
        if int(perma) <= 0:
            raise IdentityCompileError("TICKERS has a non-positive permaticker")
        if not ticker:
            raise IdentityCompileError("TICKERS has an empty current ticker")
        if ticker in out:
            raise IdentityCompileError("TICKERS has a duplicate or reused current ticker")
        out[ticker] = int(perma)
    if not out:
        raise IdentityCompileError("TICKERS has no SEP identities")
    return out


def _events(actions: pd.DataFrame, by_ticker: dict[str, int]) -> list[dict]:
    rows = actions[actions["action"].isin([_FROM, _TO])]
    pairs: dict[tuple[str, str], dict[str, str]] = {}
    for date, action, ticker, contra in zip(
            rows["date"], rows["action"], rows["ticker"], rows["contraticker"], strict=True):
        if not ticker or contra is None:
            raise IdentityCompileError("ticker-change row lacks ticker or contraticker")
        if ticker not in by_ticker:
            raise IdentityCompileError("ticker-change row has no unique current-ticker identity")
        slot = pairs.setdefault((ticker, date.strftime("%Y-%m-%d")), {})
        if action in slot:
            raise IdentityCompileError("duplicate ticker-change row for one ticker and date")
        slot[action] = contra
    events: list[dict] = []
    for (ticker, day), slot in pairs.items():
        if set(slot) != {_FROM, _TO}:
            raise IdentityCompileError("unpaired ticker-change row")
        old, new = slot[_FROM], slot[_TO]
        if old == new:
            raise IdentityCompileError("ticker change maps a symbol to itself")
        events.append({"stable_key": _stable_key(by_ticker[ticker]), "effective_date": day,
                       "from_ticker": old, "to_ticker": new})
    events.sort(key=lambda e: (e["stable_key"], e["effective_date"]))
    last: dict[str, dict] = {}
    for ev in events:  # chain: each rename must start from where the previous one ended
        prev = last.get(ev["stable_key"])
        if prev is not None and prev["to_ticker"] != ev["from_ticker"]:
            raise IdentityCompileError("contradictory ticker rename chain")
        last[ev["stable_key"]] = ev
    return events


def compile_identity_artifact(tickers_path: Path, actions_path: Path) -> IdentityArtifact:
    tickers, tickers_sha = _read_hashed(tickers_path, read_tickers, "TICKERS")
    actions, actions_sha = _read_hashed(actions_path, read_actions, "ACTIONS")
    by_ticker = _identities(tickers)
    events = _events(actions, by_ticker)
    identities = [
        {"stable_key": _stable_key(p), "permaticker": p, "current_storage_ticker": t}
        for t, p in sorted(by_ticker.items(), key=lambda kv: kv[1])]
    doc = {
        "schema": SCHEMA,
        "status": "unqualified_input_preparation",
        "coverage": "unverified",
        "completeness": "unverified",
        "notes": ["current_storage_ticker is a restated vendor key, not a historical ticker",
                  "no alias intervals, listing history or membership are inferred",
                  "events are explicit vendor rows only; absence of an event proves nothing"],
        "inputs": {"tickers_sha256": tickers_sha, "actions_sha256": actions_sha},
        "identities": identities,
        "ticker_change_events": events,
    }
    body = (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return IdentityArtifact(body, hashlib.sha256(body).hexdigest(), tickers_sha, actions_sha,
                            len(identities), len(events))


def write_private_new(path: Path, data: bytes, *, repo_root: Path) -> Path:
    """Publish `data` at a NEW path (0600; missing parent dirs 0700). Never overwrites, never
    follows a symlink, refuses locations inside the repository."""
    if path.is_symlink() or path.exists():
        raise IdentityCompileError("output path already exists; refusing to overwrite")
    resolved = path.expanduser().resolve()
    if resolved == repo_root or repo_root in resolved.parents:
        raise IdentityCompileError("output must be outside the repository")
    missing = []
    probe = resolved.parent
    while not probe.exists():
        missing.append(probe)
        probe = probe.parent
    for d in reversed(missing):
        d.mkdir(mode=0o700)
        d.chmod(0o700)
    tmp = resolved.parent / f".{resolved.name}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        fsync_file(tmp)
        os.link(tmp, resolved)  # atomic and fails if the destination appeared meanwhile
    except FileExistsError:
        raise IdentityCompileError("output path already exists; refusing to overwrite") from None
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
    fsync_dir(resolved.parent)
    return resolved
