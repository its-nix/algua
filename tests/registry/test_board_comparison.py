"""Synthetic metadata controls: no gate qualification or economic claims."""
from __future__ import annotations

import json
from dataclasses import replace

import pytest

from algua.registry.db import registry_conn
from algua.registry.store import SqliteStrategyRepository
from algua.registry.strategy_board import strategy_board_payload
from tests.test_run_provenance import COSTS, END, NAME, START, snapshot


def context():
    return {
        "schema_version": "research-comparison/v1",
        "protocol": "continuous_portfolio_tail_holdout",
        "metrics": "net_daily_returns_252_rf0_ddof1_compounded_floored_drawdown/v1",
        "timeframe": "1d", "period_start": START, "period_end": END,
        "holdout_frac": 0.2, "embargo": 20,
        "windows": [{"start": "2024-01-02", "end": "2024-05-01", "n_bars": 90},
                    {"start": "2024-05-02", "end": "2024-09-01", "n_bars": 90}],
        "oos": {"start": "2024-10-01", "end": "2024-12-30", "n_bars": 50},
        "execution": {
            "schema_version": "replay-execution/v1", "decision_lag_bars": 1,
            "fill_basis": "adjusted_close", "valuation_basis": "adjusted_close",
            "sizing": "targetpercent",
            "cash_sharing": True, "initial_cash": 100.0,
            "symbol_order": ["AAPL", "MSFT"],
            "rebalance": "every_daily_bar", "price_units": "vendor_adjusted",
            "simulation": {
                "fixed_fees": 0.0, "min_size": 1e-8, "max_size": "+inf",
                "size_granularity": "nan", "reject_prob": 0.0, "lock_cash": False,
                "allow_partial": True, "raise_reject": False, "log": False,
                "price": "+inf", "val_price": "+inf", "call_seq": "default",
                "ffill_val_price": True, "update_value": False, "seed": None,
                "fillna_close": True, "direction": "both", "freq": "1D", "group_by": True,
                "engine": "numba", "initial_cash_mode": "fixed", "vectorbt_version": "1.0.0",
            },
        },
    }


def pair(tmp_path, monkeypatch):
    _store, rec = snapshot(tmp_path, monkeypatch)
    # Fixtures explicitly declare pilot metadata on generated bars solely to test the reader.
    from algua.provenance.research import PILOT_PROXY_LIMITATIONS
    from algua.provenance.snapshot import compute_snapshot_id

    source = dict(rec.metadata.source_metadata)
    declaration = json.loads(source["research_provenance"])
    declaration["data_tier"] = "pilot_real_proxy"
    declaration["limitations"] = sorted(PILOT_PROXY_LIMITATIONS)
    source["research_provenance"] = json.dumps(declaration, sort_keys=True, separators=(",", ":"))
    metadata = replace(rec.metadata, source_metadata=source)
    sid = compute_snapshot_id(metadata, rec.content_hash)
    bars = replace(rec, snapshot_id=sid, metadata=metadata).to_dict()
    conn_context = registry_conn()
    conn = conn_context.__enter__()
    repo = SqliteStrategyRepository(conn)
    sibling, gate = record_pair(repo, NAME, bars)
    return conn_context, repo, sibling, gate


def record_pair(repo, name, bars):
    """Persist an independent synthetic identity with its own WF and holdout pointers."""
    conn = repo.connection
    sid = bars["snapshot_id"]
    strategy = repo.add(name)
    prov = {"snapshot_id": sid, "timeframe": "1d", "period_start": START, "period_end": END,
            "data_source": "StoreBackedProvider", "config_hash": "config",
            "dependency_hash": "deps"}
    metrics = {"sharpe_oos": 0.0, "total_return_oos": -0.1, "max_drawdown_oos": -0.2,
               "n_obs_oos": 50, "ann_vol_oos": 0.2}
    sibling = repo.record_run("walk_forward", name, strategy_id=strategy.id,
                              provenance=prov | {"code_hash": "runtime-source"}, metrics=metrics,
                              config={"run_provenance": {"bars": bars, "execution_costs": COSTS},
                                      "comparison_context": context()})
    evaluation = conn.execute(
        "INSERT INTO holdout_evaluations (strategy_id,data_source,snapshot_id,period_start,"
        "period_end,holdout_frac,config_hash,created_at,committed_at,holdout_start,holdout_end) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (strategy.id, "StoreBackedProvider", sid, START, END,
        0.2, "config", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00",
        "2024-10-01", "2024-12-30"),
    ).lastrowid
    holdout = conn.execute(
        "INSERT INTO holdout_returns (holdout_evaluation_id,strategy_id,holdout_start,"
        "holdout_end,n_bars,returns_blob,bar_dates_blob,created_at) VALUES (?,?,?,?,?,?,?,?)",
        (evaluation, strategy.id, "2024-10-01", "2024-12-30", 50, b"", b"",
         "2026-01-01T00:00:00+00:00"),
    ).lastrowid
    gate = repo.record_run("gate", name, strategy_id=strategy.id,
                           derived_from=[sibling],
                           provenance=prov | {"code_hash": "artifact-closure"},
                           metrics=metrics, series_holdout_id=holdout)
    return sibling, gate


