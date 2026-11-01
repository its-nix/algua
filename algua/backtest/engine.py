from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import date, datetime
from math import isfinite

import numpy as np
import pandas as pd
import vectorbt as vbt

from algua.backtest.context import ContextInputs
from algua.backtest.decision_path import _decision_weights_fast_or_loop
from algua.backtest.delisting import DelistingExitError, DelistingRecord, apply_delisting_exits
from algua.backtest.errors import BacktestError
from algua.backtest.grid import adj_grid
from algua.backtest.metrics import portfolio_metrics
from algua.backtest.pit_view import (
    _assert_fundamentals_shape,
    _assert_news_shape,
    _static_operating_view,
)
from algua.backtest.result import BacktestResult, config_hash
from algua.backtest.run_inputs import RunInputBundle, capture_run_inputs
from algua.backtest.stamps import runtime_stamps
from algua.contracts.model_types import normalize_as_of
from algua.contracts.strategy_interface import uses_context_interface
from algua.contracts.types import (
    DataProvider,
    FundamentalsProvider,
    NewsProvider,
)
from algua.strategies.base import LoadedStrategy

_SUPPORTED_CADENCES = {"1d"}  # this slice rebalances on every daily bar only

# Residual-position tolerance for the post-delisting-exit guarantee.
POSITION_EPS = 1e-9


def fetch_symbols(
    strategy: LoadedStrategy, universe_by_date: Mapping[date, Collection[str]] | None
) -> list[str]:
    """Symbols to fetch bars for.

    Static mode: the strategy's declared universe. PIT mode: the UNION of every symbol ever
    effective across the membership timeline — so price data exists for any ever-member, including
    membership active at `start` that derives from a snapshot dated before it. (The wiring layer
    already restricts the timeline to snapshots effective <= end_date.)
    """
    if universe_by_date is None:
        return strategy.universe
    union: set[str] = set()
    for members in universe_by_date.values():
        union.update(members)
    return sorted(union)


def adj_open_grid(bars: pd.DataFrame) -> pd.DataFrame:
    """The ADJUSTED-open execution grid (issue #383): raw `open` scaled by the SAME per-bar
    adjustment ratio that maps raw close -> adj_close, so it is to adj_close exactly what raw open
    is to raw close.

        adj_open[t] = open[t] * (adj_close[t] / close[t])

    Splits and dividends scale a whole bar uniformly, so this preserves `adj_open/adj_close ==
    open/close` and is the correct next-bar-open reference in the backtest's adjusted frame. Shares
    `adj_grid`'s (timestamp x symbol) index/columns EXACTLY, so it is a drop-in fill-price grid that
    leaves holdout_window / the #192 single-use holdout identity / PIT masking / the returns index
    untouched — only the price VALUES change.

    Fail-safe cells: any bar where `close <= 0`, `open <= 0`, either is NaN, or the ratio is
    non-finite (inf/-inf/NaN) yields a NaN adj_open — an untradeable bar that `from_orders` treats
    as a no-fill, identical to a missing bar. So a corrupt OHLC row can never inject a bogus fill
    price (it can only decline to fill)."""
    wide = bars.reset_index().pivot(index="timestamp", columns="symbol", values="open").sort_index()
    close = bars.reset_index().pivot(
        index="timestamp", columns="symbol", values="close"
    ).sort_index()
    adj_close = adj_grid(bars)
    open_ = wide.to_numpy(dtype="float64")
    close_ = close.to_numpy(dtype="float64")
    adjc = adj_close.to_numpy(dtype="float64")
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where((close_ > 0) & np.isfinite(close_), adjc / close_, np.nan)
        adj_open = np.where((open_ > 0) & np.isfinite(open_), open_ * ratio, np.nan)
    adj_open[~np.isfinite(adj_open)] = np.nan  # inf/-inf ratios collapse to a no-fill cell
    return pd.DataFrame(adj_open, index=adj_close.index, columns=adj_close.columns)


