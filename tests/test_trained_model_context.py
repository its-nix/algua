"""Pinned synthetic trained-model serving and actual canonical CLI/loader controls."""
from __future__ import annotations

import contextlib
import copy
import importlib
import io
import json
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from algua.contracts.model_types import ModelHandle
from algua.data.store import DataStore
from algua.features.price_linear import FrozenPriceLinear, return_features
from algua.features.price_linear_context import score_price_linear, validate_proxy_model
from algua.models import get_version_with_bytes
from algua.research.multimodal_context import build_as_of_context
from tests.test_cli_model_training import invoke, make_source


@pytest.fixture
def trained(tmp_path, monkeypatch):
    data, path, request, record, dates, calendar = make_source(tmp_path, monkeypatch, count=40)
    code, payload = invoke("train-linear", "context-model", "--request", str(path))
    assert code == 0, payload
    version, raw = get_version_with_bytes("context-model", 1, root=data / "models")
    return data, request, record, dates, calendar, version, raw


def context(trained, *, count=8, universe=("AAA", "BBB")):
    data, _, record, dates, _, version, _ = trained
    bars = DataStore(data).read_bars(record.snapshot_id)
    bars = bars[(bars.index >= dates[16]) & (bars.index <= dates[16 + count - 1])]
    return build_as_of_context(decision_ts=dates[16 + count - 1].to_pydatetime(),
        first_decision_ts=dates[16].to_pydatetime(), universe=universe, bars=bars,
        bars_snapshot_id=record.snapshot_id, required_features={"bars"},
        model_refs={version.name: version.as_ref()}, model_registry_root=data / "models")


def test_actual_pin_frozen_serve_parity_and_no_fit(trained, monkeypatch):
    import algua.training.price_linear as numerical

    def forbidden(*args, **kwargs):
        pytest.fail("serving reached a training function")

    monkeypatch.setattr(numerical, "fit_price_linear", forbidden)
    view = context(trained)
    wide = view.features["bars"].frame.reset_index().pivot(
        index="timestamp", columns="symbol", values="adj_close").reindex(columns=view.universe)
    expected = FrozenPriceLinear.from_json(trained[-1]).predict(
        return_features(wide.iloc[-6:]).xs(wide.index[-1], level="event_label"))
    actual = score_price_linear(view, model_key="context-model")
    pd.testing.assert_series_equal(actual, expected.rename(None), check_names=False)
    assert list(actual.index) == ["AAA", "BBB"]
    assert (score_price_linear(context(trained, count=5), model_key="context-model") == 0).all()


def test_missing_untrained_symbol_refuses_without_zero_substitution(trained):
    with pytest.raises(ValueError, match="subset"):
        score_price_linear(context(trained, universe=("AAA", "BBB", "UNTRAINED")),
                           model_key="context-model")


@pytest.mark.parametrize("path,value", [
    (("mode",), "verified_pit"), (("request", "extra"), 1),
    (("fit", "fitted_observations"), True),
    (("fit", "train_end"), "2023-01-01T00:00:00Z"),
    (("cutoff", "max_y_close"), "2020-01-01T00:00:00Z"),
    (("cutoff", "training_as_of"), "NaT"),
    (("clocks", "unknown"), 1), (("source", "extra"), 1),
])
def test_profile_is_closed_and_cutoff_report_bound(trained, path, value):
    version, raw = trained[-2:]
    report = copy.deepcopy(version.eval_report)
    target = report
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        validate_proxy_model(ModelHandle(replace(version, eval_report=report), raw))


def cli(*args):
    from algua.cli.main import main

    output = io.StringIO()
    with contextlib.redirect_stdout(output), pytest.raises(SystemExit) as stopped:
        main(list(args))
    return stopped.value.code, json.loads(output.getvalue())