def comparison(repo):
    return strategy_board_payload(repo, snapshot_evidence=lambda _: pytest.fail("no manifest"))[
        "rows"][0]["evidence"]["comparison"]


def test_independently_validated_record_can_join_observed_cohort(tmp_path, monkeypatch):
    cm, repo, _, _ = pair(tmp_path, monkeypatch)
    try:
        before = repo.connection.total_changes
        result = comparison(repo)
        assert result["status"] == "COMPARABLE", result
        assert result["observed_metric_sort_enabled"] is True
        assert result["context"]["oos"] == context()["oos"]
        assert result["context"]["execution_costs"] == COSTS
        assert result["context"]["data_tier"] == "pilot_real_proxy"
        assert result["cohort_id"]
        assert repo.connection.total_changes == before
    finally:
        cm.__exit__(None, None, None)


@pytest.mark.parametrize("mutation", [
    "missing_execution", "future_field", "lag_bool", "requested_rounding", "wrong_period",
    "wrong_count", "wrong_cost_unit", "source_timeframe", "source_provider", "extra_source",
    "burn_config", "burn_source", "burn_fraction", "metric", "wrong_components", "source_schema",
    "duplicate_json", "missing_identity", "modal_input", "valuation_basis", "fixed_fees",
    "rounding", "simulation_extra", "simulation_bool",
])
def test_corruption_cannot_join_a_cohort(tmp_path, monkeypatch, mutation):
    cm, repo, sibling, gate = pair(tmp_path, monkeypatch)
    try:
        assert comparison(repo)["status"] == "COMPARABLE"
        config = json.loads(repo.get_run(sibling)["config_json"])
        ctx = config["comparison_context"]
        bars = config["run_provenance"]["bars"]
        if mutation == "missing_execution":
            del ctx["execution"]
        elif mutation == "future_field":
            ctx["future"] = "not supported"
        elif mutation == "lag_bool":
            ctx["execution"]["decision_lag_bars"] = True
        elif mutation == "requested_rounding":
            ctx["execution"]["sizing"] = "allow_fractional_false"
        elif mutation == "wrong_period":
            ctx["period_start"] = "2023-12-31"
        elif mutation == "wrong_count":
            ctx["oos"]["n_bars"] = 49
        elif mutation == "valuation_basis":
            ctx["execution"]["valuation_basis"] = "adjusted_open"
        elif mutation == "fixed_fees":
            ctx["execution"]["simulation"]["fixed_fees"] = 1.0
        elif mutation == "rounding":
            ctx["execution"]["simulation"]["size_granularity"] = 1.0
        elif mutation == "simulation_extra":
            ctx["execution"]["simulation"]["future"] = True
        elif mutation == "simulation_bool":
            ctx["execution"]["simulation"]["reject_prob"] = False
        elif mutation == "wrong_cost_unit":
            config["run_provenance"]["execution_costs"]["fees_unit"] = "basis_points"
        elif mutation == "source_schema":
            bars["schema_version"] = 999
        elif mutation == "source_timeframe":
            bars["timeframe"] = "1h"
        elif mutation == "source_provider":
            bars["provider"] = "different"
        elif mutation == "extra_source":
            bars["future"] = "arbitrary source field"
        elif mutation.startswith("burn_"):
            column, value = {"burn_config": ("config_hash", "other"),
                             "burn_source": ("data_source", "OtherProvider"),
                             "burn_fraction": ("holdout_frac", 0.25)}[mutation]
            repo.connection.execute(f"UPDATE holdout_evaluations SET {column}=?", (value,))
        elif mutation == "metric":
            repo.connection.execute("UPDATE runs SET sharpe_oos=99 WHERE id=?", (gate,))
        elif mutation == "wrong_components":
            repo.connection.execute("UPDATE runs SET components='[{}]' WHERE id=?", (gate,))
        elif mutation == "missing_identity":
            repo.connection.execute("UPDATE runs SET code_hash=NULL WHERE id=?", (sibling,))
        elif mutation == "modal_input":
            repo.connection.execute("UPDATE runs SET news_snapshot='news'")
        raw = json.dumps(config)
        if mutation == "duplicate_json":
            raw = raw[:-1] + ', "comparison_context":' + json.dumps(ctx) + '}'
        repo.connection.execute("UPDATE runs SET config_json=? WHERE id=?", (raw, sibling))
        result = comparison(repo)
        assert result["status"] == "UNKNOWN", (mutation, result)
        assert result["observed_metric_sort_enabled"] is False
        assert result["cohort_id"] is None
    finally:
        cm.__exit__(None, None, None)


