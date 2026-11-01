"""Capture actual protocol at the recorder; never fill absent execution semantics from config."""
from __future__ import annotations

import json

from algua.backtest.walkforward import walk_forward
from algua.data.serve import StoreBackedProvider
from algua.primitives.timeparse import utc
from algua.registry.db import registry_conn
from algua.registry.runs import record_walk_forward_run
from algua.registry.store import SqliteStrategyRepository
from algua.strategies.loader import load_strategy
from tests.test_run_provenance import END, NAME, START, snapshot


def test_actual_execution_and_protocol_are_recorded_from_the_used_inputs(
    tmp_path, monkeypatch,
):
    store, rec = snapshot(tmp_path, monkeypatch)
    result = walk_forward(load_strategy(NAME), StoreBackedProvider(store, rec.snapshot_id),
                          utc(START), utc(END), windows=2)
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        run = record_walk_forward_run(repo, NAME, result)
        config = json.loads(repo.get_run(run)["config_json"])
    captured = config["comparison_context"]
    assert captured["protocol"] == "continuous_portfolio_tail_holdout"
    assert captured["windows"] == [{k: w[k] for k in ("start", "end", "n_bars")}
                                   for w in result.window_metrics]
    assert captured["oos"] == {k: result.holdout_metrics[k] for k in ("start", "end", "n_bars")}
    assert captured["holdout_frac"] == result.holdout_frac
    assert captured["embargo"] == result.embargo
    execution = result.execution_semantics
    assert execution is not None
    assert captured["execution"] == execution == result.to_dict()["execution_semantics"]
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


def _display_lineage(repo, result, strategy_id, sibling):
    """Synthetic pointer orchestration only; never evaluate or grant a gate verdict."""
    from algua.registry.runs import provenance_of, walk_forward_metrics

    h = result.holdout_metrics
    now = "2026-01-01T00:00:00+00:00"
    evaluation = repo.connection.execute(
        "INSERT INTO holdout_evaluations (strategy_id,data_source,snapshot_id,period_start,"
        "period_end,holdout_frac,config_hash,created_at,committed_at,holdout_start,holdout_end) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (strategy_id, result.data_source, result.snapshot_id,
        result.period["start"], result.period["end"], result.holdout_frac, result.config_hash,
        now, now, h["start"], h["end"]),
    ).lastrowid
    holdout = repo.connection.execute(
        "INSERT INTO holdout_returns (holdout_evaluation_id,strategy_id,holdout_start,"
        "holdout_end,n_bars,returns_blob,bar_dates_blob,created_at) VALUES (?,?,?,?,?,?,?,?)",
        (evaluation, strategy_id, h["start"], h["end"], h["n_bars"], b"", b"", now),
    ).lastrowid
    return repo.record_run("gate", result.strategy, strategy_id=strategy_id,
                           derived_from=[sibling], series_holdout_id=holdout,
                           provenance=provenance_of(result) | {"code_hash": "artifact-closure"},
                           metrics=walk_forward_metrics(result), passed=None)


def test_producer_to_persisted_comparable_cohort_and_legacy_absence(tmp_path, monkeypatch):
    """Generated-bar/declared-tier contract fixture, separate from real-market acceptance runs."""
    from dataclasses import replace

    from algua.data.research_provenance import DataTier, ProvenanceDeclaration
    from algua.registry.strategy_board import strategy_board_payload

    store, original = snapshot(tmp_path, monkeypatch)
    bars = store.read_bars(original.snapshot_id).reset_index().rename(columns={"timestamp": "ts"})
    rec = store.ingest_bars(
        provider="fixture", symbols=list(original.symbols), start=START, end=END,
        as_of="2025-01-01T00:00:00+00:00", source="synthetic-producer-control-not-market",
        frame=bars, provenance=ProvenanceDeclaration(DataTier.PILOT_REAL_PROXY, "fixture/v1"),
    )
    seed = load_strategy(NAME)
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        results = []
        for lookback in (20, 60):
            name = f"fixture_lb{lookback}"
            strategy = replace(seed, config=seed.config.model_copy(update={
                "name": name, "params": {"lookback": lookback}, "feature_lookback": lookback,
            }))
            identity = repo.add(name)
            result = walk_forward(strategy, StoreBackedProvider(store, rec.snapshot_id),
                                  utc(START), utc(END), windows=2, embargo=60)
            sibling = record_walk_forward_run(repo, name, result, strategy_id=identity.id)
            _display_lineage(repo, result, identity.id, sibling)
            results.append((identity.id, result))
        default = strategy_board_payload(repo)
        payload = strategy_board_payload(repo, snapshot_evidence=lambda _: {})
        comparisons = [r["evidence"]["comparison"] for r in payload["rows"]]
        assert all(c["status"] == "COMPARABLE" for c in comparisons), comparisons
        assert comparisons[0]["cohort_id"] == comparisons[1]["cohort_id"]
        assert comparisons[0]["context"]["execution"] == results[0][1].execution_semantics
        assert strategy_board_payload(repo) == default
        # A newer result without producer evidence is legacy/unknown, never inferred or backfilled.
        identity, original_result = results[0]
        legacy = replace(original_result, execution_semantics=None)
        sibling = record_walk_forward_run(repo, legacy.strategy, legacy, strategy_id=identity)
        _display_lineage(repo, legacy, identity, sibling)
        latest = strategy_board_payload(repo, snapshot_evidence=lambda _: {})["rows"][0]
        assert latest["evidence"]["comparison"]["status"] == "UNKNOWN"
        assert latest["evidence"]["comparison"]["reasons"] == ["execution_context_absent"]
