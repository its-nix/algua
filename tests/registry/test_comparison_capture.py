"""Capture actual public windows and effective execution; never read a private result."""
from __future__ import annotations

import json
from dataclasses import replace

from algua.backtest.walkforward import walk_forward
from algua.data.serve import StoreBackedProvider
from algua.primitives.timeparse import utc
from algua.registry.db import registry_conn
from algua.registry.runs import record_walk_forward_run
from algua.registry.store import SqliteStrategyRepository
from algua.strategies.loader import load_strategy
from tests.test_run_provenance import END, NAME, START, snapshot

INPUTS = {"delisting_snapshot": None, "assume_terminal_last_close": False}


def test_actual_execution_and_protocol_are_recorded_from_the_used_inputs(tmp_path, monkeypatch):
    store, rec = snapshot(tmp_path, monkeypatch)
    result = walk_forward(load_strategy(NAME), StoreBackedProvider(store, rec.snapshot_id),
                          utc(START), utc(END), windows=2)
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        run = record_walk_forward_run(repo, NAME, result, research_inputs=INPUTS)
        config = json.loads(repo.get_run(run)["config_json"])
    captured = config["public_window_record"]["context"]
    assert captured["protocol"] == "continuous_portfolio_public_windows"
    assert captured["windows"] == [{k: w[k] for k in ("start", "end", "n_bars")}
                                   for w in result.window_metrics]
    assert captured["public_interval"] == {
        "start": result.window_metrics[0]["start"], "end": result.window_metrics[-1]["end"],
        "n_windows": 2, "n_bars": sum(w["n_bars"] for w in result.window_metrics)}
    assert "oos" not in captured
    assert captured["holdout_frac"] == result.holdout_frac
    assert captured["embargo"] == result.embargo
    execution = result.execution_semantics
    assert execution is not None and captured["execution"] == execution
    assert "execution_semantics" not in result.to_dict()
    assert execution["decision_lag_bars"] == 1
    assert execution["fill_basis"] == execution["valuation_basis"] == "adjusted_open"
    assert execution["sizing"] == "targetpercent"
    assert execution["cash_sharing"] is True
    assert execution["initial_cash"] == 100.0
    assert execution["symbol_order"] == ["AAPL", "AMZN", "GOOGL", "MSFT", "NVDA"]
    assert execution["simulation"]["size_granularity"] == "nan"
    assert execution["simulation"]["call_seq"] == "default"
    assert execution["simulation"]["val_price"] == "+inf"
    assert execution["simulation"]["engine"] == "numba"
    assert execution["simulation"]["vectorbt_version"] == "1.0.0"
    assert "holdout_returns" not in json.dumps(config)


def test_producer_to_persisted_comparable_cohort_and_legacy_absence(tmp_path, monkeypatch):
    """Synthetic bars/declared tier engineering control, with zero invented gate lineage."""
    from algua.data.research_provenance import DataTier, ProvenanceDeclaration
    from algua.registry.strategy_board import strategy_board_payload

    store, original = snapshot(tmp_path, monkeypatch)
    bars = store.read_bars(original.snapshot_id).reset_index().rename(columns={"timestamp": "ts"})
    rec = store.ingest_bars(
        provider="fixture", symbols=list(original.symbols), start=START, end=END,
        as_of="2025-01-01T00:00:00+00:00", source="synthetic-producer-control-not-market",
        frame=bars, provenance=ProvenanceDeclaration(DataTier.PILOT_REAL_PROXY, "fixture/v1"))
    seed = load_strategy(NAME)
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        results = []
        for lookback in (20, 60):
            name = f"fixture_lb{lookback}"
            strategy = replace(seed, config=seed.config.model_copy(update={
                "name": name, "params": {"lookback": lookback}, "feature_lookback": lookback}))
            identity = repo.add(name)
            result = walk_forward(strategy, StoreBackedProvider(store, rec.snapshot_id),
                                  utc(START), utc(END), windows=2, embargo=60)
            record_walk_forward_run(repo, name, result, strategy_id=identity.id,
                                     research_inputs=INPUTS)
            results.append((identity.id, result))
        default = strategy_board_payload(repo)
        payload = strategy_board_payload(repo, research=True)
        comparisons = [r["evidence"]["comparison"] for r in payload["rows"]]
        assert all(c["status"] == "COMPARABLE" for c in comparisons), comparisons
        assert comparisons[0]["cohort_id"] == comparisons[1]["cohort_id"]
        assert comparisons[0]["context"]["execution"] == results[0][1].execution_semantics
        assert strategy_board_payload(repo) == default
        identity, original_result = results[0]
        legacy = replace(original_result, execution_semantics=None)
        latest_id = record_walk_forward_run(repo, legacy.strategy, legacy, strategy_id=identity,
                                            research_inputs=INPUTS)
        latest = strategy_board_payload(repo, research=True)["rows"][0]
        assert latest["latest_research"]["run_id"] == latest_id
        assert latest["evidence"]["comparison"]["status"] == "UNKNOWN"
        assert latest["evidence"]["comparison"]["reasons"] == ["research_record_absent"]
        assert conn.execute("SELECT count(*) FROM holdout_evaluations").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM gate_evaluations").fetchone()[0] == 0