@pytest.mark.parametrize("path,value", [
    (("execution_costs", "fees"), 10**500),
    (("comparison_context", "embargo"), 10**500),
    (("comparison_context", "execution"), None),
])
def test_absent_or_extreme_recorded_inputs_refuse_without_crashing(
    tmp_path, monkeypatch, path, value,
):
    cm, repo, sibling, _ = pair(tmp_path, monkeypatch)
    try:
        config = json.loads(repo.get_run(sibling)["config_json"])
        if path[0] == "execution_costs":
            config["run_provenance"][path[0]][path[1]] = value
        else:
            config[path[0]][path[1]] = value
        repo.connection.execute("UPDATE runs SET config_json=? WHERE id=?",
                                (json.dumps(config), sibling))
        assert comparison(repo)["status"] == "UNKNOWN"
    finally:
        cm.__exit__(None, None, None)


def test_sentinel_zero_with_missing_or_zero_volatility_is_never_rankable(tmp_path, monkeypatch):
    cm, repo, _, _ = pair(tmp_path, monkeypatch)
    try:
        assert comparison(repo)["status"] == "COMPARABLE"
        for volatility in (None, 0.0, -0.2):
            repo.connection.execute("UPDATE runs SET ann_vol_oos=?", (volatility,))
            assert comparison(repo)["status"] == "UNKNOWN"
    finally:
        cm.__exit__(None, None, None)


@pytest.mark.parametrize("change", ["timeframe", "symbols", "hash"])
def test_validly_bound_source_still_needs_independent_semantic_validation(
    tmp_path, monkeypatch, change,
):
    from algua.provenance.snapshot import SnapshotRecord, compute_snapshot_id

    cm, repo, sibling, _ = pair(tmp_path, monkeypatch)
    try:
        config = json.loads(repo.get_run(sibling)["config_json"])
        bars = config["run_provenance"]["bars"]
        if change == "timeframe":
            bars["timeframe"] = "1h"
        elif change == "symbols":
            bars["symbols"] = ["AAPL"]
        else:
            bars["content_hash"] = "malformed"
        record = SnapshotRecord.from_dict(bars)
        sid = compute_snapshot_id(record.metadata, record.content_hash)
        bars["snapshot_id"] = sid
        repo.connection.execute("UPDATE runs SET snapshot_id=?", (sid,))
        repo.connection.execute("UPDATE holdout_evaluations SET snapshot_id=?", (sid,))
        repo.connection.execute("UPDATE runs SET config_json=? WHERE id=?",
                                (json.dumps(config), sibling))
        board = strategy_board_payload(repo, snapshot_evidence=lambda _: {})["rows"][0]
        assert board["evidence"]["snapshot_provenance"]["status"] == "VALID"
        assert board["evidence"]["comparison"]["status"] == "UNKNOWN"
        assert board["evidence"]["comparison"]["reasons"] == ["invalid_source_metadata"]
    finally:
        cm.__exit__(None, None, None)


