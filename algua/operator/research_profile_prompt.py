"""Forward one admitted operator profile unchanged; it supplies no promotion authority."""
from __future__ import annotations

from pathlib import Path

from algua.operator.research_cycle_results import read_report
from algua.operator.research_memory_checkpoint import canonical, strict_json

_KEEP = ("id", "title", "hypothesis", "category", "market", "horizon", "falsification",
         "inspirations", "required_data", "family")
_FRAME = """

REQUIRED RESEARCH INPUT PROFILE — OPERATOR CONFIGURATION
This profile overrides generic example data options and candidate instructions above.
Use this exact evaluation_profile for every claimed idea and every evaluation command.
Pass the complete profile unchanged to the existing author and interpret tasks. It fixes the
strategy CONFIG universe to all listed symbols; do not replace it with the snapshot's larger
symbol set, today's screen, another snapshot, dates, --demo or an invented --universe timeline.
If the claimed hypothesis requires incompatible inputs, record run_error with the actual reason;
never substitute a new hypothesis or silently select different inputs. Keep the original claim.
Use --snapshot {snapshot_id} --start {start} --end {end}; windows=4, holdout_frac=0.2, 1d,
closed-bar decisions and next-bar execution. Use long-only top-20 equal weights, max symbol
weight 0.075, fees=0.0005 and slippage=0.0005 per side. Keep all seven limitations in every report.
Use --research-only for author smoke and registered backtests. The configured pilot also enforces
this development-only scope automatically: requested dates stay pinned, actual backtest end is
the reserved holdout start. Never inspect that tail for smoke or call prior exposed data fresh.
Before numerical work, put every mandatory comparison in one research run-all tasks JSON, with
required_window_metrics: ["total_return"] on each sweep (plus any other required supported metric).
The real batch preflights all declared tasks before simulation. Retain each trial's window_metrics
and compare the strategy/control on identical start/end dates, net of the pinned costs. Aggregate
sweep statistics alone cannot test paired-window falsification; reuse recorded outputs.
A diagnostic control may use broad equal_weight_positive construction. Its sweep task must declare
evaluation_role=benchmark and benchmark_for=<primary name>. Keep both in control CONFIG.params.
Include the primary strategy sweep in the same batch. Declare a common conservative feature_lookback
so effective embargo and research windows match; all other profile inputs/costs/timing stay pinned.
Benchmarks are numerical diagnostics, never registration, promotion or merge-back instructions.
run-all supports backtest/sweep/promote actions, not walk-forward. Call walk-forward CLI separately.
Backtest tasks use CONFIG defaults and accept no param grid; put grids only on sweep tasks.
This is pilot_real_proxy exploration only: qualification is data_blocked, preview_gate: null,
no merge_back, no candidate or paper admission. Empirical falsification remains a separate finding.
Use integrity_fail only for an actual integrity failure, never merely for this known data limit.
The daily bar label and collection time do not establish historical availability or verified PIT.
BEGIN REQUIRED RESEARCH PROFILE JSON
"""


def admitted_profile(raw: bytes, *, expected: dict, cycle_id: str, database: str) -> dict:
    """Bind the same validated source receipt to the controller's actual campaign admission."""
    try:
        if len(raw) > 1024 * 1024:
            raise ValueError
        response = strict_json(raw)
        request = response["campaign"]["menu"]["request"]
        receipt = request["context"]["research_profile"]
        if (response["ok"] is not True or response["phase"] != "running"
                or response["research_cycle_id"] != cycle_id
                or request["research_cycle_id"] != cycle_id or request["database"] != database
                or receipt != expected):
            raise ValueError
        return receipt
    except (KeyError, ValueError, TypeError, RecursionError):
        raise ValueError("research_profile:admission_mismatch") from None


def profile_claims(claims: list[dict], receipt: dict) -> list[dict]:
    return [{**{k: row.get(k) for k in _KEEP}, "evaluation_profile": receipt} for row in claims]


def render_profile_goal(goal: str, receipt: dict) -> str:
    result = goal + _FRAME.format(**receipt) + canonical(receipt).decode() + (
        "\nEND REQUIRED RESEARCH PROFILE JSON")
    if len(result.encode()) + 1 > 96 * 1024:
        raise ValueError("research_profile:goal_too_large")
    return result


def validate_proxy_report(path: Path) -> None:
    """Refuse incompatible publication instead of rewriting a model's economic verdict."""
    try:
        rows, gate = read_report(path)
        if gate is not None or any(row["outcome"] not in {
                "data_blocked", "integrity_fail", "run_error"}
                or row["merge_back"] is not None or row["verdict"] == "candidate-preview-pass"
                for row in rows):
            raise ValueError
    except (OSError, ValueError, TypeError, RecursionError):
        raise ValueError("research_profile:report_not_proxy_only") from None