def simulate(
    strategy: LoadedStrategy,
    provider: DataProvider,
    start: datetime,
    end: datetime,
    *,
    universe_by_date: Mapping[date, Collection[str]] | None = None,
    fundamentals_provider: FundamentalsProvider | None = None,
    news_provider: NewsProvider | None = None,
    delisting_records: Mapping[str, list[DelistingRecord]] | None = None,
    assume_terminal_last_close: bool = False,
    _run_inputs: RunInputBundle | None = None,
    initial_cash: float | None = None,
) -> tuple[vbt.Portfolio, pd.DataFrame, list[dict]]:
    """Fetch bars, compute pre-lag decision weights through the canonical loop or parity-guarded
    fast path, enforce shared risk checks, then apply the t->t+1 shift and delisting-aware exit.
    Returns (portfolio, executed-weights, forced-exits); initial_cash can pin replay capital.
    The shift lives ONLY here — the panel fn (like the loop) returns DECISION-time weights, never
    executable ones.

    This public simulation step is shared by run()/walk_forward(); metrics are computed separately.
    A held-into-gap symbol is realized through `delisting_records`, or fails closed unless the
    human-only `assume_terminal_last_close` relaxation is active.

    Point-in-time universe (`universe_by_date`): when provided, bars are fetched for the UNION of
    all ever-effective members and the per-bar decision is masked to as-of-t membership (see
    `_decision_weights`). `None` is the original static behavior — fetch the declared universe."""
    cadence = strategy.execution.rebalance_frequency.lower()
    if cadence not in _SUPPORTED_CADENCES:
        raise BacktestError(
            f"rebalance_frequency {strategy.execution.rebalance_frequency!r} not supported; "
            f"this slice rebalances daily only ({sorted(_SUPPORTED_CADENCES)})"
        )
    run_inputs = _run_inputs or capture_run_inputs(
        strategy,
        provider,
        fetch_symbols(strategy, universe_by_date),
        start,
        end,
        fundamentals_provider=fundamentals_provider,
        news_provider=news_provider,
        include_provenance=False,
    )
    bars = run_inputs.bars()
    if bars.empty:
        raise BacktestError("provider returned no bars for the universe/period")

    # A fixed-per-run model is PIT-safe only if it predates the whole evaluated period. Enforce at
    # the shared simulate boundary and normalize both timestamps to UTC (#376).
    if strategy.config.needs_model:
        assert strategy.config.model_ref is not None
        first_bar = pd.Timestamp(bars.index.min())
        first_bar_utc = (
            first_bar.tz_localize("UTC") if first_bar.tzinfo is None
            else first_bar.tz_convert("UTC")
        )
        try:
            training_as_of = normalize_as_of(strategy.config.model_ref.training_as_of)
        except (ValueError, TypeError) as exc:
            raise BacktestError(
                f"strategy {strategy.name!r}: model "
                f"{strategy.config.model_ref.name!r} v{strategy.config.model_ref.version} has an "
                f"unparseable training_as_of {strategy.config.model_ref.training_as_of!r} "
                f"(fail closed): {exc}"
            ) from exc
        if training_as_of > first_bar_utc:
            raise BacktestError(
                f"strategy {strategy.name!r}: model {strategy.config.model_ref.name!r} "
                f"v{strategy.config.model_ref.version} has training_as_of "
                f"{strategy.config.model_ref.training_as_of} AFTER the first decision bar "
                f"{first_bar_utc.date().isoformat()} — that model saw future data (look-ahead); "
                f"refusing to backtest (fail closed)"
            )

    adj = adj_grid(bars)

    if universe_by_date is None:
        # Project static runs to the operating universe; PIT keeps its per-bar as-of mask (#208).
        bars, adj = _static_operating_view(strategy, bars, adj)

    fundamentals = run_inputs.fundamentals()
    if fundamentals is not None:
        _assert_fundamentals_shape(fundamentals)

    news = run_inputs.news()
    if news is not None:
        _assert_news_shape(news)

    context_inputs = (
        ContextInputs(
            first_decision_ts=pd.Timestamp(adj.index[0]),
            bars_snapshot_id=run_inputs.bars_snapshot_id,
            fundamentals_snapshot_id=run_inputs.fundamentals_snapshot_id,
            news_snapshot_id=run_inputs.news_snapshot_id,
        )
        if uses_context_interface(strategy.strategy_interface)
        else None
    )
    weights = _decision_weights_fast_or_loop(
        strategy, bars, adj,
        universe_by_date=universe_by_date, fundamentals=fundamentals, news=news,
        context_inputs=context_inputs,
    )

    lag = strategy.execution.decision_lag_bars
    weights_eff = weights.shift(lag).fillna(0.0)

    # `adj` remains the date-index/holdout truth; only the contract-selected fill values change.
    exec_grid = adj_open_grid(bars) if strategy.execution.fill_price == "open" else adj

    try:
        # terminal_price_grid=adj pins the delisting `assume_terminal_last_close` fallback to the
        # last adj_CLOSE (a delisting is a close-of-book realization, not an open fill) regardless
        # of the ordinary fill basis; the ordinary (non-terminal) fill cells come from exec_grid.
        adj_exec, weights_exec, forced_exits = apply_delisting_exits(
            exec_grid, weights_eff, delisting_records,
            assume_terminal_last_close=assume_terminal_last_close,
            terminal_price_grid=adj,
        )
    except DelistingExitError as exc:
        raise BacktestError(str(exc)) from exc

    extra: dict[str, object] = {"call_seq": "auto"} if forced_exits else {}
    if initial_cash is not None:
        if isinstance(initial_cash, bool) or not isfinite(initial_cash) or initial_cash <= 0:
            raise BacktestError("initial_cash must be finite and positive")
        extra["init_cash"] = initial_cash
    pf = vbt.Portfolio.from_orders(
        close=adj_exec,
        size=weights_exec,
        size_type="targetpercent",
        cash_sharing=True,
        group_by=True,
        freq="1D",
        fees=run_inputs.execution_fees,
        slippage=run_inputs.execution_slippage,
        **extra,
    )

    if forced_exits:
        positions = pf.assets()
        for fe in forced_exits:
            sym = fe["symbol"]
            bar = pd.Timestamp(fe["bar"])
            after = positions[sym].loc[positions.index >= bar]
            if bool((after.abs() > POSITION_EPS).any()):
                raise BacktestError(
                    f"delisting exit for {sym} left a residual position after {fe['bar']}"
                )
        returns = pf.returns()
        if not bool(np.isfinite(returns.fillna(0.0)).all()):
            raise BacktestError("non-finite returns after delisting exits")

    return pf, weights_exec, forced_exits


