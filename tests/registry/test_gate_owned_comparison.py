"""Actual default-agent failing CLI writer, on explicitly synthetic owned data only."""

from __future__ import annotations

import json
import shutil

import pytest

from algua.registry.db import registry_conn
from algua.registry.store import SqliteStrategyRepository
from algua.registry.strategy_board import strategy_board_payload
from tests._gate_comparison_fixture import generate


@pytest.fixture(scope="module")
def produced(tmp_path_factory):
    root = tmp_path_factory.mktemp("actual-gate-producer")
    with pytest.MonkeyPatch.context() as patch:
        for key, path in (
            ("DB_PATH", "registry.db"),
            ("DATA_DIR", "data"),
            ("KNOWLEDGE_DIR", "kb"),
        ):
            patch.setenv(f"ALGUA_{key}", str(root / path))
        fixture = generate()
    return root, fixture


@pytest.fixture
def owned(produced, tmp_path, monkeypatch):
    root, fixture = produced
    shutil.copyfile(root / "registry.db", tmp_path / "registry.db")
    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "registry.db"))
    return fixture


def test_actual_failed_gate_is_comparable_without_private_wf_reads(owned):
    fixture = owned
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        default = strategy_board_payload(repo)
        before = conn.total_changes
        board = strategy_board_payload(repo, snapshot_evidence=lambda _: None)
        assert conn.total_changes == before
        assert strategy_board_payload(repo) == default
        for row in board["rows"]:
            assert row["stage"] == "backtested"
            assert row["latest_gate"]["passed"] is False
            assert row["evidence"]["oos_interval"]["status"] == "VALID"
            assert (
                row["evidence"]["snapshot_provenance"]["value"]["data_tier"] == "synthetic_fixture"
            )
            comparison = row["evidence"]["comparison"]
            assert comparison["status"] == "COMPARABLE", comparison
            assert comparison["context"]["data_tier"] == "synthetic_fixture"
            gate = repo.get_run(row["latest_gate"]["run_id"])
            record = json.loads(gate["config_json"])["gate_comparison_record"]
            assert record.get("gate_run_id") == gate["id"]
            sibling = repo.get_run(json.loads(gate["derived_from"])[0])
            assert sibling["sharpe_oos"] is None and sibling["ann_vol_oos"] is None
            assert "comparison_context" not in json.loads(sibling["config_json"])
        assert len({r["evidence"]["comparison"]["cohort_id"] for r in board["rows"]}) == 1
        assert len(fixture["strategies"]) == 2


@pytest.mark.parametrize(
    "field",
    [
        "schema_version",
        "strategy_id",
        "wf_run_id",
        "gate_run_id",
        "gate_evaluation_id",
        "holdout_evaluation_id",
        "series_holdout_id",
        "context",
        "public_record",
        "metrics",
    ],
)
def test_each_record_binding_is_independently_required(owned, field):
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        gate = repo.list_runs(kind="gate")[0]
        config = json.loads(gate["config_json"])
        config["gate_comparison_record"][field] = None
        with conn:
            conn.execute(
                "UPDATE runs SET config_json=? WHERE id=?", (json.dumps(config), gate["id"])
            )
        board = strategy_board_payload(repo, snapshot_evidence=lambda _: None)
        bad = next(r for r in board["rows"] if r["strategy_id"] == gate["strategy_id"])
        assert bad["evidence"]["comparison"]["status"] == "UNKNOWN"
        assert (
            sum(r["evidence"]["comparison"]["status"] == "COMPARABLE" for r in board["rows"]) == 1
        )


