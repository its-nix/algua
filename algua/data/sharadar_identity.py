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

import functools
import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from algua.data.importers.sharadar_tables import read_actions, read_tickers

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


MAX_TICKERS_BYTES = 64 << 20
MAX_ACTIONS_BYTES = 512 << 20
MAX_ROWS = 5_000_000


def _capture(path: Path, limit: int) -> bytes:
    """Read the source ONCE (bounded, no symlink) and return the exact bytes."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        with os.fdopen(fd, "rb") as fh:
            if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
                raise IdentityCompileError("input must be a regular file")
            data = fh.read(limit + 1)
    except IdentityCompileError:
        raise
    except OSError:
        raise IdentityCompileError("input could not be read as a regular file") from None
    if len(data) > limit:
        raise IdentityCompileError("input exceeds the size limit")
    return data


def _read_hashed(path: Path, reader, label: str, limit: int) -> tuple[pd.DataFrame, str]:
    """Hash the captured bytes and parse a private temp copy of those SAME bytes, so the hash
    binds exactly what was parsed whatever happens to the source afterwards."""
    data = _capture(path, limit)
    digest = hashlib.sha256(data).hexdigest()
    with tempfile.TemporaryDirectory(prefix="algua-ident-") as tmp:  # mkdtemp: 0700
        copy = Path(tmp) / "export.csv"
        fd = os.open(copy, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        try:
            frame = reader(copy)
        except Exception:  # vendor/pandas messages can quote cell text
            raise IdentityCompileError(f"{label} export failed schema validation") from None
    if len(frame) > MAX_ROWS:
        raise IdentityCompileError(f"{label} export exceeds the row limit")
    return frame, digest


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


def _sanitized(message: str):
    """Any unexpected failure (OS, temp, parser) becomes fixed value-free text: raw exception
    strings can carry paths or vendor cell text and the shared CLI decorator prints str(exc)."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except IdentityCompileError:
                raise
            except Exception:
                raise IdentityCompileError(message) from None
        return wrapper
    return deco


@_sanitized("identity compilation failed")
def compile_identity_artifact(tickers_path: Path, actions_path: Path) -> IdentityArtifact:
    tickers, tickers_sha = _read_hashed(tickers_path, read_tickers, "TICKERS", MAX_TICKERS_BYTES)
    actions, actions_sha = _read_hashed(actions_path, read_actions, "ACTIONS", MAX_ACTIONS_BYTES)
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


def _open_dir(name: str, parent_fd: int | None, *, create: bool) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        return os.open(name, flags, dir_fd=parent_fd)
    except FileNotFoundError:
        if not create or parent_fd is None:
            raise
    os.mkdir(name, 0o700, dir_fd=parent_fd)  # mode only narrows under umask; no chmod needed
    return os.open(name, flags, dir_fd=parent_fd)


@_sanitized("output could not be written")
def write_private_new(path: Path, data: bytes, *, repo_root: Path) -> Path:
    """Publish `data` at a NEW path (0600; missing parent dirs 0700). Never overwrites. Walks the
    path from `/` one directory fd at a time (O_NOFOLLOW), so a symlink at any component, even one
    swapped in mid-call, is refused rather than followed. Refuses locations inside the repo."""
    absolute = Path(os.path.abspath(path.expanduser()))
    if absolute == repo_root or repo_root in absolute.parents:
        raise IdentityCompileError("output must be outside the repository")
    *dirs, name = absolute.parts[1:]
    fds: list[int] = []
    try:
        fds.append(_open_dir("/", None, create=False))
        for comp in dirs:
            try:
                fds.append(_open_dir(comp, fds[-1], create=True))
            except OSError:  # ELOOP/ENOTDIR (symlink or non-directory) or any other refusal
                raise IdentityCompileError("output path must be real directories only") from None
        dfd = fds[-1]
        tmp_name = f".{name}.{os.getpid()}.tmp"
        fd = os.open(tmp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600,
                     dir_fd=dfd)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.link(tmp_name, name, src_dir_fd=dfd, dst_dir_fd=dfd)  # atomic, no overwrite
        except FileExistsError:
            raise IdentityCompileError(
                "output path already exists; refusing to overwrite") from None
        finally:
            try:
                os.unlink(tmp_name, dir_fd=dfd)
            except FileNotFoundError:
                pass
        os.fsync(dfd)
    finally:
        for f in fds:
            os.close(f)
    return absolute
