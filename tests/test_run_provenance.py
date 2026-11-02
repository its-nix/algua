"""Engineering fixtures for captured research provenance; these are not real market bars."""
from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from algua.backtest._sample import SyntheticProvider
from algua.cli.main import app
from algua.data.research_provenance import DataTier, ProvenanceDeclaration
from algua.data.store import DataStore
from algua.primitives.timeparse import utc
from algua.registry.db import registry_conn
from algua.registry.run_views import run_detail_payload
from algua.registry.runs import record_walk_forward_run
from algua.registry.store import SqliteStrategyRepository
from algua.registry.strategy_board import strategy_board_payload

START, END = "2024-01-01", "2024-12-31"
NAME = "cross_sectional_momentum"
SYMBOLS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"]
COSTS = {
    "schema_version": "execution-costs/v1",
    "model": "vectorbt.from_orders",
    "fees": 0.0005,
    "fees_unit": "fraction_of_trade_notional_per_side",
    "slippage": 0.0005,
    "slippage_unit": "adverse_fill_price_fraction_per_side",
}


def snapshot(tmp_path, monkeypatch, *, declared=True):
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "registry.db"))
    store = DataStore(tmp_path / "data")
    frame = SyntheticProvider(seed=21).get_bars(SYMBOLS, utc(START), utc(END), "1d")
    frame = frame[frame.index < utc(END)]
    frame = frame.reset_index().rename(columns={"timestamp": "ts"})
    rec = store.ingest_bars(
        provider="fixture", symbols=SYMBOLS, start=START, end=END,
        as_of="2025-01-01T00:00:00+00:00", source="engineering-fixture", frame=frame,
        provenance=ProvenanceDeclaration(
            DataTier.SYNTHETIC_FIXTURE, "fixture/v1", ("synthetic_not_market_data",)
        ) if declared else None,
    )
    return store, rec


def test_cli_snapshot_result_and_persisted_run_keep_exact_inputs(tmp_path, monkeypatch):
    _store, rec = snapshot(tmp_path, monkeypatch)
    runner = CliRunner()
    args = ["backtest", "run", NAME, "--snapshot", rec.snapshot_id,
            "--start", START, "--end", END]
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.stdout
    result = json.loads(first.stdout)
    assert result["bars_provenance"] == rec.to_dict()
    assert result["execution_costs"] == COSTS
    assert result["snapshot_id"] == rec.snapshot_id
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        run = run_detail_payload(repo, repo.list_runs()[0]["id"])
    assert run["config_json"]["run_provenance"] == {
        "bars": rec.to_dict(), "execution_costs": COSTS,
    }
    second = runner.invoke(app, args)
    assert second.exit_code == 0, second.stdout
    assert json.loads(second.stdout) == result


@pytest.mark.parametrize("surface", ["walk-forward", "sweep"])
@pytest.mark.parametrize("summary", [False, True])
def test_windowed_cli_and_registry_preserve_shared_capture(tmp_path, monkeypatch, surface, summary):
    _store, rec = snapshot(tmp_path, monkeypatch)
    args = ["backtest", surface, NAME, "--snapshot", rec.snapshot_id,
            "--start", START, "--end", END, "--windows", "2"]
    if surface == "sweep":
        args += ["--param", "lookback=20,60"]
    if summary:
        args += ["--summary"]
    output = CliRunner().invoke(app, args)
    assert output.exit_code == 0, output.stdout
    result = json.loads(output.stdout)
    assert result["bars_provenance"] == rec.to_dict()
    assert result["execution_costs"] == COSTS
    assert "holdout_metrics" not in result
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        runs = [run_detail_payload(repo, r["id"]) for r in repo.list_runs()]
    for run in runs:
        assert run["config_json"]["run_provenance"] == {
            "bars": rec.to_dict(), "execution_costs": COSTS,
        }
    if surface == "sweep":
        assert len(runs) == 3
        assert result["n_combos"] == 2
        for trial in result.get("ranked", []):
            assert trial["bars_provenance"] == rec.to_dict()
            assert trial["execution_costs"] == COSTS


