"""Ordinary producer controls. Generated bars here are engineering fixtures, not market proof."""
from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from algua.cli.main import app
from algua.data.research_provenance import DataTier, ProvenanceDeclaration
from algua.registry.db import registry_conn
from algua.registry.store import SqliteStrategyRepository
from algua.registry.strategy_board import strategy_board_payload
from tests.test_run_provenance import END, NAME, START, snapshot


def ordinary(tmp_path, monkeypatch):
    store, original = snapshot(tmp_path, monkeypatch)
    frame = store.read_bars(original.snapshot_id).reset_index().rename(columns={"timestamp": "ts"})
    rec = store.ingest_bars(
        provider="fixture", symbols=list(original.symbols), start=START, end=END,
        as_of="2025-01-01T00:00:00+00:00", source="engineering-only-declared-tier-control",
        frame=frame, provenance=ProvenanceDeclaration(DataTier.PILOT_REAL_PROXY, "fixture/v1"),
    )
    runner = CliRunner()
    registered = runner.invoke(app, ["registry", "add", NAME])
    assert registered.exit_code == 0, registered.stdout
    result = runner.invoke(app, ["backtest", "walk-forward", NAME, "--snapshot", rec.snapshot_id,
                                 "--start", START, "--end", END, "--windows", "2"])
    assert result.exit_code == 0, result.stdout
    return json.loads(result.stdout)


def test_ordinary_registered_cli_persists_identity_and_projects_without_gate(tmp_path, monkeypatch):
    output = ordinary(tmp_path, monkeypatch)
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        identity = repo.get(NAME).id
        runs = repo.list_runs()
        assert len(runs) == 1 and runs[0]["kind"] == "walk_forward"
        run = runs[0]
        assert output["recorded_run"] == {
            "run_id": run["id"], "strategy_id": identity, "kind": "walk_forward",
        }
        assert run["strategy_id"] == identity
        assert "holdout_metrics" not in output and "holdout_returns" not in output
        default = strategy_board_payload(repo)
        assert default == {"schema_version": "strategy-board/v1", "count": 1, "rows": [{
            "strategy_id": identity, "name": NAME, "family": None, "stage": "idea",
            "latest_gate": None,
        }]}
        board = strategy_board_payload(repo, snapshot_evidence=lambda _: {}, research=True)
        row = board["rows"][0]
        assert row["latest_gate"] is None
        assert row["latest_research"]["kind"] == "walk_forward"
        assert row["latest_research"]["run_id"] == run["id"]
        assert row["latest_research"]["sharpe_oos"] == run["sharpe_oos"]
        assert row["evidence"]["comparison"]["status"] == "COMPARABLE"
        assert row["evidence"]["run_id"] == run["id"]
        assert conn.execute("SELECT count(*) FROM holdout_evaluations").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM gate_evaluations").fetchone()[0] == 0
        assert strategy_board_payload(repo) == default


def test_latest_failure_and_unbound_history_never_fall_back_or_rebind(tmp_path, monkeypatch):
    ordinary(tmp_path, monkeypatch)
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        identity = repo.get(NAME).id
        good = repo.list_runs()[0]["id"]
        failed = repo.record_run("walk_forward", NAME, strategy_id=identity,
                                 config={"error": "evaluation failed"})
        row = strategy_board_payload(repo, research=True)["rows"][0]
        assert row["latest_research"]["run_id"] == failed
        assert row["latest_research"]["sharpe_oos"] is None
        assert row["evidence"]["comparison"]["status"] == "UNKNOWN"
        from algua.registry.research_runs import research_run_payload

        pinned = research_run_payload(repo, identity, good)
        assert pinned["evidence"]["comparison"]["status"] == "COMPARABLE"
        unbound = repo.record_run("walk_forward", "reused-name", metrics={"sharpe_oos": 99})
        other = repo.add("reused-name")
        assert research_run_payload(repo, other.id)["latest_research"] is None
        with pytest.raises(ValueError, match="does not belong"):
            research_run_payload(repo, other.id, good)
        with pytest.raises(ValueError, match="does not belong"):
            research_run_payload(repo, other.id, unbound)
        gate = repo.record_run("gate", NAME, strategy_id=identity, metrics={"sharpe_oos": 123})
        assert strategy_board_payload(repo)["rows"][0]["latest_gate"]["run_id"] == gate
        projected = strategy_board_payload(repo, research=True)["rows"][0]
        assert projected["latest_research"]["run_id"] == failed


def test_cli_research_exact_run_and_summary_pointer(tmp_path, monkeypatch):
    output = ordinary(tmp_path, monkeypatch)
    pointer = output["recorded_run"]
    result = CliRunner().invoke(app, ["runs", "research", str(pointer["strategy_id"]),
                                    "--run-id", str(pointer["run_id"])])
    assert result.exit_code == 0, result.stdout
    detail = json.loads(result.stdout)
    assert set(detail) == {
        "ok", "strategy_id", "latest_research", "evidence", "recorded_provenance"}
    assert detail["latest_research"]["run_id"] == pointer["run_id"]
    assert detail["latest_research"]["kind"] == "walk_forward"
    assert "passed" not in detail["latest_research"]




