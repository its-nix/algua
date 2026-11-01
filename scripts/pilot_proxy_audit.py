"""Read-only integrity audit for immutable pilot-proxy bar components."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from algua.calendar.market_calendar import MarketCalendar
from algua.data.files import logical_bars_hash, sha256_file
from algua.data.research_provenance import DataTier, decode_research_provenance
from algua.data.store import DataStore, compute_snapshot_id
from scripts.pilot_proxy_source import RecipeError, discover_git_worktree_roots


def validate_request(
    output: Path,
    start: str,
    end: str,
    count: int,
    batch_size: int,
    attempts: int,
    timeout: int,
    *,
    today: date,
) -> None:
    try:
        start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError as exc:
        raise RecipeError("start/end must be ISO dates") from exc
    if start_date >= end_date:
        raise RecipeError("start must precede half-open end")
    if end_date > today:
        raise RecipeError("end must not be in the future UTC")
    for valid, message in (
        (1 <= count <= 300, "count must be between 1 and 300"),
        (1 <= batch_size <= 300, "batch-size must be between 1 and 300"),
        (1 <= attempts <= 3, "attempts must be between 1 and 3"),
        (1 <= timeout <= 300, "timeout must be between 1 and 300 seconds"),
    ):
        if not valid:
            raise RecipeError(message)
    resolved, repo = output.resolve(), Path(__file__).resolve().parents[1]
    if any(
        resolved == root or root in resolved.parents for root in discover_git_worktree_roots(repo)
    ):
        raise RecipeError("output must be outside every git worktree and repository")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise RecipeError("output must be a new empty directory")


def build_child_env(output: Path, executable: Path, parent: Mapping[str, str]) -> dict[str, str]:
    env = {
        "PATH": f"{executable.parent}:/usr/bin:/bin",
        "HOME": str(output / "home"),
        "LANG": parent.get("LANG", "C.UTF-8"),
        "LC_ALL": parent.get("LC_ALL", "C.UTF-8"),
        "ALGUA_DATA_DIR": str(output / "data"),
        "ALGUA_DB_PATH": str(output / "registry.sqlite"),
    }
    env.update(
        {name: parent[name] for name in ("SSL_CERT_FILE", "SSL_CERT_DIR") if parent.get(name)}
    )
    return env


def run_cli_attempt(
    command: list[str],
    *,
    env: Mapping[str, str],
    cwd: Path,
    timeout: int,
    logs_dir: Path,
    label: str,
    attempt: int,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    expect_json: bool = True,
) -> dict[str, Any]:
    logs_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{label}.attempt-{attempt}"
    stdout_path, stderr_path = logs_dir / f"{stem}.stdout.log", logs_dir / f"{stem}.stderr.log"
    status, exit_code, parsed = "success", None, None
    started_at = datetime.now(UTC)
    try:
        result = (runner or subprocess.run)(
            command,
            cwd=cwd,
            env=dict(env),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        stdout, stderr, exit_code = result.stdout, result.stderr, result.returncode
        if result.returncode:
            status = "nonzero"
        elif expect_json:
            try:
                parsed = json.loads(stdout)
            except json.JSONDecodeError:
                status = "invalid_json"
    except subprocess.TimeoutExpired as exc:
        stdout = _text(exc.output)
        stderr = _text(exc.stderr)
        status = "timeout"
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    return {
        "attempt": attempt,
        "status": status,
        "exit_code": exit_code,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "command": command[1:],
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
        "payload": parsed,
    }


def _text(value: str | bytes | None) -> str:
    return value.decode(errors="replace") if isinstance(value, bytes) else value or ""


def initial_state() -> dict[str, Any]:
    return {
        "schema_version": "pilot-proxy-campaign/v1",
        "status": "initializing",
        "requests": [],
        "components": [],
        "limitations": [
            "current-survivor proxy; no historical membership, market-cap, liquidity, "
            "PIT eligibility, or delisting verification",
            "raw OHLC plus vendor retrospective adj_close; splits/dividends are not an "
            "independent action ledger",
            "vendor history may revise; partial histories and XNYS gaps are reported and "
            "never filled",
        ],
    }


def validate_cli_surface(campaign: Any) -> None:
    """Require the installed ingest/inspect/verify help surfaces before source download."""
    for command, label in (
        ("ingest-bars", "help-ingest"),
        ("inspect", "help-inspect"),
        ("verify", "help-verify"),
    ):
        payload, request = campaign.invoke(
            [str(campaign.executable), "data", command, "--help"],
            label,
            attempts=1,
            expect_json=False,
        )
        if payload is not None or request["status"] != "success":
            raise RecipeError(f"CLI help validation failed for data {command}")


@dataclass(frozen=True)
class ComponentOutcome:
    probe_passed: bool
    successful: frozenset[str]
    missing: tuple[str, ...]


def run_components(campaign: Any, selected: list[str], batch_size: int) -> ComponentOutcome:
    if campaign.ingest(selected[:2], designation="probe", campaign=False) is None:
        campaign.state.update({"status": "failed", "failure": "probe_failed"})
        campaign.save()
        return ComponentOutcome(False, frozenset(), tuple(selected))
    succeeded: set[str] = set()
    for index in range(0, len(selected), batch_size):
        batch = selected[index : index + batch_size]
        component = campaign.ingest(
            batch, designation=f"batch-{index // batch_size + 1}", campaign=True
        )
        if component is not None:
            succeeded.update(batch)
        else:
            for symbol in batch:
                if (
                    campaign.ingest([symbol], designation=f"fallback-{symbol}", campaign=True)
                    is not None
                ):
                    succeeded.add(symbol)
        campaign.save()
    return ComponentOutcome(True, frozenset(succeeded), tuple(sorted(set(selected) - succeeded)))


def audit_snapshot(
    *,
    data_dir: Path,
    snapshot: dict[str, Any],
    inspected: dict[str, Any],
    verified: dict[str, Any],
    requested_symbols: list[str],
    start: str,
    end: str,
    today: date,
    retrieved_at: datetime,
) -> dict[str, Any]:
    """Re-read one component and verify its recorded identity and logical contents."""
    if inspected != snapshot:
        raise RecipeError("CLI inspect result is not exactly equal to ingest result")
    snapshot_id = str(snapshot.get("snapshot_id", ""))
    rows = verified.get("snapshots")
    if not (
        verified.get("ok") is True
        and verified.get("failed") == 0
        and verified.get("verified") == 1
        and isinstance(rows, list)
        and len(rows) == 1
        and rows[0].get("snapshot_id") == snapshot_id
        and rows[0].get("ok") is True
    ):
        raise RecipeError("CLI verify did not confirm exactly one requested snapshot")
    store = DataStore(data_dir)
    rec = store.get_snapshot(snapshot_id)
    if rec.to_dict() != snapshot:
        raise RecipeError("manifest record differs from CLI snapshot")
    provenance = decode_research_provenance(rec.metadata.source_metadata)
    if (
        rec.provider != "yfinance"
        or provenance is None
        or provenance.data_tier is not DataTier.PILOT_REAL_PROXY
        or provenance.provider != "yfinance"
    ):
        raise RecipeError("snapshot must carry yfinance pilot_real_proxy provenance")
    frame = store.read_bars(snapshot_id)
    canon = frame.reset_index().rename(columns={"timestamp": "ts"})
    digest = logical_bars_hash(canon)
    if digest != rec.content_hash:
        raise RecipeError("logical bars hash differs from manifest content_hash")
    if compute_snapshot_id(rec.metadata, digest) != snapshot_id:
        raise RecipeError("snapshot identity recomputation failed")
    repeated = store.read_bars(snapshot_id).reset_index().rename(columns={"timestamp": "ts"})
    repeated_digest = logical_bars_hash(repeated)
    if repeated_digest != digest:
        raise RecipeError("repeated readback digest differs")

    requested = sorted(set(requested_symbols))
    actual = sorted(str(value) for value in frame["symbol"].unique())
    if actual != requested or actual != list(rec.symbols):
        raise RecipeError("declared, requested, and actual symbols differ")
    if len(frame) != rec.row_count:
        raise RecipeError("readback row count differs from manifest")
    start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
    timestamps = canon["ts"]
    if len(canon) == 0:
        raise RecipeError("component contains no bars")
    if (timestamps.dt.date < start_date).any() or (timestamps.dt.date >= end_date).any():
        raise RecipeError("bars fall outside requested half-open range")
    if (timestamps.dt.date >= today).any():
        raise RecipeError("component contains current/future UTC bars")
    if rec.metadata.timeframe != "1d" or rec.metadata.adjustment != "none":
        raise RecipeError("component metadata is not daily unadjusted OHLC")
    observed_start = timestamps.min().date().isoformat()
    observed_end = timestamps.max().date().isoformat()
    if (provenance.coverage_start, provenance.coverage_end) != (observed_start, observed_end):
        raise RecipeError("provenance coverage differs from actual bars")

    expected = set(
        MarketCalendar("XNYS").sessions_in_range(start_date, end_date - timedelta(days=1))
    )
    coverage: dict[str, Any] = {}
    for symbol in actual:
        symbol_dates = [value.date() for value in frame.index[frame["symbol"] == symbol]]
        observed = set(symbol_dates)
        coverage[symbol] = {
            "row_count": len(symbol_dates),
            "first_date": min(symbol_dates).isoformat(),
            "last_date": max(symbol_dates).isoformat(),
            "missing_sessions": [value.isoformat() for value in sorted(expected - observed)],
            "unexpected_dates": [value.isoformat() for value in sorted(observed - expected)],
        }

    root = data_dir / rec.data_path
    physical = [
        {"path": path.relative_to(root).as_posix(), "sha256": sha256_file(path)}
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]
    if not physical:
        raise RecipeError("component has no physical payload files")
    return {
        "snapshot_id": snapshot_id,
        "logical_bars_hash": digest,
        "repeated_readback_hash": repeated_digest,
        "row_count": len(frame),
        "symbols": actual,
        "coverage": coverage,
        "physical_files": physical,
        "retrieved_at": retrieved_at.isoformat(),
    }
