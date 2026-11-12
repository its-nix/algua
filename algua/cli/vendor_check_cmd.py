"""`algua data vendor-check` — run the PIT sample check on a vendor's local table exports.

Stdout carries only check names, statuses and counts (`SampleCheckReport.summary()`); the full
report, whose findings can contain vendor prices, is written to `--report-out`, which must lie
OUTSIDE this public repository and must not already exist (spec §3 licence, §4.14). Exits 1 when the
sample fails, like `data verify`. Registers on its own `vendor_check_app`, merged flat onto
`data_app` by `algua.cli.main` (cli modules never import each other).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import typer

import algua
from algua.cli._common import ok
from algua.cli.app import emit
from algua.cli.errors import json_errors
from algua.data.importers.sharadar_tables import read_actions, read_sep, read_tickers
from algua.data.sharadar_check import SampleCheckReport, run_sharadar_check

vendor_check_app = typer.Typer()

_REPO_ROOT = Path(algua.__file__).resolve().parents[1]


def _private_report_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved == _REPO_ROOT or _REPO_ROOT in resolved.parents:
        raise ValueError(
            "--report-out must be outside the repository (vendor values are licensed and private)"
        )
    if resolved.exists():
        raise ValueError(f"--report-out {resolved} already exists; refusing to overwrite")
    return resolved


def _write_private(path: Path, report: SampleCheckReport) -> None:
    full = {
        "passed": report.passed,
        "checks": [{"name": c.name, "status": c.status, "counts": c.counts,
                    "findings": c.findings} for c in report.checks],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(full, fh, indent=2, default=str)


@vendor_check_app.command("vendor-check")
@json_errors
def vendor_check(
    vendor: str = typer.Option(..., "--vendor", help="data vendor; only 'sharadar' is supported"),
    sep: Path = typer.Option(..., "--sep", help="SEP daily-prices CSV export"),
    actions: Path = typer.Option(..., "--actions", help="ACTIONS CSV export"),
    tickers: Path = typer.Option(..., "--tickers", help="TICKERS CSV export"),
    previous_sep: Path = typer.Option(
        None, "--previous-sep", help="an earlier SEP pull, to measure restatements of old rows"
    ),
    report_out: Path = typer.Option(
        ..., "--report-out", help="private path OUTSIDE the repo for the full report"
    ),
) -> None:
    """Check a vendor sample against the PIT standard; print only statuses and counts."""
    if vendor != "sharadar":
        raise ValueError(f"unsupported vendor for vendor-check: {vendor!r}")
    out = _private_report_path(report_out)
    report = run_sharadar_check(
        read_sep(sep), read_actions(actions), read_tickers(tickers),
        sep_prev=read_sep(previous_sep) if previous_sep is not None else None,
    )
    _write_private(out, report)
    emit(ok({"vendor": vendor, **report.summary(), "report_out": str(out)}))
    raise typer.Exit(code=0 if report.passed else 1)