def test_board_reads_recorded_sibling_without_consulting_current_manifest(tmp_path, monkeypatch):
    from algua.backtest.walkforward import walk_forward
    from algua.data.serve import StoreBackedProvider
    from algua.registry.runs import provenance_of
    from algua.strategies.loader import load_strategy

    store, rec = snapshot(tmp_path, monkeypatch)
    wf = walk_forward(load_strategy(NAME), StoreBackedProvider(store, rec.snapshot_id),
                      utc(START), utc(END), windows=2)
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        strategy = repo.add(NAME)
        sibling = record_walk_forward_run(repo, NAME, wf, strategy_id=strategy.id)
        gate = repo.record_run("gate", NAME, strategy_id=strategy.id,
                               derived_from=[sibling], provenance=provenance_of(wf))
        default = strategy_board_payload(repo)
        # The actual gate writes an explicit sibling link; this fixture never promotes anything.
        store.manifest.path.write_text("changed after run\n")
        def no_manifest(_):
            pytest.fail("recorded provenance must not consult mutable manifest")
        board = strategy_board_payload(repo, snapshot_evidence=no_manifest)
        assert strategy_board_payload(repo) == default
    evidence = board["rows"][0]["evidence"]
    assert set(evidence) == {
        "run_id", "evaluation", "oos_interval", "snapshot_provenance", "comparison",
    }  # the shipped frontend parses these keys exactly
    assert evidence["run_id"] == gate
    assert evidence["snapshot_provenance"]["value"] == json.loads(
        rec.metadata.source_metadata["research_provenance"])
    assert board["rows"][0]["recorded_provenance"] == {
        "status": "VALID", "reason": None,
        "value": {"bars_snapshot_id": rec.snapshot_id,
                  "bars_content_hash": rec.content_hash, "execution_costs": COSTS},
    }
    assert evidence["comparison"]["observed_metric_sort_enabled"] is False
    assert evidence["comparison"]["status"] == "UNKNOWN"
    assert evidence["comparison"]["reasons"] == [
        "lineage_or_source_unavailable",
    ]  # recorded costs alone do not establish a comparable holdout


@pytest.mark.parametrize("surface", ["backtest", "sweep"])
def test_persisted_arbitrary_params_do_not_collide_with_disclosure(tmp_path, monkeypatch, surface):
    from dataclasses import replace

    from algua.backtest.engine import run
    from algua.backtest.sweep import sweep
    from algua.data.serve import StoreBackedProvider
    from algua.registry.runs import record_backtest_run, record_sweep_run
    from algua.strategies.loader import load_strategy

    store, rec = snapshot(tmp_path, monkeypatch)
    strategy = load_strategy(NAME)
    params = strategy.config.params | {"run_provenance": 17, "params": {"nested": [None, 3]}}
    strategy = replace(strategy, config=strategy.config.model_copy(update={"params": params}))
    provider = StoreBackedProvider(store, rec.snapshot_id)
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        if surface == "backtest":
            result = run(strategy, provider, utc(START), utc(END))
            run_id = record_backtest_run(repo, NAME, result, params=params)
            configs = [run_detail_payload(repo, run_id)["config_json"]]
            expected = [params]
        else:
            result = sweep(strategy, provider, utc(START), utc(END), windows=2,
                           grid={"run_provenance": [17, 23]})
            record_sweep_run(repo, NAME, result)
            configs = [run_detail_payload(repo, row["id"])["config_json"]
                       for row in repo.list_runs(kind="sweep_trial")][::-1]
            expected = [trial["params"] for trial in result.ranked]
        assert [config.get("params", config) for config in configs] == expected
        for config in configs:
            assert config["run_provenance"] == {"bars": rec.to_dict(), "execution_costs": COSTS}
