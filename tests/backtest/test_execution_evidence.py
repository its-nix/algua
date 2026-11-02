"""Numerical parity and detached effective-input disclosure; no gate or capital effects."""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
import vectorbt as vbt

from algua.backtest.engine import simulate
from algua.backtest.execution_evidence import recorded_execution
from algua.contracts.types import ExecutionContract
from tests.test_backtest_costs import (
    END,
    START,
    _FrameProvider,
    _long_flip_bars,
    _rotate_strategy,
)


@pytest.mark.parametrize("basis,lag", [("open", 1), ("close", 2)])
def test_disclosure_preserves_original_order_inputs_and_numerical_bytes(monkeypatch, basis, lag):
    original = vbt.Portfolio.from_orders
    explicit = ("close", "size", "size_type", "cash_sharing", "group_by", "freq", "fees",
                "slippage", "init_cash")
    calls = []

    def observe(**kwargs):
        # The exact original engine call, without the now-explicit detached defaults.
        reference = original(**{k: kwargs[k] for k in explicit})
        actual = original(**kwargs)
        assert actual.orders.records_arr.tobytes() == reference.orders.records_arr.tobytes()
        assert actual.returns().to_numpy().tobytes() == reference.returns().to_numpy().tobytes()
        pd.testing.assert_frame_equal(actual.assets(), reference.assets())
        calls.append(kwargs)
        return actual

    monkeypatch.setattr(vbt.Portfolio, "from_orders", observe)
    strategy = _rotate_strategy(ExecutionContract(
        rebalance_frequency="1d", decision_lag_bars=lag, fill_price=basis, allow_fractional=False,
    ))
    bars = _long_flip_bars()
    bars["open"], bars["low"], bars["adj_close"] = 8.0, 8.0, 5.0
    pf, _, _ = simulate(strategy, _FrameProvider(bars), START, END, initial_cash=321.0)
    assert (pf.close == (4.0 if basis == "open" else 5.0)).all().all()
    assert (pf.assets() % 1 != 0).any().any()
    evidence = recorded_execution(pf)
    assert evidence["decision_lag_bars"] == lag
    assert evidence["fill_basis"] == evidence["valuation_basis"] == f"adjusted_{basis}"
    assert evidence["sizing"] == "targetpercent"  # requested allow_fractional is not applied here
    assert evidence["simulation"]["size_granularity"] == "nan"
    assert evidence["initial_cash"] == 321.0
    assert evidence["symbol_order"] == ["A", "B"]
    assert len(calls) == 1


def test_metadata_uses_same_detached_settings_given_to_the_numerical_call(monkeypatch):
    original = vbt.Portfolio.from_orders
    strategy = _rotate_strategy(ExecutionContract(rebalance_frequency="1d", fill_price="open"))
    monkeypatch.setitem(vbt.settings.portfolio, "init_cash", 234.0)
    monkeypatch.setitem(vbt.settings.portfolio, "fixed_fees", 0.25)

    def mutate_globals_after_detachment(**kwargs):
        assert kwargs["fixed_fees"] == 0.25
        assert kwargs["init_cash"] == 234.0
        # A numerical callback cannot make recorded effective settings follow a later global value.
        monkeypatch.setitem(vbt.settings.portfolio, "fixed_fees", 999.0)
        monkeypatch.setitem(vbt.settings.portfolio, "init_cash", 999.0)
        actual = original(**kwargs)
        strategy.config = strategy.config.model_copy(update={
            "execution": replace(strategy.execution, decision_lag_bars=2, fill_price="close"),
        })
        return actual

    monkeypatch.setattr(vbt.Portfolio, "from_orders", mutate_globals_after_detachment)
    pf, _, _ = simulate(strategy, _FrameProvider(_long_flip_bars()), START, END)
    evidence = recorded_execution(pf)
    assert evidence["simulation"]["fixed_fees"] == 0.25
    assert evidence["initial_cash"] == 234.0
    assert evidence["decision_lag_bars"] == 1
    assert evidence["fill_basis"] == evidence["valuation_basis"] == "adjusted_open"
    evidence["decision_lag_bars"] = 99
    assert recorded_execution(pf)["decision_lag_bars"] == 1


def test_array_settings_keep_numerical_execution_but_do_not_claim_supported_comparison(monkeypatch):
    monkeypatch.setitem(vbt.settings.portfolio, "fixed_fees", np.array([0.0, 0.0]))
    pf, _, _ = simulate(_rotate_strategy(ExecutionContract(rebalance_frequency="1d")),
                        _FrameProvider(_long_flip_bars()), START, END)
    assert np.isfinite(pf.returns()).all()
    assert recorded_execution(pf) is None