@contextlib.contextmanager
def authored(version, *, name="tmp_trained_proxy_context", construction="top_k_equal_weight"):
    import algua.strategies.momentum as family

    path = Path(family.__path__[0]) / f"{name}.py"
    dotted = f"algua.strategies.momentum.{name}"
    assert not path.exists()
    path.write_text(
        "from algua.contracts.model_types import ModelRef\n"
        "from algua.contracts.types import ExecutionContract\n"
        "from algua.features.price_linear_context import score_price_linear\n"
        "from algua.strategies.base import StrategyConfig\n"
        f"REF = ModelRef(**{version.as_ref().as_dict()!r})\n"
        "STRATEGY_INTERFACE = 'context_v1'\n"
        f"CONFIG = StrategyConfig(name={name!r}, universe=['AAA','BBB'], params={{}},\n"
        " execution=ExecutionContract(rebalance_frequency='1d', warmup_bars=5,\n"
        "  decision_lag_bars=1,\n"
        "  fees=0.0005, slippage=0.0005, target_gross_utilization=0.95,\n"
        "  max_weight_per_symbol=1.0),\n"
        f" construction={construction!r}, construction_params={{'top_k':1}},\n"
        " needs_model=True, model_ref=REF, feature_lookback=5)\n"
        "def score(context):\n"
        " return score_price_linear(context, model_key=REF.name)\n", encoding="utf-8")
    importlib.invalidate_caches()
    try:
        yield name
    finally:
        path.unlink()
        sys.modules.pop(dotted, None)
        importlib.invalidate_caches()


def test_actual_authored_loader_canonical_warmup_lag_costs_and_record(trained):
    from algua.backtest.context import ContextInputs
    from algua.backtest.decision_path import _decision_weights
    from algua.backtest.engine import simulate
    from algua.backtest.grid import adj_grid
    from algua.data.serve import StoreBackedProvider
    from algua.strategies.loader import load_strategy

    data, _, record, dates, _, version, _ = trained
    start, end = dates[16].to_pydatetime(), (dates[-1] + pd.Timedelta(days=1)).to_pydatetime()
    with authored(version) as name:
        strategy = load_strategy(name)
        assert strategy.model_handle.version.as_ref() == version.as_ref()
        provider = StoreBackedProvider(DataStore(data), record.snapshot_id)
        bars = provider.get_bars(["AAA", "BBB"], start, end, "1d")
        decisions = _decision_weights(strategy, bars, adj_grid(bars), context_inputs=ContextInputs(
            first_decision_ts=dates[16], bars_snapshot_id=record.snapshot_id,
            fundamentals_snapshot_id=None, news_snapshot_id=None))
        portfolio, executed, _ = simulate(strategy, provider, start, end)
        assert (decisions.iloc[:5] == 0).all().all()
        assert decisions.iloc[5].abs().sum() > 0
        assert (executed.iloc[:6] == 0).all().all()
        assert executed.iloc[6].abs().sum() > 0
        assert portfolio.orders.records_readable.iloc[0]["Timestamp"] >= dates[22]
        code, result = cli("backtest", "run", name, "--snapshot", record.snapshot_id,
                           "--start", start.date().isoformat(), "--end", end.date().isoformat())
        assert code == 0, result
        assert result["model_ref"] == version.as_ref().as_dict()
        assert result["snapshot_id"] == record.snapshot_id and result["seed"] is None
        assert result["execution_costs"]["fees"] == result["execution_costs"]["slippage"] == 0.0005
        with sqlite3.connect(data / "algua.db") as conn:
            row = conn.execute(
                "SELECT kind,snapshot_id,components,config_json FROM runs").fetchone()
            assert row[0:2] == ("backtest", record.snapshot_id)
            assert version.name in row[2]
            assert json.loads(row[3])["run_provenance"]["bars"]["snapshot_id"] == record.snapshot_id


def test_first_decision_model_guard_runs_before_warmup_and_artifact_tamper_refuses(trained):
    data, request, record, dates, _, version, raw = trained
    with authored(version, name="tmp_proxy_refusals") as name:
        code, result = cli("backtest", "run", name, "--snapshot", record.snapshot_id,
                           "--start", request["train_start"], "--end", dates[-1].date().isoformat())
        assert code == 1 and "first decision" in result["error"]
        artifact = data / "models" / version.name / "v1" / "artifact.bin"
        artifact.write_bytes(raw + b" ")
        code, result = cli("backtest", "run", name, "--snapshot", record.snapshot_id,
                           "--start", dates[16].date().isoformat(),
                           "--end", dates[-1].date().isoformat())
        assert code == 1 and result["ok"] is False


def test_cold_serve_import_cannot_reach_training_or_io_layers():
    script = '''
import importlib.abc,sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("algua.training", "algua.features.scaling_fit", "algua.models",
            "algua.registry", "algua.data", "algua.cli", "mlflow")):
            raise AssertionError(fullname)
sys.meta_path.insert(0,Block())
from algua.features.price_linear_context import score_price_linear
assert callable(score_price_linear)
'''
    result = subprocess.run([sys.executable, "-I", "-c", script], capture_output=True,
                            text=True, timeout=20)
    assert result.returncode == 0, result.stderr
