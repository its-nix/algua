from __future__ import annotations

import math

import typer

from algua.cli._common import ok, project
from algua.cli.app import app, emit
from algua.cli.errors import json_errors
from algua.registry.promote_run import promote_task

research_app = typer.Typer(help="Research workflow: gates and promotion", no_args_is_help=True)
app.add_typer(research_app, name="research")

# --summary keep-list (#349): the decision essence of a promote — the pass/fail verdict, the
# per-check breakdown (`checks` carries each gate's name/value/threshold/pass), the breadth and
# the binding flags, the holdout/stability scalars, and provenance. Keep-list (not drop-list) so
# the deep dsr_* internals and shadow-audit fields are
# excluded-by-default from the operator-facing summary (context-rot defense).
_PROMOTE_SUMMARY_KEYS = (
    "promoted", "strategy", "passed", "checks", "n_combos", "n_funnel", "breadth_provenance",
    "base_min_holdout_sharpe", "pit_ok", "pit_override",
    "dsr_binding", "dsr_bootstrap_binding", "returns_available", "holdout", "stability",
    "config_hash", "snapshot_id", "universe_name", "universe_snapshots", "fundamentals_snapshot",
    "news_snapshot",
)


@research_app.command("promote")
# sqlite3.OperationalError keeps lock-contention ("database is locked") from reserve_holdout's
# BEGIN IMMEDIATE inside the JSON envelope, not a leaked traceback (CLI JSON-output contract).
@json_errors
def promote(
    name: str,
    start: str = typer.Option("2023-01-01", "--start"),
    end: str = typer.Option("2023-12-31", "--end"),
    demo: bool = typer.Option(False, "--demo", help="use the synthetic data provider"),
    snapshot: str = typer.Option(None, "--snapshot", help="backtest an ingested bars snapshot id"),
    fundamentals_snapshot: str = typer.Option(
        None, "--fundamentals-snapshot",
        help="ingested fundamentals snapshot id (required for a needs_fundamentals strategy)"),
    news_snapshot: str = typer.Option(
        None, "--news-snapshot",
        help="ingested news snapshot id (required for a needs_news strategy)"),
    universe: str = typer.Option(
        None, "--universe",
        help="point-in-time universe name (opt into survivorship-bias-free membership)"),
    windows: int = typer.Option(4, "--windows", help="walk-forward windows"),
    holdout_frac: float = typer.Option(0.2, "--holdout-frac", help="fraction reserved as holdout"),
    min_holdout_sharpe: float = typer.Option(0.5, "--min-holdout-sharpe"),
    min_holdout_return: float = typer.Option(0.0, "--min-holdout-return"),
    delistings: str = typer.Option(
        None, "--delistings",
        help="delistings snapshot handle (survivorship-free: realize held delisted names)"),
    actor: str = typer.Option(
        "agent", "--actor",
        help="human | agent: an audit label only; it unlocks nothing (every gate is the same)"),
    summary: bool = typer.Option(
        False, "--summary",
        help="emit only decision-relevant scalars (drops deep dsr_* diagnostics; "
             "context-rot defense)"),
) -> None:
    """Gate backtested->candidate on the INTEGRITY FLOOR; promote only on pass (factory soft gate).

    BINDING (the floor): PIT universe (`--universe`; non-PIT fails closed), holdout >= 63
    observations (underpowered holdouts fail closed), and raw holdout Sharpe > 0. Everything
    statistical — the holdout-Sharpe/return bars and the DSR/bootstrap evidence (the one
    trial-aware signal) — is computed and recorded as ADVISORY (`"advisory": true` on the check;
    never vetoes). The FORWARD gate is the harsh threshold (its
    bar is 0.5x the holdout Sharpe recorded here — overfit self-punishes). Breadth is MEASURED as
    the sum of recorded `search_trials` (from `backtest sweep`); no measured trials => refused. The
    holdout is single-use. The gates are the same for every `--actor`: there is no override. See
    docs/superpowers/specs/2026-11-13-go-live-only-approval-design.md.
    """
    for flag, value in (("--min-holdout-sharpe", min_holdout_sharpe),
                        ("--min-holdout-return", min_holdout_return)):
        if not math.isfinite(value):  # Infinity/NaN would land in decision_json (not strict JSON)
            raise ValueError(f"{flag} must be a finite number")
    payload = promote_task(
        name, start=start, end=end, demo=demo, snapshot=snapshot,
        fundamentals_snapshot=fundamentals_snapshot, news_snapshot=news_snapshot,
        universe=universe, windows=windows, holdout_frac=holdout_frac,
        min_holdout_sharpe=min_holdout_sharpe, min_holdout_return=min_holdout_return,
        delistings=delistings, actor=actor,
    )
    out = ok(payload)
    emit(project(out, _PROMOTE_SUMMARY_KEYS) if summary else out)