@pytest.mark.parametrize(
    "table,field,value",
    [
        ("holdout_evaluations", "committed_at", None),
        ("holdout_evaluations", "config_hash", "corrupt"),
        ("holdout_evaluations", "snapshot_id", "corrupt"),
        ("holdout_evaluations", "data_source", "corrupt"),
        ("holdout_evaluations", "period_start", "2020-01-01"),
        ("holdout_evaluations", "period_end", "2026-01-01"),
        ("holdout_evaluations", "holdout_start", "2020-01-01"),
        ("holdout_evaluations", "holdout_end", "2026-01-01"),
        ("holdout_evaluations", "holdout_frac", 0.3),
        ("holdout_evaluations", "reused", 1),
        ("holdout_evaluations", "strategy_id", 2),
        ("holdout_returns", "strategy_id", 2),
        ("holdout_returns", "holdout_evaluation_id", 2),
        ("holdout_returns", "n_bars", 1),
        ("holdout_returns", "created_at", "2000-01-01T00:00:00Z"),
        ("gate_evaluations", "strategy_id", 2),
        ("gate_evaluations", "code_hash", "corrupt"),
        ("gate_evaluations", "config_hash", "corrupt"),
        ("gate_evaluations", "dependency_hash", "corrupt"),
        ("gate_evaluations", "snapshot_id", "corrupt"),
        ("gate_evaluations", "holdout_n_bars", 1),
        ("gate_evaluations", "holdout_frac", 0.3),
        ("gate_evaluations", "passed", 1),
        ("gate_evaluations", "decision_json", "{}"),
    ],
)
def test_authoritative_rows_cannot_be_replaced_by_consistent_claims(owned, table, field, value):
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        gate = repo.list_runs(kind="gate")[-1]  # identity 1
        record = json.loads(gate["config_json"])["gate_comparison_record"]
        pointer = {
            "holdout_evaluations": "holdout_evaluation_id",
            "holdout_returns": "series_holdout_id",
            "gate_evaluations": "gate_evaluation_id",
        }
        # Parameterized identifiers are the fixed test inventory above, never user input.
        if table == "holdout_returns" and field == "holdout_evaluation_id":
            # Keep the independent other series healthy and avoid the UNIQUE constraint.
            with conn:
                conn.execute("DELETE FROM holdout_returns WHERE holdout_evaluation_id=2")
        with conn:
            conn.execute(
                f"UPDATE {table} SET {field}=? WHERE id=?", (value, record[pointer[table]])
            )
        row = next(
            r
            for r in strategy_board_payload(repo, snapshot_evidence=lambda _: None)["rows"]
            if r["strategy_id"] == gate["strategy_id"]
        )
        assert row["evidence"]["comparison"]["status"] == "UNKNOWN"


@pytest.mark.parametrize(
    "field,value",
    [
        ("ann_vol_oos", 0),
        ("ann_vol_oos", -0.1),
        ("ann_vol_oos", float("inf")),
        ("sharpe_oos", None),
        ("sharpe_oos", float("inf")),
        ("max_drawdown_oos", -1.1),
        ("max_drawdown_oos", 0.1),
        ("total_return_oos", -1.1),
        ("n_obs_oos", 0),
    ],
)
def test_bad_authoritative_gate_metrics_stay_unknown_even_if_record_matches(owned, field, value):
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        gate = repo.list_runs(kind="gate")[0]
        config = json.loads(gate["config_json"])
        config["gate_comparison_record"]["metrics"][field] = value
        with conn:
            conn.execute(
                f"UPDATE runs SET {field}=?,config_json=? WHERE id=?",
                (value, json.dumps(config), gate["id"]),
            )
        row = next(
            r
            for r in strategy_board_payload(repo, snapshot_evidence=lambda _: None)["rows"]
            if r["strategy_id"] == gate["strategy_id"]
        )
        assert row["evidence"]["comparison"]["status"] == "UNKNOWN"


@pytest.mark.parametrize(
    "location,field,value",
    [
        ("context", "execution", None),
        ("context", "embargo", 0),
        ("context", "holdout_frac", 0.3),
        ("context", "windows", []),
        ("public_record", "execution", None),
        ("public_record", "strategy_id", 999),
    ],
)
def test_context_claims_do_not_replace_independent_execution_and_windows(
    owned, location, field, value
):
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        gate = repo.list_runs(kind="gate")[0]
        config = json.loads(gate["config_json"])
        config["gate_comparison_record"][location][field] = value
        with conn:
            conn.execute(
                "UPDATE runs SET config_json=? WHERE id=?", (json.dumps(config), gate["id"])
            )
        row = next(
            r
            for r in strategy_board_payload(repo, snapshot_evidence=lambda _: None)["rows"]
            if r["strategy_id"] == gate["strategy_id"]
        )
        assert row["evidence"]["comparison"]["status"] == "UNKNOWN"


@pytest.mark.parametrize("setting,value", [("fixed_fees", 0.1), ("size_granularity", 0.01)])
def test_changed_actual_cost_or_execution_is_unsupported_without_relaxing_gate(
    tmp_path,
    monkeypatch,
    setting,
    value,
    produced,
):
    import vectorbt as vbt
    from typer.testing import CliRunner

    from algua.cli.main import app
    from tests._gate_comparison_fixture import NAMES

    for key, path in (("DB_PATH", "registry.db"), ("DATA_DIR", "data"), ("KNOWLEDGE_DIR", "kb")):
        monkeypatch.setenv(f"ALGUA_{key}", str(tmp_path / path))
    runner = CliRunner()

    def actual_cli(*args):
        result = runner.invoke(app, list(args))
        assert result.exit_code == 0, result.stdout
        output = json.loads(result.stdout)
        assert output["ok"] is True
        return output

    original = vbt.settings["portfolio"][setting]
    try:
        # Real numerical input, consumed by the real from_orders producer; no result/auth mock.
        vbt.settings["portfolio"][setting] = value
        generate(names=(NAMES[0],), invoke=actual_cli)
    finally:
        vbt.settings["portfolio"][setting] = original
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        row = strategy_board_payload(repo, snapshot_evidence=lambda _: None)["rows"][0]
        assert row["stage"] == "backtested" and row["latest_gate"]["passed"] is False
        assert row["evidence"]["oos_interval"]["status"] == "VALID"
        assert row["evidence"]["comparison"]["status"] == "UNKNOWN"
        assert conn.execute("SELECT count(*) FROM holdout_returns").fetchone()[0] == 1
        import sqlite3
        from contextlib import closing

        with closing(sqlite3.connect(produced[0] / "registry.db")) as baseline:
            original_metrics = baseline.execute(
                "SELECT sharpe_oos,total_return_oos FROM runs WHERE kind='gate' AND strategy_id=1"
            ).fetchone()
        assert (
            row["latest_gate"]["sharpe_oos"],
            row["latest_gate"]["total_return_oos"],
        ) != original_metrics


