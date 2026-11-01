"""Synthetic sentinels through the real recorder, ledger and operator readers."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from algua.backtest.walkforward import WalkForwardResult
from algua.cli.main import app
from algua.registry.db import registry_conn
from algua.registry.run_views import run_detail_payload, run_list_payload
from algua.registry.runs import record_walk_forward_run
from algua.registry.store import SqliteStrategyRepository

PRIVATE = 987654.321
PUBLIC = {"mean_sharpe": 0.0, "std_sharpe": 0.5, "min_sharpe": -2.5,
          "pct_positive_windows": 0.25}
PARAMS = {"holdout_metrics": {"sharpe_oos": "a user parameter"}, "returns": [0, -1],
          "nested": {"anything": {"x": True}}}


def wf_result() -> WalkForwardResult:
    return WalkForwardResult(
        strategy="synthetic", config_hash="cfg", data_source="synthetic_fixture",
        snapshot_id="snapshot", timeframe="1d", seed=7,
        period={"start": "2023-01-01", "end": "2023-12-31"},
        windows=4, holdout_frac=0.2, stability=dict(PUBLIC),
        window_metrics=[{"index": 0, "start": "2023-01-02", "end": "2023-03-01",
                         "n_bars": 40, "sharpe": -2.5, "total_return": -0.1}],
        holdout_metrics={"sharpe": PRIVATE, "total_return": PRIVATE,
                         "ann_volatility": PRIVATE, "n_bars": 123,
                         "max_drawdown": -PRIVATE, "start": "2023-11-01",
                         "end": "2023-12-29"},
        holdout_returns=([PRIVATE], ["2023-12-29"]),
    )


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "registry.db"))
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path / "data"))


def test_recorder_withholds_tail_and_retains_public_measurements():
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        run_id = record_walk_forward_run(repo, "synthetic", wf_result())
        raw = dict(conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())
        assert raw["sharpe_oos"] is None
        assert raw["total_return_oos"] is None
        assert raw["n_obs_oos"] is None
        assert raw["mean_window_sharpe"] == 0.0
        assert raw["min_window_sharpe"] == -2.5
        assert str(PRIVATE) not in json.dumps(raw)
        assert conn.execute("SELECT count(*) FROM holdout_evaluations").fetchone()[0] == 0


def test_generic_recording_and_historical_reads_cannot_export_nested_tail():
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        config = {"params": PARAMS, "result": {"holdout_metrics": {"sharpe": PRIVATE}},
                  "run_provenance": {"bars": {"nested": {"sharpe_oos": PRIVATE}},
                                     "execution_costs": None},
                  "include_holdout": True}
        run_id = repo.record_run("walk_forward", "synthetic", config=config,
                                 metrics={"sharpe_oos": PRIVATE, "min_window_sharpe": -2.5},
                                 extra_metrics={"tail_alias": PRIVATE})
        assert str(PRIVATE) not in json.dumps(dict(repo.get_run(run_id)))
        # Simulate a pre-repair row. Reads must redact without rewriting historical evidence.
        with conn:
            conn.execute("UPDATE runs SET sharpe_oos=?, config_json=? WHERE id=?",
                         (PRIVATE, json.dumps(config), run_id))
            conn.execute("INSERT OR REPLACE INTO run_metrics VALUES (?,?,?)",
                         (run_id, "tail_alias", PRIVATE))
        before = [tuple(r) for r in conn.execute("SELECT * FROM runs")]
        for payload in [run_detail_payload(repo, run_id), run_list_payload(
            repo, kind=None, strategy=None, family=None, sort="sharpe_oos", limit=100)]:
            assert str(PRIVATE) not in json.dumps(payload)
        assert run_detail_payload(repo, run_id)["config_json"]["params"] == PARAMS
        assert [tuple(r) for r in conn.execute("SELECT * FROM runs")] == before
        for args in [["runs", "show", str(run_id)], ["runs", "list"],
                     ["runs", "list", "--sort", "sharpe_oos"], ["runs", "board"]]:
            result = CliRunner().invoke(app, args)
            assert result.exit_code == 0, result.output
            assert str(PRIVATE) not in result.stdout
        assert conn.execute("SELECT count(*) FROM holdout_evaluations").fetchone()[0] == 0


def test_cli_and_serialization_withhold_nested_outcomes(monkeypatch):
    from algua.cli import backtest_cmd

    wf = wf_result()
    wf.stability["sharpe_oos"] = PRIVATE
    wf.window_metrics[0]["diagnostics"] = {"holdout_metrics": {"sharpe": PRIVATE}}
    wf.bars_provenance = {"snapshot_id": "snapshot", "raw_result": {"alias": PRIVATE},
                          "source_metadata": {"raw_json": json.dumps({"tail": PRIVATE})}}
    wf.execution_costs = {"fees": 0.0, "nested": {"tail": PRIVATE}}
    strategy = type("Strategy", (), {"config": type("Config", (), {
        "needs_fundamentals": False, "needs_news": False, "params": PARAMS})()})()
    monkeypatch.setattr(backtest_cmd, "resolve_eval_inputs",
                        lambda *a: (strategy, None, None, None))
    monkeypatch.setattr(backtest_cmd, "resolve_universe_inputs", lambda *a: (None, None))
    monkeypatch.setattr(backtest_cmd, "resolve_delisting_inputs", lambda *a: (None, None))
    monkeypatch.setattr(backtest_cmd, "walk_forward", lambda *a, **kw: wf)
    assert str(PRIVATE) not in json.dumps(wf.to_dict())
    for summary in [[], ["--summary"]]:
        result = CliRunner().invoke(app, ["backtest", "walk-forward", "synthetic", *summary])
        assert result.exit_code == 0, result.output
        assert str(PRIVATE) not in result.stdout
        assert json.loads(result.stdout)["stability"] == PUBLIC
    with registry_conn() as conn:
        assert conn.execute("SELECT count(*) FROM holdout_evaluations").fetchone()[0] == 0


def test_sweep_serialization_and_tracking_use_only_public_namespaces(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace

    import mlflow

    from algua.backtest.sweep import SweepResult
    from algua.tracking.mlflow_tracker import log_sweep, log_walk_forward

    wf = wf_result()
    wf.stability["sharpe_oos"] = PRIVATE
    wf.window_metrics[0]["raw"] = {"returns": [PRIVATE]}
    trial = {"params": PARAMS, "config_hash": "trial-cfg", "score": 0.0,
             "stability": PUBLIC | {"holdout_sharpe": PRIVATE},
             "raw_json": json.dumps({"tail": PRIVATE})}
    sweep = SweepResult(
        strategy="synthetic", data_source=wf.data_source, snapshot_id=wf.snapshot_id,
        timeframe=wf.timeframe, seed=wf.seed, period=wf.period, windows=4, holdout_frac=0.2,
        grid={"holdout_metrics": [PARAMS]}, n_combos=1, rank_by="mean_sharpe",
        ranked=[trial], best=trial,
    )
    assert str(PRIVATE) not in json.dumps(sweep.to_dict())
    assert sweep.to_dict()["ranked"][0]["params"] == PARAMS
    logged = []

    @contextmanager
    def run(*args, **kwargs):
        yield SimpleNamespace(info=SimpleNamespace(run_id="synthetic-run"))

    monkeypatch.setattr("algua.tracking.mlflow_tracker._run", run)
    monkeypatch.setattr(mlflow, "start_run", run)
    for name in ["log_params", "log_metrics", "set_tags"]:
        monkeypatch.setattr(mlflow, name, lambda value: logged.append(value))
    monkeypatch.setattr(mlflow, "log_dict", lambda value, path: logged.append(value))
    monkeypatch.setattr(mlflow, "log_metric", lambda key, value: logged.append({key: value}))
    log_walk_forward(wf, PARAMS, tracking_uri=str(tmp_path))
    log_sweep(sweep, tracking_uri=str(tmp_path))
    assert str(PRIVATE) not in json.dumps(logged)
    assert any(value.get("mean_sharpe") == 0.0 for value in logged)


@pytest.mark.parametrize("kind", ["walk_forward", "sweep", "sweep_trial"])
def test_all_ordinary_windowed_ledger_kinds_reject_tail_aliases(kind):
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        run_id = repo.record_run(kind, "synthetic", metrics={"sharpe_oos": PRIVATE},
                                 config={"params": PARAMS, "result_json": str(PRIVATE)},
                                 components=[{"holdout_returns": [PRIVATE]}],
                                 extra_metrics={"holdout_alias": PRIVATE})
        raw = dict(conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())
        assert str(PRIVATE) not in json.dumps(raw)
        assert str(PRIVATE) not in json.dumps(run_detail_payload(repo, run_id))
        assert run_detail_payload(repo, run_id)["config_json"]["params"] == PARAMS


def test_risk_consumer_reads_gate_evidence_and_never_ordinary_wf_tail():
    from datetime import UTC, datetime

    from algua.registry.allocations import portfolio_risk_estimates

    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        evidence = {"code_hash": "code", "config_hash": "cfg", "period_end": "2023-12-31"}
        ordinary = repo.record_run("walk_forward", "synthetic", provenance=evidence)
        gate = repo.record_run("gate", "synthetic", provenance=evidence,
                               metrics={"ann_vol_oos": 0.2, "n_obs_oos": 63})
        # Historical ordinary WF tails are still private even if a matching gate exists.
        with conn:
            conn.execute("UPDATE runs SET ann_vol_oos=?,n_obs_oos=63 WHERE id=?",
                         (PRIVATE, ordinary))
        estimates = portfolio_risk_estimates(
            repo, {"synthetic": ("code", "cfg")}, as_of=datetime(2099, 1, 1, tzinfo=UTC))
        assert [r.source for r in estimates["synthetic"]] == [f"run:{gate}"]
        assert estimates["synthetic"][0].volatility == 0.2
        assert repo.get_run(ordinary)["ann_vol_oos"] is None


def test_unknown_public_statistics_are_not_zero_and_input_metadata_survives():
    wf = wf_result()
    wf.stability = PUBLIC | {"mean_sharpe": float("nan"), "min_sharpe": None}
    wf.bars_provenance = canonical_bars_record()
    public = wf.to_dict()
    assert public["stability"]["mean_sharpe"] is None
    assert public["stability"]["min_sharpe"] is None
    assert public["stability"]["pct_positive_windows"] == 0.25
    assert public["bars_provenance"] == wf.bars_provenance


def test_hidden_tail_cannot_affect_sort_order_or_series_exports():
    from algua.registry.run_views import run_series_payload

    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        first = repo.record_run("walk_forward", "first")
        second = repo.record_run("walk_forward", "second")
        gate = repo.record_run("gate", "gate", metrics={"sharpe_oos": -3.0})
        with conn:
            vector = conn.execute(
                "INSERT INTO backtest_returns(strategy_name,period_start,period_end,"
                "returns_json,created_at) VALUES (?,?,?,?,?)",
                ("first", "2023-01-01", "2023-12-31", json.dumps([["2023-12-29", PRIVATE]]),
                 "2024-01-01T00:00:00+00:00")).lastrowid
            conn.execute("UPDATE runs SET series_backtest_id=? WHERE id=?", (vector, first))
            conn.execute("UPDATE runs SET sharpe_oos=?,components=?,series_holdout_id=? WHERE id=?",
                         (PRIVATE, json.dumps([{"holdout_returns": [PRIVATE]}]), 12345, first))
            conn.execute("UPDATE runs SET sharpe_oos=? WHERE id=?", (-PRIVATE, second))
        ordered = repo.list_runs(sort="sharpe_oos", limit=1)
        assert ordered[0]["id"] == gate
        assert [r["id"] for r in repo.list_runs(sort="sharpe_oos")] == [gate, second, first]
        assert run_series_payload(repo, [first, second]) == {
            "series": {str(first): None, str(second): None}}
        assert str(PRIVATE) not in json.dumps(run_detail_payload(repo, first))


@pytest.mark.parametrize("namespace", ["run_provenance", "execution_costs"])
def test_metadata_projection_never_upgrades_invalid_recorded_evidence(
    tmp_path, monkeypatch, namespace,
):
    from tests.registry.test_run_provenance_fixes import board_pair
    from tests.test_run_provenance import NAME

    # Build exact synthetic input/lineage with the established board fixture, then corrupt
    # the historical metadata directly. Projection must hide the extra payload and stay invalid.
    board_pair(tmp_path, monkeypatch)
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        wf = conn.execute("SELECT * FROM runs WHERE kind='walk_forward'").fetchone()
        config = json.loads(wf["config_json"])
        prov = config["run_provenance"]
        target = prov if namespace == "run_provenance" else prov["execution_costs"]
        target["raw_result"] = {"holdout_sharpe": PRIVATE}
        with conn:
            conn.execute("UPDATE runs SET config_json=? WHERE id=?", (json.dumps(config), wf["id"]))
        from algua.registry.strategy_board import strategy_board_payload

        board = strategy_board_payload(repo, snapshot_evidence=lambda _: {})
        row = next(r for r in board["rows"] if r["name"] == NAME)
        assert row["recorded_provenance"]["status"] == "INVALID"
        assert str(PRIVATE) not in json.dumps(run_detail_payload(repo, wf["id"]))


def test_real_tracking_artifact_contains_only_public_window_measurements(tmp_path):
    import mlflow
    from mlflow.tracking import MlflowClient

    from algua.tracking.mlflow_tracker import log_walk_forward

    uri = f"sqlite:///{tmp_path / 'tracking.db'}"
    mlflow.set_tracking_uri(uri)
    mlflow.create_experiment("synthetic", artifact_location=(tmp_path / "artifacts").as_uri())
    wf = wf_result()
    wf.stability["holdout_alias"] = PRIVATE
    wf.window_metrics[0]["raw"] = {"holdout_returns": [PRIVATE]}
    run_id = log_walk_forward(wf, PARAMS, tracking_uri=uri)
    client = MlflowClient(tracking_uri=uri)
    run = client.get_run(run_id)
    assert run.data.metrics == PUBLIC
    assert str(PRIVATE) not in json.dumps(run.to_dictionary())
    path = client.download_artifacts(run_id, "result.json", dst_path=str(tmp_path))
    artifact = json.loads(Path(path).read_text())
    assert str(PRIVATE) not in json.dumps(artifact)
    assert artifact["stability"] == PUBLIC
    assert {a.path for a in client.list_artifacts(run_id)} == {"result.json"}


@pytest.mark.parametrize("costs", [[PRIVATE], json.dumps({"tail": PRIVATE})])
def test_malformed_cost_metadata_cannot_become_a_raw_json_export(costs):
    wf = wf_result()
    wf.execution_costs = costs
    assert str(PRIVATE) not in json.dumps(wf.to_dict())


def test_historical_malformed_lineage_is_unknown_not_a_nested_export():
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        run_id = repo.record_run("walk_forward", "synthetic",
                                 derived_from=[{"result": {"holdout_sharpe": PRIVATE}}])
        raw = dict(conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())
        assert str(PRIVATE) not in json.dumps(raw)
        with conn:
            conn.execute("UPDATE runs SET derived_from=? WHERE id=?",
                         (json.dumps([{"result": {"holdout_sharpe": PRIVATE}}]), run_id))
        assert str(PRIVATE) not in json.dumps(run_detail_payload(repo, run_id))


def test_actual_sweep_cli_recording_and_summary_withhold_nested_tail(monkeypatch):
    from algua.backtest.sweep import SweepResult
    from algua.evaluation import sweep_run

    wf = wf_result()
    trial = {"params": PARAMS, "config_hash": "cfg", "score": 0.0,
             "stability": PUBLIC | {"oos_alias": PRIVATE},
             "raw_json": json.dumps({"tail": PRIVATE})}
    result = SweepResult(
        strategy="synthetic", data_source=wf.data_source, snapshot_id=wf.snapshot_id,
        timeframe=wf.timeframe, seed=wf.seed, period=wf.period, windows=4, holdout_frac=0.2,
        grid={"input": [PARAMS]}, n_combos=1, rank_by="mean_sharpe", ranked=[trial], best=trial)
    config = type("Config", (), {"needs_fundamentals": False, "needs_news": False})()
    strategy = type("Strategy", (), {"config": config})()
    monkeypatch.setattr(sweep_run, "resolve_eval_inputs", lambda *a, **kw: (
        strategy, None, None, None))
    monkeypatch.setattr(sweep_run, "resolve_universe_inputs", lambda *a: (None, None))
    monkeypatch.setattr(sweep_run, "resolve_delisting_inputs", lambda *a: (None, None))
    monkeypatch.setattr(sweep_run, "sweep", lambda *a, **kw: result)
    for summary in [[], ["--summary"]]:
        output = CliRunner().invoke(
            app, ["backtest", "sweep", "synthetic", "--param", "input=1", *summary])
        assert output.exit_code == 0, output.output
        assert str(PRIVATE) not in output.stdout
        assert json.loads(output.stdout)["best"]["params"] == PARAMS
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        for row in repo.list_runs():
            assert str(PRIVATE) not in json.dumps(run_detail_payload(repo, row["id"]))
        assert conn.execute("SELECT count(*) FROM holdout_evaluations").fetchone()[0] == 0


@pytest.mark.parametrize("kind", ["walk_forward", "sweep", "sweep_combo", "unknown"])
def test_historical_tracking_reader_and_kb_projection_withhold_tail_aliases(tmp_path, kind):
    import mlflow
    from mlflow.tracking import MlflowClient

    from algua.knowledge.metrics import latest_run_metrics
    from algua.knowledge.sync import render_results_block

    uri = f"sqlite:///{tmp_path / 'historical.db'}"
    mlflow.set_tracking_uri(uri)
    exp_id = mlflow.create_experiment(
        "history", artifact_location=(tmp_path / "artifacts").as_uri())
    raw = PUBLIC | {"sharpe_oos": PRIVATE, "holdout_sharpe": PRIVATE, "sharpe": PRIVATE,
                    "best_score": -2.5, "score": 0.0}
    with mlflow.start_run(experiment_id=exp_id) as run:
        mlflow.set_tag("kind", kind)
        mlflow.log_metrics(raw)
        run_id = run.info.run_id
    result = latest_run_metrics("history", tracking_uri=uri)
    assert result is not None
    assert str(PRIVATE) not in json.dumps(result)
    assert str(PRIVATE) not in render_results_block(result)
    expected = (PUBLIC if kind == "walk_forward" else PUBLIC | {"score": 0.0}
                if kind == "sweep_combo" else {"best_score": -2.5} if kind == "sweep" else {})
    assert result["metrics"] == expected
    assert MlflowClient(tracking_uri=uri).get_run(run_id).data.metrics == raw


def canonical_bars_record(extra=None, *, source_metadata=None, provider="yfinance"):
    """Known complete producer input; unrestricted future-field R1 admission is superseded."""
    from algua.provenance.research import (
        DataTier,
        ProvenanceDeclaration,
        build_envelope,
        encode_envelope,
    )
    from algua.provenance.snapshot import (
        Dataset,
        Kind,
        SnapshotMetadata,
        SnapshotRecord,
        compute_snapshot_id,
    )

    envelope = encode_envelope(build_envelope(
        ProvenanceDeclaration(DataTier.SYNTHETIC_FIXTURE, "fixture/v1",
                              ("synthetic_not_market_data",)),
        provider=provider, coverage_start="2023-01-02", coverage_end="2023-12-29"))
    metadata = SnapshotMetadata(
        dataset=Dataset.BARS, kind=Kind.BARS, provider=provider, symbols=("SYNTHETIC",),
        start="2023-01-01", end="2024-01-01", as_of="2024-01-02T00:00:00+00:00",
        source="synthetic", timeframe="1d", adjustment="none",
        source_metadata={"research_provenance": envelope,
                         **({"library": "yfinance", "timeframe": "1d", "adjustment": "none"}
                            if source_metadata is None else source_metadata), **(extra or {})})
    digest = "a" * 64
    return SnapshotRecord(compute_snapshot_id(metadata, digest), metadata, 260, digest,
                          Path("synthetic.parquet"), "2024-01-02T00:00:00+00:00",
                          "parquet_dataset").to_dict()


def record_provenance_pair(repo, bars, *, costs=None, name="synthetic"):
    from tests.test_run_provenance import COSTS

    strategy = repo.add(name)
    provenance = {"code_hash": "code", "config_hash": "cfg", "dependency_hash": "deps",
                  "snapshot_id": bars.get("snapshot_id") if isinstance(bars, dict) else "snapshot",
                  "timeframe": "1d", "period_start": "2023-01-01", "period_end": "2023-12-31"}
    sibling = repo.record_run("walk_forward", name, strategy_id=strategy.id,
                              provenance=provenance, config={"params": PARAMS, "run_provenance": {
                                  "bars": bars,
                                  "execution_costs": COSTS if costs is None else costs}})
    gate = repo.record_run("gate", name, strategy_id=strategy.id,
                           derived_from=[sibling], provenance=provenance)
    return sibling, gate


def test_canonical_provenance_survives_recording_serialization_and_repeated_projection():
    from algua.provenance.research_disclosure import public_window_result
    from algua.provenance.snapshot_evidence import project_snapshot_record
    from algua.registry.store.run_public import public_config
    from algua.registry.strategy_board import strategy_board_payload
    from tests.test_run_provenance import COSTS

    bars = canonical_bars_record()
    wf = wf_result()
    wf.snapshot_id, wf.bars_provenance, wf.execution_costs = bars["snapshot_id"], bars, COSTS
    assert project_snapshot_record(bars["snapshot_id"], bars)["status"] == "VALID"
    public = wf.to_dict()
    assert public["bars_provenance"] == bars
    assert public_window_result(public) == public
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        sibling, _ = record_provenance_pair(repo, bars)
        for _ in range(3):
            config = run_detail_payload(repo, sibling)["config_json"]
            assert config["run_provenance"] == {"bars": bars, "execution_costs": COSTS}
            assert public_config(config) == config
            row, = strategy_board_payload(repo, snapshot_evidence=lambda _: {})["rows"]
            assert row["recorded_provenance"]["status"] == "VALID"
            assert row["evidence"]["snapshot_provenance"]["status"] == "VALID"
            assert row["evidence"]["comparison"]["observed_metric_sort_enabled"] is False


@pytest.mark.parametrize("malformation", [
    "envelope_dict", "envelope_list", "envelope_number", "envelope_null", "envelope_json",
    "source_dict_value", "source_list", "source_null", "bars_list", "bars_string", "bars_bool",
    "bars_count_bool",
])
def test_present_malformed_bars_remain_invalid_after_repeated_projection(malformation):
    from algua.provenance.research_disclosure import public_bars
    from algua.registry.strategy_board import strategy_board_payload
    from tests.test_run_provenance import COSTS

    bars = canonical_bars_record()
    metadata = bars["source_metadata"]
    variants = {"envelope_dict": {"tail": PRIVATE}, "envelope_list": [PRIVATE],
                "envelope_number": PRIVATE, "envelope_null": None,
                "envelope_json": json.dumps({"tail": PRIVATE})}
    if malformation in variants:
        metadata["research_provenance"] = variants[malformation]
    elif malformation == "source_dict_value":
        metadata["additional_input"] = {"tail": PRIVATE}
    elif malformation.startswith("source_"):
        bars["source_metadata"] = [PRIVATE] if malformation == "source_list" else None
    elif malformation == "bars_count_bool":
        bars["row_count"] = True
    else:
        bars = {"bars_list": [PRIVATE], "bars_string": json.dumps({"tail": PRIVATE}),
                "bars_bool": True}[malformation]
    projected = public_bars(bars)
    assert projected is not None
    assert public_bars(projected) == projected
    assert str(PRIVATE) not in json.dumps(projected)
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        sibling, _ = record_provenance_pair(repo, bars)
        # Historical readback must be safe without rewriting the originally malformed bytes.
        config = {"params": PARAMS, "run_provenance": {
            "bars": bars, "execution_costs": COSTS}}
        with conn:
            conn.execute("UPDATE runs SET config_json=? WHERE id=?", (json.dumps(config), sibling))
        before = conn.execute("SELECT config_json FROM runs WHERE id=?", (sibling,)).fetchone()[0]
        for _ in range(2):
            public = run_detail_payload(repo, sibling)
            assert str(PRIVATE) not in json.dumps(public)
            row, = strategy_board_payload(repo, snapshot_evidence=lambda _: {})["rows"]
            assert row["recorded_provenance"]["status"] == "INVALID"
            assert row["evidence"]["snapshot_provenance"]["status"] == "INVALID"
        assert conn.execute("SELECT config_json FROM runs WHERE id=?",
                            (sibling,)).fetchone()[0] == before
        assert conn.execute("SELECT count(*) FROM holdout_evaluations").fetchone()[0] == 0


@pytest.mark.parametrize("field", ["fees", "slippage"])
@pytest.mark.parametrize("bad", [json.dumps({"holdout_metrics": {"sharpe": PRIVATE}}),
                                 True, None, float("inf"), -0.1])
def test_cost_numeric_fields_fail_closed_through_recording_and_cli(field, bad):
    from algua.provenance.research_disclosure import public_run_provenance
    from algua.registry.strategy_board import strategy_board_payload
    from tests.test_run_provenance import COSTS

    costs = COSTS | {field: bad}
    value = {"bars": canonical_bars_record(), "execution_costs": costs}
    public = public_run_provenance(value)
    assert public["execution_costs"] == {"invalid_fields": True}
    assert public_run_provenance(public) == public
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        sibling, _ = record_provenance_pair(repo, value["bars"], costs=costs)
        assert str(PRIVATE) not in json.dumps(dict(repo.get_run(sibling)))
        for args in [["runs", "show", str(sibling)], ["runs", "list"]]:
            output = CliRunner().invoke(app, args)
            assert output.exit_code == 0, output.output
            assert str(PRIVATE) not in output.stdout
        row, = strategy_board_payload(repo, snapshot_evidence=lambda _: {})["rows"]
        assert row["recorded_provenance"]["status"] == "INVALID"
        assert row["evidence"]["snapshot_provenance"]["status"] == "INVALID"
        assert conn.execute("SELECT count(*) FROM holdout_evaluations").fetchone()[0] == 0


@pytest.mark.parametrize("field", ["index", "n_bars", "sharpe", "total_return", "max_drawdown"])
@pytest.mark.parametrize("bad", [json.dumps({"holdout_returns": [PRIVATE]}), True])
def test_window_numeric_fields_are_unknown_without_echoing_raw_json(field, bad):
    wf = wf_result()
    wf.window_metrics[0][field] = bad
    public = wf.to_dict()
    assert str(PRIVATE) not in json.dumps(public)
    assert public["window_metrics"][0][field] is None


def test_trial_and_result_numeric_fields_are_typed_and_user_inputs_opaque():
    from algua.backtest.sweep import SweepResult
    from algua.provenance.research_disclosure import public_window_result

    raw = json.dumps({"holdout_returns": [PRIVATE]})
    wf = wf_result()
    params = PARAMS | {"opaque_input": {"json": '[1, -2, {"x": true}]'}}
    trial = {"config_hash": "cfg", "params": params, "stability": PUBLIC, "score": raw,
             "n_windows": raw}
    result = SweepResult(
        strategy="synthetic", data_source=wf.data_source, snapshot_id=wf.snapshot_id,
        timeframe=wf.timeframe, seed=raw, period=wf.period, windows=raw, holdout_frac=raw,
        grid={"opaque_input": [params]}, n_combos=raw, rank_by="mean_sharpe",
        ranked=[trial], best=trial, trial_sharpe_mean=raw)
    public = result.to_dict()
    assert str(PRIVATE) not in json.dumps(public)
    assert public["best"]["score"] is None
    assert public["ranked"][0]["n_windows"] is None
    assert all(public[key] is None for key in (
        "windows", "holdout_frac", "n_combos", "seed", "trial_sharpe_mean"))
    assert public["grid"] == result.grid
    assert public["ranked"][0]["params"] == params
    assert public_window_result(public) == public


def test_legacy_numeric_json_cannot_escape_show_or_influence_window_sort():
    raw = json.dumps({"tail": PRIVATE})
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        malformed = repo.record_run("walk_forward", "malformed")
        measured = repo.record_run("walk_forward", "measured", metrics={"mean_window_sharpe": -2.5})
        with conn:
            conn.execute("UPDATE runs SET mean_window_sharpe=? WHERE id=?", (raw, malformed))
        before = conn.execute("SELECT mean_window_sharpe FROM runs WHERE id=?",
                              (malformed,)).fetchone()[0]
        ordered = repo.list_runs(sort="mean_window_sharpe", limit=1)
        assert ordered[0]["id"] == measured
        detail = run_detail_payload(repo, malformed)
        assert detail["mean_window_sharpe"] is None
        assert str(PRIVATE) not in json.dumps(detail)
        assert conn.execute("SELECT mean_window_sharpe FROM runs WHERE id=?",
                            (malformed,)).fetchone()[0] == before


@pytest.mark.parametrize("aliases", [
    {"sharpe_oos": "987654.321", "holdout_returns": "987654.321"},
    {"sharpe_oos": "987654.321"},
    {"holdout_returns": "987654.321"},
])
def test_matching_input_hash_never_authorizes_reserved_scalar_outcomes(aliases):
    from algua.provenance.research_disclosure import public_bars
    from algua.provenance.snapshot_evidence import project_snapshot_record

    bars = canonical_bars_record(aliases)
    before = json.dumps(bars, sort_keys=True)
    assert project_snapshot_record(bars["snapshot_id"], bars)["status"] == "VALID"
    public = public_bars(bars)
    assert public == {"invalid_fields": True}
    assert public_bars(public) == public
    assert project_snapshot_record(bars["snapshot_id"], public)["status"] == "INVALID"
    assert json.dumps(bars, sort_keys=True) == before


def test_matching_input_hash_never_authorizes_untyped_outcome_json():
    from algua.provenance.research_disclosure import public_bars
    from algua.provenance.snapshot_evidence import project_snapshot_record

    # Hash is canonical and matches, but is not authorization to disclose structured outcomes.
    for key in ["result_json", "research_provenance"]:
        bars = canonical_bars_record({key: json.dumps({"holdout_returns": [PRIVATE]})})
        expected = "VALID" if key == "result_json" else "INVALID"
        assert project_snapshot_record(bars["snapshot_id"], bars)["status"] == expected
        public = public_bars(bars)
        assert public == {"invalid_fields": True}
        assert public_bars(public) == public


@pytest.mark.parametrize("surface", ["walk-forward", "sweep"])
def test_exact_inputs_and_rejected_numeric_json_through_cli_and_real_tracking(
    tmp_path, monkeypatch, surface,
):
    import mlflow
    from mlflow.tracking import MlflowClient

    from algua.backtest.sweep import SweepResult
    from algua.cli import backtest_cmd
    from algua.evaluation import sweep_run
    from tests.test_run_provenance import COSTS

    uri = f"sqlite:///{tmp_path / 'typed-tracking.db'}"
    monkeypatch.setenv("ALGUA_MLFLOW_TRACKING_URI", uri)
    monkeypatch.setenv("ALGUA_TRACKING_BACKEND", "mlflow-sqlite")
    mlflow.set_tracking_uri(uri)
    exp = mlflow.create_experiment("synthetic", artifact_location=(tmp_path / "artifacts").as_uri())
    raw = json.dumps({"holdout_returns": [PRIVATE]})
    bars = canonical_bars_record()
    wf = wf_result()
    wf.snapshot_id, wf.bars_provenance = bars["snapshot_id"], bars
    wf.execution_costs = COSTS | {"fees": raw}
    wf.window_metrics[0]["sharpe"] = raw
    wf.stability["mean_sharpe"] = raw
    config = type("Config", (), {"needs_fundamentals": False, "needs_news": False,
                                  "params": PARAMS})()
    strategy = type("Strategy", (), {"config": config})()
    trial = {"params": PARAMS, "config_hash": "cfg", "score": raw, "stability": wf.stability,
             "bars_provenance": bars, "execution_costs": wf.execution_costs}
    result = SweepResult(
        strategy="synthetic", data_source=wf.data_source, snapshot_id=wf.snapshot_id,
        timeframe="1d", seed=7, period=wf.period, windows=4, holdout_frac=0.2,
        grid={"input": [PARAMS]}, n_combos=1, rank_by="mean_sharpe", ranked=[trial], best=trial,
        bars_provenance=bars, execution_costs=wf.execution_costs)
    target = backtest_cmd if surface == "walk-forward" else sweep_run
    monkeypatch.setattr(target, "resolve_eval_inputs",
                        lambda *a, **kw: (strategy, None, None, None))
    monkeypatch.setattr(target, "resolve_universe_inputs", lambda *a: (None, None))
    monkeypatch.setattr(target, "resolve_delisting_inputs", lambda *a: (None, None))
    monkeypatch.setattr(target, "walk_forward" if surface == "walk-forward" else "sweep",
                        lambda *a, **kw: wf if surface == "walk-forward" else result)
    for summary in [[], ["--summary"]]:
        args = ["backtest", surface, "synthetic", "--track", *summary]
        if surface == "sweep":
            args += ["--param", "input=1"]
        output = CliRunner().invoke(app, args)
        assert output.exit_code == 0, output.output
        assert str(PRIVATE) not in output.stdout
        payload = json.loads(output.stdout)
        assert payload["bars_provenance"] == bars
        assert payload["execution_costs"] == {"invalid_fields": True}
        assert "mlflow_tracking_error" not in payload
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        for row in repo.list_runs():
            detail = run_detail_payload(repo, row["id"])
            assert str(PRIVATE) not in json.dumps(detail)
            assert detail["config_json"]["run_provenance"]["bars"] == bars
        assert conn.execute("SELECT count(*) FROM holdout_evaluations").fetchone()[0] == 0
    client = MlflowClient(tracking_uri=uri)
    runs = client.search_runs([exp])
    assert len(runs) == (2 if surface == "walk-forward" else 4)
    for run in runs:
        assert str(PRIVATE) not in json.dumps(run.to_dictionary())
        for artifact in client.list_artifacts(run.info.run_id):
            path = client.download_artifacts(run.info.run_id, artifact.path, dst_path=str(tmp_path))
            payload = json.loads(Path(path).read_text())
            assert str(PRIVATE) not in json.dumps(payload)
            assert payload["bars_provenance"] == bars
            if surface == "sweep":
                assert payload["grid"] == result.grid
                assert payload["best"]["params"] == PARAMS


@pytest.mark.parametrize("key", ["schema_version", "model", "fees_unit", "slippage_unit"])
def test_cost_schema_constants_cannot_carry_raw_outcomes(key):
    from algua.provenance.research_disclosure import public_run_provenance
    from tests.test_run_provenance import COSTS

    value = {"bars": canonical_bars_record(), "execution_costs": COSTS | {
        key: json.dumps({"holdout_metrics": {"sharpe": PRIVATE}})}}
    public = public_run_provenance(value)
    assert public["execution_costs"] == {"invalid_fields": True}
    assert public_run_provenance(public) == public


def test_direct_generic_and_batched_numeric_writers_keep_json_out_of_measurements():
    from algua.registry.runs import walk_forward_metrics

    raw = json.dumps({"holdout_metrics": {"sharpe": PRIVATE}})
    wf = wf_result()
    wf.stability["mean_sharpe"] = raw
    assert walk_forward_metrics(wf)["mean_window_sharpe"] is None
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        for kind in ["walk_forward", "sweep", "sweep_trial"]:
            run_id = repo.record_run(kind, "synthetic", metrics={"mean_window_sharpe": raw},
                                     extra_metrics={"mean_trial_sharpe": raw},
                                     config={"params": PARAMS, "grid": {"input": [PARAMS]}})
            row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            assert row["mean_window_sharpe"] is None
            assert str(PRIVATE) not in json.dumps(run_detail_payload(repo, run_id))
            assert run_detail_payload(repo, run_id)["config_json"]["params"] == PARAMS
        parent = repo.record_run("sweep", "synthetic")
        repo.record_sweep_trials(parent, "synthetic", [
            {"metrics": {"mean_window_sharpe": raw}, "config": {"params": PARAMS}}])
        trial = repo.list_runs(kind="sweep_trial")[0]
        assert trial["mean_window_sharpe"] is None


def test_canonical_zero_costs_and_nonpositive_measurements_survive_exactly():
    from algua.provenance.research_disclosure import public_run_provenance
    from tests.test_run_provenance import COSTS

    value = {"bars": canonical_bars_record(), "execution_costs": COSTS | {
        "fees": 0.0, "slippage": 0.0}}
    assert public_run_provenance(value) == value
    assert public_run_provenance(public_run_provenance(value)) == value
    wf = wf_result()
    assert wf.to_dict()["stability"] == PUBLIC
    assert wf.to_dict()["window_metrics"][0]["sharpe"] == -2.5


@pytest.mark.parametrize("extra", [
    {"note": str(PRIVATE)}, {"future_input_note": "innocuous"},
    {"observation": str(PRIVATE), "public": "true"},
    {"vendor": "firstratedata", "raw_dir": "input", "adjusted_dir": "input"},
    {"include_holdout": "true", "snapshot_binding_verified": "true", "sample": str(PRIVATE)},
])
def test_unknown_or_mixed_input_metadata_is_internal_even_with_matching_hash(extra):
    from algua.provenance.research_disclosure import public_bars
    from algua.provenance.snapshot import SnapshotRecord, compute_snapshot_id
    from algua.provenance.snapshot_evidence import project_snapshot_record

    bars = canonical_bars_record(extra)
    before = json.dumps(bars, sort_keys=True)
    record = SnapshotRecord.from_dict(bars)
    assert record.to_dict() == bars  # Canonical INTERNAL storage remains legal.
    assert compute_snapshot_id(record.metadata, record.content_hash) == bars["snapshot_id"]
    assert project_snapshot_record(bars["snapshot_id"], bars)["status"] == "VALID"
    assert public_bars(bars) == {"invalid_fields": True}
    assert json.dumps(bars, sort_keys=True) == before
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        wf = wf_result()
        wf.snapshot_id, wf.bars_provenance = bars["snapshot_id"], bars
        run_id = record_walk_forward_run(repo, "synthetic", wf)
        # Also read pre-repair bytes without rewriting that history.
        with conn:
            conn.execute("UPDATE runs SET config_json=? WHERE id=?", (json.dumps({
                "params": PARAMS, "run_provenance": {"bars": bars}}), run_id))
        stored = conn.execute("SELECT config_json FROM runs WHERE id=?", (run_id,)).fetchone()[0]
        detail = run_detail_payload(repo, run_id)
        assert detail["snapshot_id"] == bars["snapshot_id"]
        assert detail["config_json"]["run_provenance"]["bars"] == {"invalid_fields": True}
        assert detail["config_json"]["params"] == PARAMS
        for args in [["runs", "show", str(run_id)], ["runs", "list"],
                     ["runs", "board", "--include-evidence"]]:
            output = CliRunner().invoke(app, args)
            assert output.exit_code == 0, output.output
            assert str(PRIVATE) not in output.stdout
        assert conn.execute("SELECT config_json FROM runs WHERE id=?",
                            (run_id,)).fetchone()[0] == stored
        assert conn.execute("SELECT count(*) FROM holdout_evaluations").fetchone()[0] == 0


@pytest.mark.parametrize("unsupported", [False, True])
@pytest.mark.parametrize("surface", ["walk-forward", "sweep"])
def test_closed_input_admission_through_cli_batches_tracking_and_kb(
    tmp_path, monkeypatch, unsupported, surface,
):
    import mlflow
    from mlflow.tracking import MlflowClient

    from algua.backtest.sweep import SweepResult
    from algua.cli import backtest_cmd
    from algua.evaluation import sweep_run
    from algua.knowledge.metrics import latest_run_metrics
    from algua.knowledge.sync import render_results_block
    from tests.test_run_provenance import COSTS

    bars = canonical_bars_record({"measurement": str(PRIVATE)} if unsupported else {})
    original = json.dumps(bars, sort_keys=True)
    expected = {"invalid_fields": True} if unsupported else bars
    wf = wf_result()
    wf.snapshot_id, wf.bars_provenance, wf.execution_costs = bars["snapshot_id"], bars, COSTS
    trial = {"params": PARAMS, "config_hash": "cfg", "score": 0.0, "stability": PUBLIC,
             "bars_provenance": bars, "execution_costs": COSTS}
    sweep = SweepResult(
        strategy="synthetic", data_source=wf.data_source, snapshot_id=wf.snapshot_id,
        timeframe="1d", seed=7, period=wf.period, windows=4, holdout_frac=0.2,
        grid={"holdout_metrics": [PARAMS]}, n_combos=1, rank_by="mean_sharpe",
        ranked=[trial], best=trial, bars_provenance=bars, execution_costs=COSTS)
    assert wf.to_dict()["bars_provenance"] == expected
    assert sweep.to_dict()["bars_provenance"] == expected
    assert sweep.to_dict()["ranked"][0]["bars_provenance"] == expected
    uri = f"sqlite:///{tmp_path / 'closed-tracking.db'}"
    monkeypatch.setenv("ALGUA_MLFLOW_TRACKING_URI", uri)
    monkeypatch.setenv("ALGUA_TRACKING_BACKEND", "mlflow-sqlite")
    mlflow.set_tracking_uri(uri)
    exp = mlflow.create_experiment("synthetic", artifact_location=(tmp_path / "artifacts").as_uri())
    strategy = type("Strategy", (), {"config": type("Config", (), {
        "needs_fundamentals": False, "needs_news": False, "params": PARAMS})()})()
    target = backtest_cmd if surface == "walk-forward" else sweep_run
    monkeypatch.setattr(target, "resolve_eval_inputs",
                        lambda *a, **kw: (strategy, None, None, None))
    monkeypatch.setattr(target, "resolve_universe_inputs", lambda *a: (None, None))
    monkeypatch.setattr(target, "resolve_delisting_inputs", lambda *a: (None, None))
    monkeypatch.setattr(target, "walk_forward" if surface == "walk-forward" else "sweep",
                        lambda *a, **kw: wf if surface == "walk-forward" else sweep)
    for summary in [[], ["--summary"]]:
        args = ["backtest", surface, "synthetic", "--track", *summary]
        if surface == "sweep":
            args += ["--param", "input=1"]
        output = CliRunner().invoke(app, args)
        assert output.exit_code == 0, output.output
        assert str(PRIVATE) not in output.stdout
        payload = json.loads(output.stdout)
        assert payload["bars_provenance"] == expected
        assert payload["snapshot_id"] == bars["snapshot_id"]
        assert "mlflow_tracking_error" not in payload
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        rows = repo.list_runs()
        assert len(rows) == (2 if surface == "walk-forward" else 4)
        for row in rows:
            detail = run_detail_payload(repo, row["id"])
            if row["kind"] == "sweep_trial":
                parent = repo.get_run(detail["derived_from"][0])
                assert parent["snapshot_id"] == bars["snapshot_id"]
            else:
                assert detail["snapshot_id"] == bars["snapshot_id"]
            assert detail["config_json"]["run_provenance"]["bars"] == expected
            assert str(PRIVATE) not in json.dumps(detail)
            if row["kind"] == "sweep_trial":
                assert detail["config_json"]["params"] == PARAMS
            if row["kind"] == "sweep":
                assert detail["config_json"]["grid"] == sweep.grid
        assert conn.execute("SELECT count(*) FROM holdout_evaluations").fetchone()[0] == 0
    client = MlflowClient(tracking_uri=uri)
    tracked = client.search_runs([exp])
    assert len(tracked) == (2 if surface == "walk-forward" else 4)
    artifacts = 0
    for run in tracked:
        assert str(PRIVATE) not in json.dumps(run.to_dictionary())
        for artifact in client.list_artifacts(run.info.run_id):
            artifacts += 1
            path = client.download_artifacts(run.info.run_id, artifact.path, dst_path=str(tmp_path))
            payload = json.loads(Path(path).read_text())
            assert payload["bars_provenance"] == expected
            assert payload["snapshot_id"] == bars["snapshot_id"]
            assert str(PRIVATE) not in json.dumps(payload)
            if surface == "sweep":
                assert payload["grid"] == sweep.grid
                assert payload["best"]["params"] == PARAMS
    assert artifacts == 2
    knowledge = latest_run_metrics("synthetic", tracking_uri=uri)
    assert knowledge is not None
    assert str(PRIVATE) not in json.dumps(knowledge)
    assert str(PRIVATE) not in render_results_block(knowledge)
    assert json.dumps(bars, sort_keys=True) == original


INPUT_PRODUCERS = [
    ("fixture", {}),
    ("yfinance", {"library": "yfinance", "timeframe": "1d", "adjustment": "none"}),
    ("alpaca", {"api": "alpaca", "base_url": "https://data.alpaca.markets/v2",
                 "timeframe": "1d", "adjustment": "raw+all"}),
    ("firstrate", {"vendor": "firstratedata", "symbol": "SYNTHETIC",
                    "raw_file": "raw.csv", "adjusted_file": "adjusted.csv"}),
    ("databento", {"vendor": "databento", "symbol": "SYNTHETIC", "raw_file": "raw.csv"}),
    ("firstrate", {"vendor": "firstratedata", "raw_dir": "raw", "adjusted_dir": "adjusted"}),
    ("databento", {"vendor": "databento", "raw_dir": "raw", "corp_actions_file": "actions",
                   "corp_actions_sha256": "b" * 64, "ca_schema_version": "1"}),
]


@pytest.mark.parametrize("provider,metadata", INPUT_PRODUCERS)
@pytest.mark.parametrize("declared", [False, True])
@pytest.mark.parametrize("requested", [None, (), ("requested_start",), ("requested_end",),
                                        ("requested_start", "requested_end")])
def test_supported_complete_input_shapes_keep_exact_bytes_and_identity(
    provider, metadata, declared, requested,
):
    from algua.provenance.research_disclosure import public_bars
    from algua.provenance.snapshot import SnapshotRecord, compute_snapshot_id

    bars = canonical_bars_record(source_metadata=metadata, provider=provider)
    source = bars["source_metadata"]
    if not declared:
        del source["research_provenance"]
    if requested is not None:
        source.update({"observed_start": bars["start"], "observed_end": bars["end"],
                       "content_hash_algorithm": "bars-symbol-merkle-v1"})
        if declared:
            envelope = json.loads(source["research_provenance"])
            envelope.update(coverage_start=bars["start"], coverage_end=bars["end"])
            source["research_provenance"] = json.dumps(
                envelope, sort_keys=True, separators=(",", ":"))
        for key in requested:
            source[key] = bars["start"] if key.endswith("start") else bars["end"]
    record = SnapshotRecord.from_dict(bars)
    bars["snapshot_id"] = compute_snapshot_id(record.metadata, record.content_hash)
    before = json.dumps(bars, sort_keys=True, separators=(",", ":"))
    assert public_bars(bars) == bars
    assert public_bars(public_bars(bars)) == bars
    assert json.dumps(public_bars(bars), sort_keys=True, separators=(",", ":")) == before
    assert json.dumps(bars, sort_keys=True, separators=(",", ":")) == before


@pytest.mark.parametrize("change", ["missing", "value_type", "constant", "provider", "binding",
                                    "envelope", "envelope_provider", "envelope_coverage",
                                    "stream_partial", "stream_dates", "stream_algorithm"])
def test_known_shape_does_not_replace_envelope_binding_or_field_validation(change):
    from algua.provenance.research_disclosure import public_bars
    from algua.provenance.snapshot import SnapshotRecord, compute_snapshot_id

    bars = canonical_bars_record()
    source = bars["source_metadata"]
    if change == "missing":
        del source["timeframe"]
    elif change == "value_type":
        source["timeframe"] = 1
    elif change == "constant":
        source["library"] = "other"
    elif change == "provider":
        bars["provider"] = "other"
    elif change == "binding":
        bars["content_hash"] = "c" * 64
    elif change.startswith("envelope"):
        envelope = json.loads(source["research_provenance"])
        if change == "envelope":
            envelope["note"] = str(PRIVATE)
        elif change == "envelope_provider":
            envelope["provider"] = "other"
        else:
            envelope["coverage_start"] = "2020-01-01"
        source["research_provenance"] = json.dumps(envelope, sort_keys=True, separators=(",", ":"))
    else:
        source["observed_start"] = bars["start"]
        if change != "stream_partial":
            source.update(observed_end=bars["end"], content_hash_algorithm="bars-symbol-merkle-v1")
        if change == "stream_dates":
            source["observed_start"] = "not-a-date"
        if change == "stream_algorithm":
            source["content_hash_algorithm"] = "other"
    if change != "binding":
        record = SnapshotRecord.from_dict(bars)
        bars["snapshot_id"] = compute_snapshot_id(record.metadata, record.content_hash)
    assert public_bars(bars) == {"invalid_fields": True}


@pytest.mark.parametrize("producer", ["yfinance", "alpaca", "firstrate", "databento"])
def test_actual_producers_and_import_cli_keep_complete_input_records(
    tmp_path, monkeypatch, producer,
):
    import sys
    from types import SimpleNamespace

    import pandas as pd

    from algua.data.contracts import BarRequest, DatabentoImportRequest, FirstRateImportRequest
    from algua.data.importers import get_importer
    from algua.data.providers.alpaca import AlpacaBarProvider
    from algua.data.providers.yfinance import YFinanceBarProvider
    from algua.data.store import DataStore
    from algua.provenance.research import DataTier, ProvenanceDeclaration
    from algua.provenance.research_disclosure import public_bars

    store = DataStore(tmp_path / "data")
    if producer == "yfinance":
        raw = pd.DataFrame({"Open": [10.0], "High": [11.0], "Low": [9.0], "Close": [10.0],
                            "Adj Close": [10.0], "Volume": [100.0]},
                           index=pd.Index([pd.Timestamp("2023-01-02")], name="Date"))
        monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=lambda **kw: raw))
        chunk = YFinanceBarProvider().get_bars(
            BarRequest(("SYNTHETIC",), "2023-01-01", "2024-01-01"))
    elif producer == "alpaca":
        monkeypatch.setattr(AlpacaBarProvider, "_fetch_bars", lambda *a, **kw: {"bars": {
            "SYNTHETIC": [{"t": "2023-01-02T00:00:00Z", "o": 10.0, "h": 11.0, "l": 9.0,
                           "c": 10.0, "v": 100.0}]}})
        chunk = AlpacaBarProvider(api_key="fixture", api_secret="fixture").get_bars(
            BarRequest(("SYNTHETIC",), "2023-01-01", "2024-01-01"))
    else:
        raw_dir, adjusted_dir = tmp_path / "raw", tmp_path / "adjusted"
        raw_dir.mkdir()
        adjusted_dir.mkdir()
        if producer == "firstrate":
            for directory, suffix in [(raw_dir, "UNADJUSTED"), (adjusted_dir, "adjsplitdiv")]:
                (directory / f"SYNTHETIC_full_1day_{suffix}.txt").write_text(
                    "2023-01-02,10,11,9,10,100\n")
            request = FirstRateImportRequest(raw_dir=raw_dir, adjusted_dir=adjusted_dir)
            flags = ["--adjusted-dir", str(adjusted_dir)]
        else:
            from tests.test_databento_importer import _write_raw

            _write_raw(raw_dir / "SYNTHETIC.parquet",
                       pd.to_datetime(["2023-01-02"], utc=True), [10])
            actions = tmp_path / "actions.parquet"
            pd.DataFrame(columns=["symbol", "ex_date", "kind", "value"]).to_parquet(actions)
            request = DatabentoImportRequest(raw_dir=raw_dir, corp_actions_path=actions)
            flags = ["--corp-actions", str(actions)]
        chunk, = list(get_importer(producer).import_bars(request))
        output = CliRunner().invoke(app, ["data", "import-bars", "--vendor", producer,
                                         "--raw-dir", str(raw_dir),
                                         "--as-of", "2024-01-02T00:00:00Z",
                                         "--start", "2023-01-02", "--end", "2023-01-02", *flags])
        assert output.exit_code == 0, output.output
        consolidated = json.loads(output.stdout)["snapshot"]
        assert public_bars(consolidated) == consolidated
    # The actual producer's per-chunk source map is admitted unchanged after canonical capture.
    rec = store.ingest_bars(
        provider=producer, symbols=["SYNTHETIC"], start="2023-01-01", end="2024-01-01",
        as_of="2024-01-02T00:00:00Z", source="synthetic", frame=chunk.frame,
        source_metadata=chunk.source_metadata,
        provenance=ProvenanceDeclaration(DataTier.SYNTHETIC_FIXTURE, "fixture/v1",
                                         ("synthetic_not_market_data",)))
    bars = rec.to_dict()
    before = json.dumps(bars, sort_keys=True)
    assert public_bars(bars) == bars
    wf = wf_result()
    wf.snapshot_id, wf.bars_provenance = rec.snapshot_id, bars
    assert wf.to_dict()["bars_provenance"] == bars
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        run_id = record_walk_forward_run(repo, "synthetic", wf)
        assert run_detail_payload(repo, run_id)["config_json"]["run_provenance"]["bars"] == bars
        assert conn.execute("SELECT count(*) FROM holdout_evaluations").fetchone()[0] == 0
    assert json.dumps(bars, sort_keys=True) == before


@pytest.mark.parametrize("declared", [False, True])
def test_original_binding_is_required_independently_of_declared_envelope(declared):
    from algua.provenance.research_disclosure import public_bars
    from algua.provenance.snapshot import SnapshotRecord, compute_snapshot_id

    bars = canonical_bars_record()
    if not declared:
        del bars["source_metadata"]["research_provenance"]
        record = SnapshotRecord.from_dict(bars)
        bars["snapshot_id"] = compute_snapshot_id(record.metadata, record.content_hash)
    assert public_bars(bars) == bars
    bars["snapshot_id"] = "0" * 16
    assert public_bars(bars) == {"invalid_fields": True}


@pytest.mark.parametrize("bad", ["parent/input", json.dumps({"measurement": PRIVATE})])
def test_known_importer_filename_fields_require_input_names(bad):
    from algua.provenance.research_disclosure import public_bars

    bars = canonical_bars_record(source_metadata={
        "vendor": "firstratedata", "raw_dir": bad, "adjusted_dir": "adjusted"},
        provider="firstrate")
    assert public_bars(bars) == {"invalid_fields": True}


def test_pilot_recipe_input_envelope_is_exact_and_never_grants_verified_pit():
    from algua.provenance.research import (
        PILOT_PROXY_LIMITATIONS,
        DataTier,
        ProvenanceDeclaration,
        build_envelope,
        encode_envelope,
    )
    from algua.provenance.research_disclosure import public_bars
    from algua.provenance.snapshot import SnapshotRecord, compute_snapshot_id

    # Metadata-only synthetic fixture of the recipe; no market payload or tail is read/evaluated.
    bars = canonical_bars_record()
    envelope = build_envelope(ProvenanceDeclaration(DataTier.PILOT_REAL_PROXY, "current-sp400/v1"),
                              provider="yfinance", coverage_start="2023-01-02",
                              coverage_end="2023-12-29")
    raw = encode_envelope(envelope)
    bars["source_metadata"]["research_provenance"] = raw
    record = SnapshotRecord.from_dict(bars)
    bars["snapshot_id"] = compute_snapshot_id(record.metadata, record.content_hash)
    assert public_bars(bars) == bars
    assert public_bars(bars)["source_metadata"]["research_provenance"] == raw
    assert set(json.loads(raw)["limitations"]) == PILOT_PROXY_LIMITATIONS
    unsupported = json.loads(raw) | {"data_tier": "verified_pit", "limitations": []}
    bars["source_metadata"]["research_provenance"] = json.dumps(
        unsupported, sort_keys=True, separators=(",", ":"))
    record = SnapshotRecord.from_dict(bars)
    bars["snapshot_id"] = compute_snapshot_id(record.metadata, record.content_hash)
    assert public_bars(bars) == {"invalid_fields": True}


def test_importer_current_directory_name_survives_exactly():
    from algua.provenance.research_disclosure import public_bars

    # CLI Path(".").name is empty; it is still a supported input directory name.
    bars = canonical_bars_record(source_metadata={
        "vendor": "firstratedata", "raw_dir": Path(".").name, "adjusted_dir": "adjusted"},
        provider="firstrate")
    assert public_bars(bars) == bars


@pytest.mark.parametrize("field", ["row_count", "schema_version"])
@pytest.mark.parametrize("exponent", ["1e999", "-1e999"])
def test_historical_integer_overflow_is_invalid_without_breaking_cli_neighbors(field, exponent):
    from algua.provenance.research_disclosure import public_bars

    bars = canonical_bars_record()
    wf = wf_result()
    wf.snapshot_id, wf.bars_provenance = bars["snapshot_id"], bars
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        healthy = record_walk_forward_run(repo, "healthy", wf)
        malformed = repo.record_run("walk_forward", "malformed")
        config = json.dumps({"run_provenance": {"bars": bars | {field: "overflow"}}})
        config = config.replace('"overflow"', exponent)  # Valid JSON, non-finite after decoding.
        with conn:
            conn.execute("UPDATE runs SET config_json=? WHERE id=?", (config, malformed))
        before = [tuple(row) for row in conn.execute("SELECT * FROM runs")]
        outputs = []
        for _ in range(2):
            outputs.append({
                "list": CliRunner().invoke(app, ["runs", "list"]),
                "malformed": CliRunner().invoke(app, ["runs", "show", str(malformed)]),
                "healthy": CliRunner().invoke(app, ["runs", "show", str(healthy)]),
            })
            assert [tuple(row) for row in conn.execute("SELECT * FROM runs")] == before
            assert conn.execute("SELECT count(*) FROM holdout_evaluations").fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM holdout_returns").fetchone()[0] == 0
        for results in outputs:
            for result in results.values():
                assert result.exit_code == 0, result.stdout
            listing = json.loads(results["list"].stdout)["runs"]
            by_id = {row["id"]: row for row in listing}
            assert by_id[healthy]["config_json"]["run_provenance"]["bars"] == bars
            assert by_id[malformed]["config_json"]["run_provenance"]["bars"] == {
                "invalid_fields": True}
            bad = json.loads(results["malformed"].stdout)
            assert bad["config_json"]["run_provenance"]["bars"] == {"invalid_fields": True}
            good = json.loads(results["healthy"].stdout)
            assert good["config_json"]["run_provenance"]["bars"] == bars
            assert good["mean_window_sharpe"] == 0.0
            assert good["min_window_sharpe"] == -2.5
    assert public_bars(json.loads(config)["run_provenance"]["bars"]) == {"invalid_fields": True}
    assert public_bars(bars) == bars
