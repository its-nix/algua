"""Synthetic observed-price math only; no data source, registry, strategy or temporal pin."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest


def linear_process(n=45):
    """Independent generative oracle: next return has declared raw-feature coefficients."""
    columns = {}
    for symbol, initial in [("AAA", [0.03, -0.02, 0.01, 0.04, -0.01]),
                            ("BBB", [-0.01, 0.02, 0.04, -0.03, 0.01])]:
        prices = [100.0]
        for change in initial:
            prices.append(prices[-1] * (1 + change))
        while len(prices) < n:
            one = prices[-1] / prices[-2] - 1
            five = prices[-1] / prices[-6] - 1
            change = 0.001 - 0.2 * one + 0.15 * five
            prices.append(prices[-1] * (1 + change))
        columns[symbol] = prices[:n]
    return pd.DataFrame(columns, index=pd.date_range("2024-01-01", periods=n, tz="UTC"))


def fit(prices, **kwargs):
    from algua.training.price_linear import fit_price_linear

    return fit_price_linear(prices, train_start=kwargs.pop("train_start", prices.index[0]),
                            train_end=kwargs.pop("train_end", prices.index[-1]), **kwargs)


def test_known_linear_process_recovers_forecast_without_another_fit_formula():
    from algua.features.price_linear import return_features

    prices = linear_process()
    result = fit(prices, l2=1e-9)
    scaler = result.model.scaler
    raw_coefficients = np.array(result.model.coefficients) / np.array([
        scaler.params[name]["std"] for name in ("return_1", "return_5")])
    raw_intercept = result.model.intercept - sum(raw_coefficients[i] * scaler.params[name]["mean"]
        for i, name in enumerate(("return_1", "return_5")))
    np.testing.assert_allclose(raw_coefficients, [-0.2, 0.15], atol=1e-8)
    assert raw_intercept == pytest.approx(0.001, abs=1e-10)
    features = return_features(prices).loc[(prices.index[5:-2], slice(None)), :]
    expected = [prices.loc[date + pd.Timedelta(days=1), symbol] / prices.loc[date, symbol] - 1
                for date, symbol in features.index]
    np.testing.assert_allclose(result.model.predict(features), expected, atol=1e-10)


def test_exact_window_label_censoring_scaler_scope_and_counts():
    from algua.features.price_linear import return_features

    prices = linear_process(20)
    result = fit(prices, train_start=prices.index[7], train_end=prices.index[13])
    report = result.report
    assert report.window_events == 6 and report.consumed_events == 11
    assert report.warmup_observations == 0 and report.unlabelled_observations == 2
    assert report.fitted_observations == 10 and report.candidate_observations == 12
    assert report.symbols == ("AAA", "BBB")
    assert report.max_x_event == prices.index[11].isoformat()
    assert report.max_y_event == prices.index[12].isoformat()
    assert result.model.max_x_event == result.model.scaler.fit_max_timestamp == report.max_x_event
    assert result.model.max_y_event == report.max_y_event
    eligible = return_features(prices).loc[(prices.index[7:12], slice(None)), :]
    for column in eligible:
        assert result.model.scaler.params[column]["mean"] == pytest.approx(eligible[column].mean())
        assert result.model.scaler.params[column]["std"] == pytest.approx(
            eligible[column].std(ddof=0))


def test_warmup_and_unlabelled_exclusions_are_disjoint():
    result = fit(linear_process(10), train_end=pd.Timestamp("2024-01-09", tz="UTC"))
    report = result.report
    assert (report.candidate_observations, report.warmup_observations,
            report.unlabelled_observations, report.fitted_observations) == (16, 10, 2, 4)
    assert report.candidate_observations == (report.warmup_observations
        + report.unlabelled_observations + report.fitted_observations)


@pytest.mark.parametrize("bad", [np.nan, np.inf, -1.0, 0.0, True, "bad", 2 + 3j])
def test_future_append_and_container_promotion_do_not_change_fit(bad):
    prices = linear_process(20)
    end = prices.index[15]
    base = fit(prices.iloc[:15], train_start=prices.index[6], train_end=end)
    future = prices.iloc[15:].copy()
    future["AAA"] = bad
    expanded = pd.concat([prices.iloc[:15], future])
    repeated = fit(expanded, train_start=prices.index[6], train_end=end)
    assert repeated.model.to_json() == base.model.to_json()
    assert repeated.report == base.report


def test_unused_ancient_history_is_not_validated_or_counted():
    prices = linear_process(30)
    original = fit(prices, train_start=prices.index[15], train_end=prices.index[25])
    changed = prices.astype(object)
    changed.iloc[:10] = "unused"
    repeated = fit(changed, train_start=prices.index[15], train_end=prices.index[25])
    assert repeated.model.to_json() == original.model.to_json()
    assert repeated.report == original.report


@pytest.mark.parametrize("bad", [np.nan, np.inf, -1, 0, True, "100", 1 + 2j])
def test_consumed_bad_values_refuse_without_fill_or_silent_row_drop(bad):
    prices = linear_process(25).astype(object)
    prices.iloc[7, 0] = bad
    with pytest.raises(ValueError):
        fit(prices, train_start=prices.index[10], train_end=prices.index[20])


@pytest.mark.parametrize("l2", [True, False, 0, -1, np.nan, np.inf, "0.1", None])
def test_ridge_penalty_has_explicit_finite_positive_numeric_type(l2):
    with pytest.raises(ValueError):
        fit(linear_process(), l2=l2)


@pytest.mark.parametrize("start,end", [
    ("2024-01-01", "2024-02-01T00:00:00Z"),
    ("NaT", "2024-02-01T00:00:00Z"),
    ("2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z"),
    ("2024-02-01T00:00:00Z", "2024-01-01T00:00:00Z"),
    (False, "2024-02-01T00:00:00Z"),
])
def test_fit_window_requires_finite_aware_ordered_bounds(start, end):
    with pytest.raises(ValueError):
        fit(linear_process(), train_start=start, train_end=end)


def test_degenerate_and_insufficient_samples_fail_closed():
    with pytest.raises(ValueError):
        fit(linear_process(7))
    flat = linear_process(15) * 0 + 100.0
    with pytest.raises(ValueError):
        fit(flat)
    with pytest.raises(ValueError, match="warmup=6.*unlabelled=0.*fitted=0"):
        fit(linear_process(5), train_end=pd.Timestamp("2024-01-04", tz="UTC"))


def test_positive_ridge_handles_correlated_nonconstant_features():
    prices = pd.DataFrame({"AAA": [100.0, 110.0] * 10},
                          index=pd.date_range("2024-01-01", periods=20, tz="UTC"))
    result = fit(prices)
    assert np.isfinite(result.model.coefficients).all()
    assert result.model.coefficients[0] == pytest.approx(result.model.coefficients[1])


def test_irregular_labels_mean_next_observation_not_calendar_day():
    prices = linear_process(20)
    prices.index = pd.date_range("2024-01-01", periods=20, freq="3D", tz="UTC")
    result = fit(prices)
    assert result.report.max_x_event == prices.index[-3].isoformat()
    assert result.report.max_y_event == prices.index[-2].isoformat()


def test_fit_result_is_detached_recursively_immutable_and_has_no_policy_clocks():
    from dataclasses import FrozenInstanceError, asdict

    prices = linear_process()
    result = fit(prices)
    before = result.model.to_json()
    prices.iloc[:] = 1
    assert result.model.to_json() == before
    with pytest.raises(FrozenInstanceError):
        result.report.fitted_observations = 0
    assert isinstance(result.report.symbols, tuple)
    assert "training_as_of" not in json.dumps(asdict(result.report))
    assert "known_at" not in json.dumps(asdict(result.report))


def test_fit_does_not_call_io(monkeypatch):
    from pathlib import Path

    from algua.training.price_linear import fit_price_linear

    prices = linear_process()

    def forbidden(*args, **kwargs):
        pytest.fail("pure synthetic fit attempted IO")

    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(pd, "read_csv", forbidden)
    monkeypatch.setattr(pd, "read_pickle", forbidden)
    result = fit_price_linear(prices, train_start=prices.index[0], train_end=prices.index[-1])
    assert result.report.fitted_observations > 0


def test_fit_preserves_symbol_order_and_is_deterministic():
    prices = linear_process()[["BBB", "AAA"]]
    first, second = fit(prices), fit(prices)
    assert first.model.to_json() == second.model.to_json()
    assert first.report == second.report
    assert first.report.symbols == ("BBB", "AAA")


@pytest.mark.parametrize("start,end", [("2024-02-28T00:00:00Z", "2024-03-01T00:00:00Z"),
                                      ("2023-01-01T00:00:00Z", "2023-02-01T00:00:00Z")])
def test_window_without_observations_refuses(start, end):
    with pytest.raises(ValueError):
        fit(linear_process(), train_start=start, train_end=end)
