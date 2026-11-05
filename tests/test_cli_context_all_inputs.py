"""Synthetic all-input CLI mechanics; no real modalities, learned alpha or DL acceptance."""
from __future__ import annotations

import copy
import importlib
import json
import sqlite3
import sys
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

import algua.strategies.momentum as family
from algua.calendar.market_calendar import MarketCalendar
from algua.cli.main import app
from algua.config.settings import Settings
from algua.data.research_provenance import DataTier, ProvenanceDeclaration
from algua.data.store import DataStore
from algua.models import register
from algua.strategies.ml import model_linear_scores as linear


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "ledger.db"))
    store = DataStore(tmp_path / "data")
    dates = pd.DatetimeIndex(MarketCalendar().sessions_in_range(
        date(2024, 1, 2), date(2024, 1, 31))[:10], tz="UTC")
    bars = pd.DataFrame([
        {"ts": stamp, "symbol": symbol, "open": price, "high": price, "low": price,
         "close": price, "adj_close": price, "volume": 1000.}
        for i, stamp in enumerate(dates) for symbol in ("AAPL", "MSFT")
        for price in (100. * (1.01 ** i if symbol == "AAPL" else 1.),)
    ])
    news = pd.DataFrame([
        {"source": "SYNTHETIC_FIXTURE", "article_id": article, "symbols": ["AAPL"],
         "published_at": dates[0], "knowable_at": known, "headline": headline}
        for article, known, headline in (
            ("visible", dates[0], "positive"), ("future", dates[7], "neutral"))
    ])
    funds = pd.DataFrame([
        {"symbol": "AAPL", "fiscal_period_end": "2023-12-31", "metric": "fixture_score",
         "value": value, "knowable_at": known, "source": "SYNTHETIC_FIXTURE"}
        for known, value in ((dates[0], 1.), (dates[7], 0.))
    ])
    versions = []
    for raw in (linear.ARTIFACT_BYTES, _zero_aapl_coefficients()):
        versions.append(register("model_linear_scores", raw,
            training_snapshot_id=linear.TRAINING_SNAPSHOT_ID,
            training_as_of=linear.TRAINING_AS_OF, code_hash=None,
            hyperparameters=linear.HYPERPARAMETERS, seed=linear.SEED,
            eval_report=linear.EVAL_REPORT, root=store.data_dir / "models"))
    assert versions[0].as_ref() == linear.CONFIG.model_ref
    return tmp_path, store, dates, bars, news, funds, versions


def _zero_aapl_coefficients():
    model = json.loads(linear.ARTIFACT_BYTES)
    model["coefficients"]["AAPL"] = [0., 0.]
    return json.dumps(model, sort_keys=True).encode()


def _snapshots(inputs, change=None):
    _, store, dates, original_bars, original_news, original_funds, versions = inputs
    bars, news, funds = (frame.copy(deep=True)
                        for frame in (original_bars, original_news, original_funds))
    if change == "bars":
        bars.loc[bars.symbol == "AAPL", ["open", "high", "low", "close", "adj_close"]] *= .1
    elif change == "news":
        news.loc[news.article_id == "visible", "headline"] = "neutral"
    elif change == "fundamentals":
        funds.loc[funds.knowable_at == dates[0], "value"] = 0.
    elif change == "future":
        bars.loc[bars.ts > dates[6], ["open", "high", "low", "close", "adj_close"]] *= 1.5
        news.loc[news.article_id == "future", "headline"] = "positive"
        funds.loc[funds.knowable_at == dates[7], "value"] = 100.
    declaration = ProvenanceDeclaration(DataTier.SYNTHETIC_FIXTURE,
        "all-input-cli-fixture/v1", ("synthetic_not_market_data",))
    brec = store.ingest_bars(provider="fixture", symbols=["AAPL", "MSFT"],
        start=dates[0].date().isoformat(), end=(dates[-1].date() + timedelta(days=1)).isoformat(),
        as_of="2024-03-01T00:00:00Z", source="SYNTHETIC_FIXTURE", frame=bars,
        provenance=declaration)
    nrec = store.ingest_news(provider="fixture", as_of="2024-03-01T00:00:00Z", frame=news)
    frec = store.ingest_fundamentals(provider="fixture", symbols=["AAPL", "MSFT"],
        as_of="2024-03-01T00:00:00Z", source="SYNTHETIC_FIXTURE", frame=funds)
    return (brec.snapshot_id, nrec.snapshot_id, frec.snapshot_id,
            versions[1 if change == "model" else 0])


