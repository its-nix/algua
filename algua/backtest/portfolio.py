"""Bounded reference book replay through the real backtest simulator.

Prefix replay is intentionally quadratic, bounded to about two years on a small explicit book.
It derives actual holdings including fills/costs before each allocation, rather than calling last
target "current weights". No runtime dispatch, registry access or second fill/accounting model.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import vectorbt as vbt

from algua.backtest import engine
from algua.backtest.errors import BacktestError
from algua.backtest.run_inputs import capture_run_inputs
from algua.backtest.stamps import runtime_stamps
from algua.calendar.market_calendar import MarketCalendar
from algua.contracts.strategy_interface import LEGACY_INTERFACE
from algua.contracts.types import DataProvider, ExecutionContract
from algua.portfolio.allocator import PortfolioConstraints, RiskEstimate, allocate_targets
from algua.risk.limits import validate_decision_weights
from algua.strategies.base import LoadedStrategy, StrategyConfig, config_hash

MAX_REPLAY_SESSIONS = 512
MAX_REPLAY_SYMBOLS = 8
MAX_REPLAY_SLEEVES = 8
MAX_REPLAY_WORK_UNITS = 2_000_000


def _work_units(sessions: int, symbols: int, sleeve_symbols: int) -> int:
    # Engine prefix grids + expanding sleeve history rows + the final engine grid. This is a
    # deterministic workload bound, not a wall-clock guarantee for arbitrary strategy callables.
    return (symbols + sleeve_symbols) * sessions * (sessions + 1) // 2 + symbols * sessions


def _window_sessions(start: datetime, end: datetime) -> int:
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    if pd.isna(start_ts) or pd.isna(end_ts):
        raise BacktestError("portfolio replay requires valid start/end")
    if start_ts.tzinfo is None or end_ts.tzinfo is None:
        raise BacktestError("portfolio replay requires tz-aware start/end")
    if start_ts >= end_ts:
        raise BacktestError("portfolio replay requires start before end")
    # Count UTC-midnight bars inside [start, end), including for non-UTC/intraday bounds.
    first = start_ts.tz_convert("UTC").ceil("D")
    last = end_ts.tz_convert("UTC").ceil("D") - timedelta(days=1)
    try:
        count = len(MarketCalendar().sessions_in_range(first.date(), last.date()))
    except ValueError as exc:
        raise BacktestError(f"portfolio replay window outside session calendar: {exc}") from exc
    if not 1 <= count <= MAX_REPLAY_SESSIONS:
        raise BacktestError(f"portfolio replay requires 1..{MAX_REPLAY_SESSIONS} sessions")
    return count


@dataclass(frozen=True)
class PortfolioSimulation:
    portfolio: vbt.Portfolio
    decision_weights: pd.DataFrame
    current_weights: pd.DataFrame
    executed_weights: pd.DataFrame
    provenance: dict[str, Any]


@dataclass
class _CapturedBars:
    frame: pd.DataFrame

    def get_bars(self, symbols: list[str], start: datetime, end: datetime,
                 timeframe: str) -> pd.DataFrame:
        return self.frame.loc[(self.frame.index >= start) & (self.frame.index < end)
                              & self.frame.symbol.isin(symbols)].copy(deep=True)


def _replay_strategy(
    symbols: list[str], execution: ExecutionContract, decisions: dict[pd.Timestamp, pd.Series],
) -> LoadedStrategy:
    # Decisions have already passed construction/overlays/capacity and the account rails.
    # Avoid applying utilization or warmup a second time to these final target weights.
    replay_execution = replace(
        execution, warmup_bars=0, target_gross_utilization=1.0, capacity=None,
    )
    return LoadedStrategy(
        StrategyConfig(name="portfolio_replay", universe=symbols, execution=replay_execution,
                       construction="equal_weight_positive"),
        construct_fn=lambda weights, view, params: weights,
        signal_fn=lambda view, params: decisions.get(view.index.max(), pd.Series(dtype="float64")),
    )


def _validate_members(
    strategies: Mapping[str, LoadedStrategy], execution: ExecutionContract,
) -> None:
    if execution.decision_lag_bars != 1 or execution.rebalance_frequency.lower() != "1d":
        raise BacktestError("portfolio reference replay supports daily lag=1 only")
    if not execution.allow_fractional:
        raise BacktestError("portfolio reference replay requires fractional account sizing")
    if execution.allow_short or execution.capacity is not None:
        raise BacktestError("portfolio replay requires long-only account contract without capacity")
    for name, strategy in strategies.items():
        cfg = strategy.config
        if (strategy.strategy_interface != LEGACY_INTERFACE or cfg.needs_fundamentals
                or cfg.needs_news or cfg.needs_model):
            raise BacktestError(f"{name}: portfolio replay supports bars-only legacy strategies")
        if (strategy.execution.decision_lag_bars != execution.decision_lag_bars
                or strategy.execution.fill_price != execution.fill_price
                or strategy.execution.rebalance_frequency.lower() != "1d"):
            raise BacktestError(f"{name}: incompatible execution timing")


def simulate_portfolio(
    strategies: Mapping[str, LoadedStrategy],
    budgets: Mapping[str, float],
    constraints: PortfolioConstraints,
    provider: DataProvider,
    start: datetime,
    end: datetime,
    *,
    execution: ExecutionContract,
    initial_cash: float,
    symbols: Sequence[str],
    risk_estimates: Mapping[str, Sequence[RiskEstimate]] | None = None,
    seed: int | None = None,
) -> PortfolioSimulation:
    """Evaluate explicitly qualified sleeves against one pinned complete static-universe fixture.

    Explicit account execution supplies costs; no qualification or cost inference. Unsupported
    sidecars/PIT membership/delistings/longer lags fail closed, rather than approximate them.
    Results include the original snapshot, captured content digest, configs, constraints, risk
    sources, seed and runtime stamps. Session/symbol/sleeve and aggregate work limits are checked
    before fetching data. Prefix replay reuses the canonical engine without a continuation API;
    its finite grid/history bound does not bound arbitrary sleeve computation time. This is an
    offline research simulation, not promotion or elapsed forward-test evidence.
    """
    if len(strategies) > MAX_REPLAY_SLEEVES:
        raise BacktestError(f"portfolio replay supports at most {MAX_REPLAY_SLEEVES} sleeves")
    if len(symbols) > MAX_REPLAY_SYMBOLS:
        raise BacktestError(f"portfolio replay supports at most {MAX_REPLAY_SYMBOLS} symbols")
    _validate_members(strategies, execution)
    if (not symbols or isinstance(symbols, str)
            or any(not isinstance(s, str) or not s.strip() for s in symbols)):
        raise BacktestError("explicit nonempty string symbols required, including all-cash replay")
    symbols = sorted(set(symbols))
    if any(not set(s.universe) <= set(symbols) for s in strategies.values()):
        raise BacktestError("portfolio symbols must include every supplied strategy universe")
    requested_sessions = _window_sessions(start, end)
    sleeve_symbols = sum(len(s.universe) for s in strategies.values())
    requested_work = _work_units(requested_sessions, len(symbols), sleeve_symbols)
    if requested_work > MAX_REPLAY_WORK_UNITS:
        raise BacktestError(f"portfolio replay work exceeds {MAX_REPLAY_WORK_UNITS} units")
    if (isinstance(initial_cash, bool) or not math.isfinite(initial_cash) or initial_cash <= 0):
        raise BacktestError("initial_cash must be finite and positive")
    decisions: dict[pd.Timestamp, pd.Series] = {}
    replay = _replay_strategy(symbols, execution, decisions)
    snapshot_id = getattr(provider, "snapshot_id", None)
    captured = capture_run_inputs(replay, provider, symbols, start, end, include_provenance=True)
    if captured.bars_snapshot_id is None:
        raise BacktestError("portfolio replay requires a pinned bars snapshot_id")
    if snapshot_id != captured.bars_snapshot_id:
        raise BacktestError("bars snapshot_id changed during capture")
    bars = captured.bars()
    if len(bars) > requested_sessions * len(symbols):
        raise BacktestError("provider returned more bars than the bounded replay workload")
    bars = bars.sort_index(kind="stable")
    if not isinstance(bars.index, pd.DatetimeIndex) or str(bars.index.tz) != "UTC":
        raise BacktestError("portfolio replay requires UTC daily timestamps")
    if bool(((bars.index < start) | (bars.index >= end)).any()):
        raise BacktestError("provider returned bars outside the half-open replay window")
    dates = bars.index.unique().sort_values()
    if not 1 <= len(dates) <= MAX_REPLAY_SESSIONS:
        raise BacktestError(f"portfolio replay requires 1..{MAX_REPLAY_SESSIONS} sessions")
    calendar = MarketCalendar()
    expected = calendar.sessions_in_range(dates[0].date(), dates[-1].date())
    if list(dates.date) != expected or any(t != t.normalize() for t in dates):
        raise BacktestError("portfolio replay requires consecutive daily session bars")
    for t in dates:
        rows = bars.loc[bars.index == t]
        if sorted(rows.symbol) != symbols:
            raise BacktestError("portfolio replay requires complete unique bars each session")
        if not all(math.isfinite(v) and v > 0 for v in rows.adj_close):
            raise BacktestError("portfolio replay requires finite positive marks")
    source = _CapturedBars(bars)
    currents: dict[pd.Timestamp, pd.Series] = {}
    for i, t in enumerate(dates):
        prefix_end = (t + timedelta(days=1)).to_pydatetime()
        # The decision at t is still absent: lag>=1 guarantees it cannot affect holdings at t.
        pf, _, _ = engine.simulate(replay, source, start, prefix_end, initial_cash=initial_cash)
        shares = pf.assets().iloc[-1]
        marks = bars.loc[bars.index == t].set_index("symbol").adj_close.reindex(symbols)
        values = shares.reindex(symbols) * marks
        equity = float(pf.cash().iloc[-1]) + float(values.sum())
        if not math.isfinite(equity) or equity <= 0:
            raise BacktestError("non-positive portfolio equity")
        current = values / equity
        currents[t] = current
        sleeve_targets = {}
        for name in sorted(strategies):
            strategy = strategies[name]
            view = bars.loc[(bars.index <= t) & bars.symbol.isin(strategy.universe)].copy(deep=True)
            warmup = max(strategy.execution.warmup_bars, execution.warmup_bars)
            weights = (strategy.target_weights(view) if i >= warmup
                       else pd.Series(dtype="float64"))
            validate_decision_weights(weights, strategy.execution, name,
                                      allowed_symbols=strategy.universe)
            sleeve_targets[name] = weights
        target = allocate_targets(sleeve_targets, budgets, constraints, current_weights=current,
                                  as_of=t.to_pydatetime(), risk_estimates=risk_estimates)
        validate_decision_weights(target, execution, "portfolio", allowed_symbols=symbols)
        decisions[t] = target
    pf, executed, _ = engine.simulate(replay, source, start, end, initial_cash=initial_cash)
    config = {
        "strategies": {n: config_hash(s) for n, s in sorted(strategies.items())},
        "budgets": dict(sorted(budgets.items())), "constraints": asdict(constraints),
        "execution": asdict(execution), "initial_cash": initial_cash, "symbols": symbols,
        "risk_estimates": {n: [dict(asdict(r), as_of=r.as_of.isoformat())
                               for r in sorted(rs, key=lambda r: (r.as_of, r.volatility, r.source))]
                           for n, rs in sorted((risk_estimates or {}).items())},
    }
    provenance = {
        **captured.provenance(seed), **runtime_stamps(), **config,
        "config_hash": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
        "bars_digest": hashlib.sha256(captured.bars_payload).hexdigest(),
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "replay": {
            "method": "canonical_engine_prefix", "scope": "research_only",
            "sessions": len(dates), "symbols": len(symbols), "sleeves": len(strategies),
            "work_units": _work_units(len(dates), len(symbols), sleeve_symbols),
            "requested_sessions": requested_sessions, "requested_work_units": requested_work,
            "limits": {"sessions": MAX_REPLAY_SESSIONS, "symbols": MAX_REPLAY_SYMBOLS,
                       "sleeves": MAX_REPLAY_SLEEVES, "work_units": MAX_REPLAY_WORK_UNITS},
        },
    }
    return PortfolioSimulation(
        pf, pd.DataFrame.from_dict(decisions, orient="index").reindex(index=dates, columns=symbols)
        .fillna(0.0).astype("float64"),
        pd.DataFrame.from_dict(currents, orient="index").reindex(index=dates, columns=symbols)
        .fillna(0.0).astype("float64"), executed, provenance,
    )