@pytest.mark.parametrize("field", [
    "cost", "bars", "context", "oos", "scalar", "snapshot", "identity", "binding",
    "schema", "components", "passed", "lineage", "boolean_scalar",
])
def test_independent_record_corruption_is_unranked(tmp_path, monkeypatch, field):
    ordinary(tmp_path, monkeypatch)
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        run = repo.list_runs()[0]
        config = json.loads(run["config_json"])
        if field == "cost":
            config["run_provenance"]["execution_costs"]["fees"] = 0.42
        elif field == "bars":
            config["run_provenance"]["bars"]["content_hash"] = "a" * 64
        elif field == "context":
            config["comparison_context"]["execution"]["fill_basis"] = "adjusted_close"
        elif field == "oos":
            config["comparison_context"]["oos"]["n_bars"] += 1
        elif field == "binding":
            config["research_record"]["inputs_sha256"] = "b" * 64
        elif field == "boolean_scalar":
            config["research_record"]["metrics"]["pct_positive_windows"] = True
        else:
            column, value = {
                "scalar": ("sharpe_oos", 99), "snapshot": ("snapshot_id", "other"),
                "identity": ("config_hash", "other"), "schema": ("metric_schema_version", 2),
                "components": ("components", '[{"model":"other"}]'), "passed": ("passed", 0),
                "lineage": ("derived_from", '[123]'),
            }[field]
            conn.execute(f"UPDATE runs SET {column}=? WHERE id=?", (value, run["id"]))
        conn.execute("UPDATE runs SET config_json=? WHERE id=?", (json.dumps(config), run["id"]))
        result = strategy_board_payload(repo, research=True)["rows"][0]
        assert result["evidence"]["comparison"]["status"] == "UNKNOWN"
        assert result["evidence"]["comparison"]["observed_metric_sort_enabled"] is False


def test_terminal_assumption_is_recorded_and_outside_the_comparison_class(tmp_path, monkeypatch):
    ordinary(tmp_path, monkeypatch)
    with registry_conn() as conn:
        snapshot_id = SqliteStrategyRepository(conn).list_runs()[0]["snapshot_id"]
    result = CliRunner().invoke(app, ["backtest", "walk-forward", NAME, "--snapshot", snapshot_id,
                                     "--start", START, "--end", END, "--windows", "2",
                                     "--assume-terminal-last-close"])
    assert result.exit_code == 0, result.stdout
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        row = strategy_board_payload(repo, research=True)["rows"][0]
        assert row["evidence"]["comparison"]["status"] == "UNKNOWN"
        assert row["evidence"]["comparison"]["reasons"] == ["unsupported_modal_inputs"]


@pytest.mark.parametrize("registered", [False, True])
@pytest.mark.parametrize("summary", [False, True])
def test_cli_exact_metadata_shape_and_no_historical_name_rebinding(
    tmp_path, monkeypatch, registered, summary,
):
    snapshot(tmp_path, monkeypatch)
    runner = CliRunner()
    if registered:
        assert runner.invoke(app, ["registry", "add", NAME]).exit_code == 0
    args = ["backtest", "walk-forward", NAME, "--demo", "--start", START, "--end", END,
            "--windows", "2"] + (["--summary"] if summary else [])
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.stdout
    output = json.loads(result.stdout)
    keys = {"bars_provenance", "code_hash", "config_hash", "data_source", "dependency_hash",
            "execution_costs", "fundamentals_snapshot", "holdout_frac", "news_snapshot", "ok",
            "period", "recorded_run", "seed", "snapshot_id", "stability", "strategy",
            "timeframe", "universe_name", "universe_snapshots", "windows"}
    keys |= {"summary"} if summary else {"embargo", "execution_semantics", "window_metrics"}
    assert set(output) == keys
    pointer = output["recorded_run"]
    assert set(pointer) == {"run_id", "strategy_id", "kind"}
    assert pointer["kind"] == "walk_forward"
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        run = repo.get_run(pointer["run_id"])
        assert run["strategy_id"] == pointer["strategy_id"]
        assert (run["strategy_id"] is not None) is registered
        config = json.loads(run["config_json"])
        assert set(config) == {
            "run_provenance", "comparison_context", "research_inputs", "research_record",
        }
        assert config["research_record"]["provenance"] == {
            k: run[k] for k in config["research_record"]["provenance"]}
        assert config["research_record"]["metrics"]["sharpe_oos"] == run["sharpe_oos"]
        assert config["research_record"]["strategy_id"] == pointer["strategy_id"]
        if not registered:
            repo.add(NAME)
            assert strategy_board_payload(repo, research=True)["rows"][0]["latest_research"] is None


def test_actual_protocol_change_creates_distinct_research_cohorts(tmp_path, monkeypatch):
    output = ordinary(tmp_path, monkeypatch)
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        before = strategy_board_payload(repo, research=True)["rows"][0]
        snapshot_id = repo.get_run(output["recorded_run"]["run_id"])["snapshot_id"]
    result = CliRunner().invoke(app, ["backtest", "walk-forward", NAME, "--snapshot", snapshot_id,
                                     "--start", START, "--end", END, "--windows", "3"])
    assert result.exit_code == 0, result.stdout
    with registry_conn() as conn:
        after = strategy_board_payload(SqliteStrategyRepository(conn), research=True)["rows"][0]
    assert after["evidence"]["comparison"]["status"] == "COMPARABLE"
    a, b = after["evidence"]["comparison"], before["evidence"]["comparison"]
    assert a["cohort_id"] != b["cohort_id"]