# build_portfolio is the explicit public alias of the simulation step. walk_forward and
# sweep import this (not a private helper).
build_portfolio = simulate


def run(
    strategy: LoadedStrategy,
    provider: DataProvider,
    start: datetime,
    end: datetime,
    *,
    seed: int | None = None,
    universe_by_date: Mapping[date, Collection[str]] | None = None,
    universe_name: str | None = None,
    universe_snapshots: list[dict[str, str]] | None = None,
    fundamentals_provider: FundamentalsProvider | None = None,
    news_provider: NewsProvider | None = None,
    delisting_records: Mapping[str, list[DelistingRecord]] | None = None,
    delisting_snapshot: str | None = None,  # surfaced in BacktestResult provenance (#212)
    assume_terminal_last_close: bool = False,
) -> BacktestResult:
    run_inputs = capture_run_inputs(
        strategy,
        provider,
        fetch_symbols(strategy, universe_by_date),
        start,
        end,
        fundamentals_provider=fundamentals_provider,
        news_provider=news_provider,
        include_provenance=True,
    )
    pf, weights_eff, forced_exits = simulate(
        strategy, provider, start, end,
        universe_by_date=universe_by_date, fundamentals_provider=fundamentals_provider,
        news_provider=news_provider,
        delisting_records=delisting_records,
        assume_terminal_last_close=assume_terminal_last_close,
        _run_inputs=run_inputs,
    )
    metrics = portfolio_metrics(
        pf, weights_eff,
        fees=run_inputs.execution_fees, slippage=run_inputs.execution_slippage,
    )
    stamps = runtime_stamps()
    prov = run_inputs.provenance(seed)
    # Surface daily returns for downstream correlation analysis (#222 Task 7).
    returns = pf.returns()
    if not bool(np.isfinite(returns.fillna(0.0)).all()):
        returns_series: pd.Series | None = None  # fail-closed: non-finite returns not surfaced
    else:
        returns_series = returns
    return BacktestResult(
        strategy=strategy.name,
        metrics=metrics,
        config_hash=config_hash(strategy),
        timeframe="1d",
        period={"start": start.date().isoformat(), "end": end.date().isoformat()},
        code_hash=stamps["code_hash"],
        dependency_hash=stamps["dependency_hash"],
        universe_name=universe_name,
        universe_snapshots=universe_snapshots,
        fundamentals_snapshot=run_inputs.fundamentals_snapshot_id,
        news_snapshot=(run_inputs.news_snapshot_id if strategy.config.needs_news else None),
        # Model provenance (#376): the pinned model_ref (name/version/digest/training_as_of/
        # provenance_digest) is stamped HERE, at the same mandatory boundary as the run, so a
        # programmatic caller cannot get an unstamped result. None for non-model strategies.
        model_ref=(
            strategy.config.model_ref.as_dict()
            if strategy.config.needs_model and strategy.config.model_ref is not None
            else None
        ),
        delisting_snapshot=delisting_snapshot,
        forced_exits=forced_exits,
        returns=returns_series,
        **prov,
    )
