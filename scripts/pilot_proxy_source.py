"""Strict current-membership source parsing for the pilot proxy recipe."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9.-]*$")


class RecipeError(ValueError):
    """Fail-closed recipe input, execution, or audit error."""


@dataclass(frozen=True)
class SourceSelection:
    source_symbols: tuple[str, ...]
    selected: tuple[dict[str, str], ...]
    excluded: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class SourceDocument:
    filename: str
    selection: SourceSelection


def installed_algua_executable(sys_executable: str) -> Path:
    """Return the absolute venv sibling without resolving the interpreter symlink."""
    return Path(sys_executable).absolute().with_name("algua")


def build_parser(default_source_url: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bounded current-S&P-400/yfinance proxy recipe")
    parser.add_argument("--output", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--count", type=int, default=150)
    parser.add_argument("--batch-size", type=int, default=150)
    parser.add_argument("--attempts", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--source-url", default=default_source_url)
    return parser


@dataclass(frozen=True)
class PreparedSource:
    filename: str
    manifest: dict[str, Any]
    method: str
    selected: tuple[str, ...]


def prepare_source(
    payload: bytes, *, url: str, count: int, retrieved_at: str
) -> PreparedSource:
    document = parse_source_payload(payload, count=count)
    source_hash = hashlib.sha256(payload).hexdigest()
    selection = document.selection
    return PreparedSource(
        filename=document.filename,
        manifest={
            "url": url,
            "retrieved_at": retrieved_at,
            "sha256": source_hash,
            "raw_symbols": list(selection.source_symbols),
            "selected_mapping": list(selection.selected),
            "excluded": list(selection.excluded),
            "selection_method": (
                "unique source symbols sorted ascending; periods mapped to hyphens; first N"
            ),
        },
        method=f"sp400-current-sorted-first-{count}/sha256:{source_hash}",
        selected=tuple(row["yahoo_symbol"] for row in selection.selected),
    )


def download_source(
    url: str,
    *,
    output: Path,
    attempts: int,
    timeout: int,
    state: dict[str, Any],
    save: Callable[[], None],
) -> bytes:
    """Download exact source bytes with bounded, durable failure accounting."""
    request: dict[str, Any] = {"label": "source-download", "url": url, "attempts": []}
    state["requests"].append(request)
    save()
    for number in range(1, attempts + 1):
        started = datetime.now(UTC)
        stdout_log = output / "logs" / f"source-download.attempt-{number}.stdout.log"
        stderr_log = output / "logs" / f"source-download.attempt-{number}.stderr.log"
        try:
            source_request = Request(url, headers={"User-Agent": "AlguaResearchProxy/1.0"})
            with urlopen(source_request, timeout=timeout) as response:  # noqa: S310
                payload = response.read()
            status, error = "success", ""
        except OSError as exc:
            payload = b""
            status, error = "network_error", str(exc)
        stdout_log.write_text("", encoding="utf-8")
        stderr_log.write_text(error, encoding="utf-8")
        request["attempts"].append(
            {
                "attempt": number,
                "status": status,
                "started_at": started.isoformat(),
                "finished_at": datetime.now(UTC).isoformat(),
                "stdout_log": str(stdout_log),
                "stderr_log": str(stderr_log),
            }
        )
        save()
        if status == "success":
            request["status"] = "success"
            save()
            return payload
        if number < attempts:
            time.sleep(0.25 * number)
    request["status"] = "failed"
    state.update({"status": "failed", "failure": "source_download_failed"})
    save()
    raise RecipeError("source download failed after bounded attempts")


def discover_git_worktree_roots(repo: Path) -> frozenset[Path]:
    """Read Git's common-dir metadata and return main plus every linked worktree root."""
    repo = repo.resolve()
    marker = repo / ".git"
    roots = {repo}
    if marker.is_file():
        line = marker.read_text(encoding="utf-8").strip()
        if not line.startswith("gitdir: "):
            raise RecipeError("repository .git pointer is malformed")
        git_dir = Path(line.removeprefix("gitdir: "))
        git_dir = (marker.parent / git_dir).resolve() if not git_dir.is_absolute() else git_dir
    elif marker.is_dir():
        git_dir = marker.resolve()
    else:
        return frozenset(roots)
    common = git_dir.parents[1] if git_dir.parent.name == "worktrees" else git_dir
    roots.add(common.parent.resolve())
    worktrees = common / "worktrees"
    if worktrees.is_dir():
        for pointer in worktrees.glob("*/gitdir"):
            linked_marker = Path(pointer.read_text(encoding="utf-8").strip())
            roots.add(linked_marker.parent.resolve())
    return frozenset(roots)