@pytest.mark.parametrize("field", ["costs", "lag", "fill", "embargo", "dependencies"])
def test_supported_but_heterogeneous_contexts_never_share_a_cohort(tmp_path, monkeypatch, field):
    cm, repo, sibling, _ = pair(tmp_path, monkeypatch)
    try:
        original = comparison(repo)
        config = json.loads(repo.get_run(sibling)["config_json"])
        if field == "costs":
            config["run_provenance"]["execution_costs"]["fees"] = 0
        elif field == "lag":
            config["comparison_context"]["execution"]["decision_lag_bars"] = 2
        elif field == "fill":
            config["comparison_context"]["execution"]["fill_basis"] = "adjusted_open"
            config["comparison_context"]["execution"]["valuation_basis"] = "adjusted_open"
        elif field == "embargo":
            # Partition remains valid; the different in-sample protocol has its own cohort.
            config["comparison_context"]["embargo"] = 22
        else:
            repo.connection.execute("UPDATE runs SET dependency_hash='other-dependencies'")
        repo.connection.execute("UPDATE runs SET config_json=? WHERE id=?",
                                (json.dumps(config), sibling))
        result = comparison(repo)
        assert result["status"] == "COMPARABLE", result
        assert result["cohort_id"] != original["cohort_id"]
    finally:
        cm.__exit__(None, None, None)


@pytest.mark.parametrize("field,value", [
    ("timeframe", "1h"), ("adjustment", "split_only"),
    ("timeframe", "1d"), ("adjustment", "none"),
    ("timeframe", None), ("adjustment", None),
])
def test_provider_declarations_must_agree_even_with_valid_rehashed_identity(
    tmp_path, monkeypatch, field, value,
):
    from algua.provenance.snapshot import SnapshotRecord, compute_snapshot_id

    cm, repo, sibling, _ = pair(tmp_path, monkeypatch)
    try:
        assert comparison(repo)["status"] == "COMPARABLE"
        config = json.loads(repo.get_run(sibling)["config_json"])
        bars = config["run_provenance"]["bars"]
        if value is None:
            bars["source_metadata"].pop(field, None)
        else:
            bars["source_metadata"][field] = value
        record = SnapshotRecord.from_dict(bars)
        sid = compute_snapshot_id(record.metadata, record.content_hash)
        bars["snapshot_id"] = sid
        repo.connection.execute("UPDATE runs SET snapshot_id=?", (sid,))
        repo.connection.execute("UPDATE holdout_evaluations SET snapshot_id=?", (sid,))
        repo.connection.execute("UPDATE runs SET config_json=? WHERE id=?",
                                (json.dumps(config), sibling))
        row = strategy_board_payload(repo, snapshot_evidence=lambda _: {})["rows"][0]
        assert row["evidence"]["snapshot_provenance"]["status"] == "VALID"
        result = row["evidence"]["comparison"]
        if value in ("1h", "split_only"):
            assert result["status"] == "UNKNOWN"
            assert result["observed_metric_sort_enabled"] is False
            assert result["reasons"] == ["invalid_source_metadata"]
        else:
            assert result["status"] == "COMPARABLE", (bars["adjustment"], result)
    finally:
        cm.__exit__(None, None, None)


@pytest.mark.parametrize("field", ["row_count", "schema_version"])
@pytest.mark.parametrize("literal", ["1e999", "-1e999"])
def test_overflowing_json_number_is_isolated_from_healthy_row_and_default_board(
    tmp_path, monkeypatch, field, literal,
):
    cm, repo, sibling, _ = pair(tmp_path, monkeypatch)
    try:
        config = json.loads(repo.get_run(sibling)["config_json"])
        record_pair(repo, "healthy_second", config["run_provenance"]["bars"])
        default = strategy_board_payload(repo)
        healthy_before = next(row for row in strategy_board_payload(
            repo, snapshot_evidence=lambda _: {})["rows"] if row["name"] == "healthy_second")
        assert healthy_before["evidence"]["comparison"]["status"] == "COMPARABLE"
        config["run_provenance"]["bars"][field] = "exponent_overflow_control"
        raw = json.dumps(config).replace('"exponent_overflow_control"', literal)
        repo.connection.execute("UPDATE runs SET config_json=? WHERE id=?", (raw, sibling))
        rows = strategy_board_payload(repo, snapshot_evidence=lambda _: {})["rows"]
        damaged = next(row for row in rows if row["name"] == NAME)
        assert damaged["recorded_provenance"]["status"] == "INVALID"
        assert damaged["evidence"]["comparison"]["status"] == "UNKNOWN"
        assert damaged["evidence"]["comparison"]["observed_metric_sort_enabled"] is False
        assert next(row for row in rows if row["name"] == "healthy_second") == healthy_before
        assert strategy_board_payload(repo) == default
    finally:
        cm.__exit__(None, None, None)
