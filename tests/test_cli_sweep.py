import json

import pytest
from typer.testing import CliRunner

from algua.cli.main import app

runner = CliRunner()


def _promote(args):
    return runner.invoke(app, args)


@pytest.fixture(autouse=True)
def _tmp(monkeypatch, tmp_path):
    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "r.db"))
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path))
    # A PIT universe covering the demo window: there is no non-PIT override (spec 2026-11-13).
    from algua.data.store import DataStore

    DataStore(tmp_path).ingest_universe(
        universe="demo_pit", symbols=["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"],
        effective_date="2021-01-01", as_of="2021-01-02T00:00:00+00:00", source="test")


def test_sweep_demo_emits_ranked():
    result = runner.invoke(app, ["backtest", "sweep", "cross_sectional_momentum", "--demo",
                                 "--start", "2022-01-01", "--end", "2023-12-31",
                                 "--param", "lookback=20,40", "--param", "construction.top_k=1,3",
                                 "--top", "2"])
    assert result.exit_code == 0, result.stdout
    d = json.loads(result.stdout)
    assert d["n_combos"] == 4
    assert len(d["ranked"]) == 2
    assert d["best"]["params"]
    assert d["rank_by"] == "mean_sharpe"


def test_sweep_combos_carry_no_holdout():
    # The OOS holdout is WITHHELD from sweep entirely: ranking is on window/stability, and
    # exposing a per-combo holdout would let an agent SELECT on the holdout across combos (the
    # exact overfitting the breadth gate fights). It is revealed only by `research promote`.
    result = runner.invoke(app, ["backtest", "sweep", "cross_sectional_momentum", "--demo",
                                 "--start", "2022-01-01", "--end", "2023-12-31",
                                 "--param", "lookback=20,40", "--param", "construction.top_k=1,3"])
    assert result.exit_code == 0, result.stdout
    d = json.loads(result.stdout)
    assert d["ranked"]
    for entry in d["ranked"]:
        assert "holdout" not in entry
        assert "stability" in entry  # ranking signal is still present


def test_sweep_of_unregistered_strategy_still_records_breadth():
    # Breadth is keyed by NAME, so a sweep BEFORE registration still records (closes the leak
    # where a run sweeps broadly first, then registers to reset its breadth).
    result = runner.invoke(app, ["backtest", "sweep", "cross_sectional_momentum", "--demo",
                                 "--start", "2022-01-01", "--end", "2023-12-31",
                                 "--param", "lookback=20,40"])
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["recorded_breadth"] == {"n_combos": 2, "cumulative": 2}


def test_pre_registration_sweep_breadth_used_by_promote():
    # Sweep broadly while UNREGISTERED, then register + backtest, then promote: the measured sum
    # must be used (provenance "measured").
    sweep = runner.invoke(app, ["backtest", "sweep", "cross_sectional_momentum", "--demo",
                                "--start", "2022-01-01", "--end", "2023-12-31",
                                "--param", "lookback=20,40", "--param", "construction.top_k=1,3"])
    assert sweep.exit_code == 0, sweep.stdout
    assert json.loads(sweep.stdout)["recorded_breadth"] == {"n_combos": 4, "cumulative": 4}

    backtested = runner.invoke(app, ["backtest", "run", "cross_sectional_momentum", "--demo",
                                     "--start", "2022-01-01", "--end", "2023-12-31", "--register"])
    assert backtested.exit_code == 0, backtested.stdout

    promote = _promote(["research", "promote", "cross_sectional_momentum", "--demo",
                                  "--start", "2022-01-01", "--end", "2023-12-31",
                                  "--min-holdout-sharpe", "-100", "--min-holdout-return", "-100",
                                  "--universe", "demo_pit"])
    assert promote.exit_code == 0, promote.stdout
    payload = json.loads(promote.stdout)
    assert payload["breadth_provenance"] == "measured"
    assert payload["n_funnel"] == 4