def parse_source_payload(payload: bytes, *, count: int) -> SourceDocument:
    """Parse the Wikipedia constituents table or a strict custom CSV without rewriting bytes."""
    if payload.lstrip().startswith((b"<", b"<!")):
        return SourceDocument("constituents.html", _select(_html_symbols(payload), count))
    return SourceDocument("constituents.csv", parse_source_csv(payload, count=count))


def parse_source_csv(payload: bytes, *, count: int) -> SourceSelection:
    try:
        reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")), strict=True)
        fields = reader.fieldnames
        if fields is None or "Symbol" not in fields or len(fields) != len(set(fields)):
            raise RecipeError("source CSV must contain one unique Symbol header")
        raw: list[str] = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise RecipeError("source CSV is malformed")
            raw.append(_symbol(row["Symbol"]))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise RecipeError("source CSV is malformed") from exc
    return _select(raw, count)


def _html_symbols(payload: bytes) -> list[str]:
    soup = BeautifulSoup(payload, "html.parser")
    table = soup.find("table", id="constituents")
    if table is None:
        raise RecipeError("source HTML must contain table id constituents")
    rows = table.find_all("tr")
    if not rows:
        raise RecipeError("constituents table is empty")
    headers = [cell.get_text(" ", strip=True) for cell in rows[0].find_all("th")]
    if "Symbol" not in headers or len(headers) != len(set(headers)):
        raise RecipeError("constituents table must contain one unique Symbol header")
    symbol_index = headers.index("Symbol")
    raw: list[str] = []
    for row in rows[1:]:
        cells = row.find_all("td", recursive=False)
        if len(cells) != len(headers):
            raise RecipeError("constituents table contains a malformed row")
        raw.append(_symbol(cells[symbol_index].get_text(" ", strip=True)))
    return raw


def _symbol(value: str) -> str:
    if value != value.strip() or not _SYMBOL.fullmatch(value):
        raise RecipeError("source contains a malformed Symbol value")
    return value


def _select(raw: list[str], count: int) -> SourceSelection:
    if not raw:
        raise RecipeError("source contains no symbols")
    unique = sorted(set(raw))
    if len(unique) < count:
        raise RecipeError(f"source has {len(unique)} unique symbols; requested {count}")
    aliases = {symbol: symbol.replace(".", "-") for symbol in unique}
    reverse: dict[str, list[str]] = {}
    for source, alias in aliases.items():
        reverse.setdefault(alias, []).append(source)
    collisions = {alias: values for alias, values in reverse.items() if len(values) > 1}
    if collisions:
        raise RecipeError(f"Yahoo alias collision: {collisions}")
    selected = tuple(
        {"source_symbol": source, "yahoo_symbol": aliases[source]} for source in unique[:count]
    )
    excluded = [
        {"source_symbol": symbol, "reason": "duplicate_source_symbol"}
        for symbol in unique
        for _ in range(raw.count(symbol) - 1)
    ]
    excluded += [{"source_symbol": symbol, "reason": "beyond_first_n"} for symbol in unique[count:]]
    return SourceSelection(tuple(raw), selected, tuple(excluded))