@pytest.mark.parametrize(
    "namespace,field",
    [
        ("public_record", k)
        for k in (
            "schema_version",
            "strategy_id",
            "provenance",
            "context",
            "windows",
            "statistics",
            "inputs",
            "research_inputs",
            "execution",
            "params",
        )
    ]
    + [
        ("metrics", k)
        for k in (
            "sharpe_oos",
            "total_return_oos",
            "max_drawdown_oos",
            "ann_vol_oos",
            "n_obs_oos",
        )
    ]
    + [
        ("context", k)
        for k in (
            "schema_version",
            "protocol",
            "metrics",
            "timeframe",
            "period_start",
            "period_end",
            "oos",
        )
    ],
)
def test_each_closed_declaration_cannot_be_dropped(owned, namespace, field):
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        gate = repo.list_runs(kind="gate")[0]
        config = json.loads(gate["config_json"])
        config["gate_comparison_record"][namespace][field] = None
        with conn:
            conn.execute(
                "UPDATE runs SET config_json=? WHERE id=?", (json.dumps(config), gate["id"])
            )
        row = next(
            r
            for r in strategy_board_payload(repo, snapshot_evidence=lambda _: None)["rows"]
            if r["strategy_id"] == gate["strategy_id"]
        )
        assert row["evidence"]["comparison"]["status"] == "UNKNOWN"


def test_boolean_metric_claim_is_not_an_observed_zero(owned):
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        gate = repo.list_runs(kind="gate")[0]
        config = json.loads(gate["config_json"])
        config["gate_comparison_record"]["metrics"]["total_return_oos"] = False
        decision = json.loads(
            conn.execute(
                "SELECT decision_json FROM gate_evaluations WHERE id=?", (gate["gate_id"],)
            ).fetchone()[0]
        )
        for check in decision["checks"]:
            if check["name"] == "holdout_return":
                check["value"] = 0.0
        with conn:
            conn.execute(
                "UPDATE runs SET config_json=?,total_return_oos=0 WHERE id=?",
                (json.dumps(config), gate["id"]),
            )
            conn.execute(
                "UPDATE gate_evaluations SET decision_json=? WHERE id=?",
                (json.dumps(decision), gate["gate_id"]),
            )
        row = next(
            r
            for r in strategy_board_payload(repo, snapshot_evidence=lambda _: None)["rows"]
            if r["strategy_id"] == gate["strategy_id"]
        )
        assert row["evidence"]["comparison"]["status"] == "UNKNOWN"
        # A genuine numeric zero remains an observation on the same nondegenerate gate.
        config["gate_comparison_record"]["metrics"]["total_return_oos"] = 0.0
        with conn:
            conn.execute(
                "UPDATE runs SET config_json=? WHERE id=?", (json.dumps(config), gate["id"])
            )
        row = next(
            r
            for r in strategy_board_payload(repo, snapshot_evidence=lambda _: None)["rows"]
            if r["strategy_id"] == gate["strategy_id"]
        )
        assert row["evidence"]["comparison"]["status"] == "COMPARABLE"
        assert row["latest_gate"]["total_return_oos"] == 0.0


@pytest.mark.parametrize("damage", ["nonfinite", "missing_reference"])
def test_unusable_comparison_metadata_does_not_abort_the_gate_transaction(owned, damage):
    from algua.registry.gate_comparison_write import seal_gate_comparison

    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        gate = repo.list_runs(kind="gate")[0]
        config = json.loads(gate["config_json"])
        pending = config["gate_comparison_record"]
        del pending["gate_run_id"]
        if damage == "nonfinite":
            pending["metrics"]["ann_vol_oos"] = float("nan")
        else:
            del pending["wf_run_id"]
        with conn:
            conn.execute(
                "UPDATE runs SET config_json=? WHERE id=?", (json.dumps(config), gate["id"])
            )
            seal_gate_comparison(conn, gate["id"])
        row = next(
            r
            for r in strategy_board_payload(repo, snapshot_evidence=lambda _: None)["rows"]
            if r["strategy_id"] == gate["strategy_id"]
        )
        assert row["evidence"]["comparison"]["status"] == "UNKNOWN"
        assert row["latest_gate"]["passed"] is False