def _promote_to_backtested_with_breadth():
    """Shared setup for the promote tests below: measure breadth, register+backtest, assign family.

    Returns the base `research promote` args (sans --summary) for a PIT run that passes the
    (relaxed-threshold) gate against the demo provider.
    """
    sweep = runner.invoke(app, ["backtest", "sweep", "cross_sectional_momentum", "--demo",
                                "--start", "2022-01-01", "--end", "2023-12-31",
                                "--param", "lookback=20,40", "--param", "construction.top_k=1,3"])
    assert sweep.exit_code == 0, sweep.stdout
    backtested = runner.invoke(app, ["backtest", "run", "cross_sectional_momentum", "--demo",
                                     "--start", "2022-01-01", "--end", "2023-12-31", "--register"])
    assert backtested.exit_code == 0, backtested.stdout
    return ["research", "promote", "cross_sectional_momentum", "--demo",
            "--start", "2022-01-01", "--end", "2023-12-31",
            "--min-holdout-sharpe", "-100", "--min-holdout-return", "-100",
            "--universe", "demo_pit"]


def test_promote_full_emits_deep_diagnostics():
    # The single-use holdout is per-DB, so a full and a summary promote can't share a window in
    # one test; assert the FULL surface here and the SUMMARY surface in the next test (#349).
    base = _promote_to_backtested_with_breadth()
    res = _promote(base)
    assert res.exit_code == 0, res.stdout
    payload = json.loads(res.stdout)
    # full output is unchanged: deep gate diagnostics present, no summary marker
    assert "dsr_confidence" in payload and "haircut_would_have_blocked" in payload
    assert "dsr_trial_sr_var_ann" in payload
    assert "summary" not in payload


def test_promote_summary_drops_deep_diagnostics():
    base = _promote_to_backtested_with_breadth()
    res = _promote(base + ["--summary"])
    assert res.exit_code == 0, res.stdout
    payload = json.loads(res.stdout)
    # summary drops the deep dsr_*/shadow-audit fields
    assert "dsr_confidence" not in payload and "haircut_would_have_blocked" not in payload
    assert "dsr_trial_sr_var_ann" not in payload and "own_lifetime_combos" not in payload
    # keeps the decision essence + marker
    assert payload["summary"] is True and payload["ok"] is True
    assert "promoted" in payload and "checks" in payload and "passed" in payload
    assert payload["strategy"] == "cross_sectional_momentum"


def test_sweep_of_registered_strategy_records_breadth():
    assert runner.invoke(app, ["registry", "add", "cross_sectional_momentum"]).exit_code == 0
    result = runner.invoke(app, ["backtest", "sweep", "cross_sectional_momentum", "--demo",
                                 "--start", "2022-01-01", "--end", "2023-12-31",
                                 "--param", "lookback=20,40", "--param", "construction.top_k=1,3"])
    assert result.exit_code == 0, result.stdout
    recorded = json.loads(result.stdout)["recorded_breadth"]
    assert recorded == {"n_combos": 4, "cumulative": 4}

    # A second sweep accumulates the cumulative family total.
    result2 = runner.invoke(app, ["backtest", "sweep", "cross_sectional_momentum", "--demo",
                                  "--start", "2022-01-01", "--end", "2023-12-31",
                                  "--param", "lookback=20,40"])
    assert json.loads(result2.stdout)["recorded_breadth"] == {"n_combos": 2, "cumulative": 6}


def test_sweep_requires_param():
    result = runner.invoke(app, ["backtest", "sweep", "cross_sectional_momentum", "--demo"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["ok"] is False


def test_sweep_malformed_param_is_json_error():
    result = runner.invoke(app, ["backtest", "sweep", "cross_sectional_momentum", "--demo",
                                 "--param", "lookback"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["ok"] is False


def test_sweep_requires_data_source():
    result = runner.invoke(app, ["backtest", "sweep", "cross_sectional_momentum",
                                 "--param", "lookback=20,40"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["ok"] is False


def test_sweep_top_zero_is_json_error():
    result = runner.invoke(app, ["backtest", "sweep", "cross_sectional_momentum", "--demo",
                                 "--param", "lookback=20,40", "--top", "0"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["ok"] is False