@contextmanager
def _authored(ref, case):
    name = "tmp_all_inputs_" + case
    path = Path(family.__path__[0]) / f"{name}.py"
    dotted = f"algua.strategies.momentum.{name}"
    assert not path.exists()
    path.write_text(
        "import pandas as pd\n"
        "from algua.contracts.model_types import ModelRef\n"
        "from algua.contracts.types import ExecutionContract\n"
        "from algua.strategies.base import StrategyConfig\n"
        "from algua.strategies.ml.model_linear_scores import signal as linear_score\n"
        f"REF=ModelRef(**{ref!r})\nSTRATEGY_INTERFACE='context_v1'\nOBSERVED=[]\n"
        f"CONFIG=StrategyConfig(name={name!r}, universe=['AAPL','MSFT'], params={{}},\n"
        " execution=ExecutionContract(rebalance_frequency='1d',warmup_bars=5,\n"
        " decision_lag_bars=1,fees=.0005,slippage=.0005,max_weight_per_symbol=1.),\n"
        " construction='top_k_equal_weight',construction_params={'top_k':1},\n"
        " needs_news=True,needs_fundamentals=True,needs_model=True,model_ref=REF,\n"
        " feature_lookback=5)\n"
        "def score(context):\n"
        " bars=context.features['bars'].frame\n news=context.features['news'].frame\n"
        " funds=context.features['fundamentals'].frame\n"
        " components=[float(bars.groupby('symbol').adj_close.last()['AAPL'])/100.,\n"
        " float(((news.symbol=='AAPL')&(news.headline=='positive')).sum()),\n"
        " float(funds.loc[funds.metric=='fixture_score','value'].sum()),\n"
        " 30.*linear_score(bars,{},context.models[REF.name])['AAPL']]\n"
        " scores=pd.Series({'AAPL':sum(components),'MSFT':3.5})\n"
        # Observation only: no production engine/scorer is mocked or replaced.
        " OBSERVED.append({'time':pd.Timestamp(context.decision_ts),\n"
        " 'components':components,'scores':scores.to_dict(),'bar_max':bars.index.max(),\n"
        " 'news_max':news.knowable_at.max(),'fund_max':funds.knowable_at.max()})\n"
        " return scores\n")
    importlib.invalidate_caches()
    try:
        yield name, importlib.import_module(dotted)
    finally:
        path.unlink(missing_ok=True)
        sys.modules.pop(dotted, None)
        importlib.invalidate_caches()


def _run(inputs, case="base", ref_override=None):
    root, _, dates, *_ = inputs
    bid, nid, fid, version = _snapshots(inputs, case)
    ref = version.as_ref().as_dict() if ref_override is None else ref_override
    output = root / f"{case}.parquet"
    with _authored(ref, case) as (name, module):
        result = CliRunner().invoke(app, ["backtest", "run", name, "--snapshot", bid,
            "--news-snapshot", nid, "--fundamentals-snapshot", fid,
            "--start", dates[0].date().isoformat(),
            "--end", (dates[-1].date() + timedelta(days=1)).isoformat(),
            "--emit-series", str(output)])
        payload = json.loads(result.stdout)
        if ref_override is not None:
            assert result.exit_code == 1 and payload["ok"] is False
            assert not module.OBSERVED and not output.exists()
            assert not (root / "ledger.db").exists()
            return payload
        assert result.exit_code == 0, result.output
        assert payload["model_ref"] == ref and payload["snapshot_id"] == bid
        assert payload["news_snapshot"] == nid and payload["fundamentals_snapshot"] == fid
        assert payload["seed"] is None
        assert payload["execution_costs"]["fees"] == payload["execution_costs"]["slippage"] == .0005
        with sqlite3.connect(root / "ledger.db") as conn:
            row = conn.execute("SELECT snapshot_id,news_snapshot,fundamentals_snapshot,components "
                               "FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        assert row[:3] == (bid, nid, fid) and json.loads(row[3]) == [ref]
        observed = copy.deepcopy(module.OBSERVED)
        for decision in observed:
            assert decision["bar_max"] <= decision["time"]
            assert decision["news_max"] <= decision["time"]
            assert decision["fund_max"] <= decision["time"]
        return observed, pd.read_parquet(output)


def test_each_required_input_changes_real_cli_scores_and_portfolio_path(inputs):
    baseline, returns = _run(inputs)
    assert baseline[0]["time"] == inputs[2][5]
    assert returns.ret.iloc[:6].eq(0).all()  # Five warmup bars plus the required next-bar lag.
    for component, modality in enumerate(("bars", "news", "fundamentals", "model")):
        changed, changed_returns = _run(inputs, modality)
        assert baseline[0]["scores"]["AAPL"] > 3.5 > changed[0]["scores"]["AAPL"]
        assert baseline[0]["components"][component] != changed[0]["components"][component]
        for other in set(range(4)) - {component}:
            assert baseline[0]["components"][other] == pytest.approx(
                changed[0]["components"][other])
        assert returns.ret.iloc[7] > changed_returns.ret.iloc[7] + .005


def test_future_bars_and_knowable_sidecars_cannot_change_earlier_cli_scores(inputs):
    baseline, returns = _run(inputs)
    changed, changed_returns = _run(inputs, "future")
    assert baseline[:2] == changed[:2]  # Decisions5/6 precede future bar/revision7.
    pd.testing.assert_frame_equal(returns.iloc[:7], changed_returns.iloc[:7])
    for component in (0, 1, 2):
        assert baseline[2]["components"][component] != changed[2]["components"][component]


@pytest.mark.parametrize("fault", ["missing_version", "mismatched_digest"])
def test_all_input_cli_refuses_unavailable_or_mismatched_exact_pin_before_recording(inputs, fault):
    ref = inputs[-1][0].as_ref().as_dict()
    ref["version" if fault == "missing_version" else "digest"] = (
        999 if fault == "missing_version" else "f" * 16)
    payload = _run(inputs, fault, ref_override=ref)
    assert "model" in payload["error"].lower()
