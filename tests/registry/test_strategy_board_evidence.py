"""Opt-in strategy-board evidence remains exact-run bound and scalar-only."""
from __future__ import annotations

import sqlite3
from unittest.mock import ANY

import pytest

from algua.registry.db.migrate import migrate
from algua.registry.store import SqliteStrategyRepository
from algua.registry.strategy_board import strategy_board_payload


@pytest.fixture()
def repo() -> SqliteStrategyRepository:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    migrate(conn)
    return SqliteStrategyRepository(conn)


def _holdout(
    repo: SqliteStrategyRepository,
    strategy_id: int,
    *,
    snapshot_id: object = "snapshot-exact",
    period_start: object = "2025-01-01",
    period_end: object = "2025-12-31",
    committed_at: object = "2026-01-01T00:00:00+00:00",
    evaluation_holdout_start: object = "2025-10-01",
    evaluation_holdout_end: object = "2025-12-31",
    return_holdout_start: object = "2025-10-01",
    return_holdout_end: object = "2025-12-31",
) -> int:
    with repo.connection:
        burn = repo.connection.execute(
            "INSERT INTO holdout_evaluations("
            "strategy_id,data_source,snapshot_id,period_start,period_end,holdout_frac,"
            "config_hash,created_at,committed_at,holdout_start,holdout_end) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                strategy_id,
                "fixture",
                snapshot_id,
                period_start,
                period_end,
                0.2,
                "burn-workflow-config-hash-deliberately-not-run-config-hash",
                "2026-01-01T00:00:00+00:00",
                committed_at,
                evaluation_holdout_start,
                evaluation_holdout_end,
            ),
        ).lastrowid
        assert burn is not None
        holdout = repo.connection.execute(
            "INSERT INTO holdout_returns("
            "holdout_evaluation_id,strategy_id,holdout_start,holdout_end,n_bars,"
            "returns_blob,bar_dates_blob,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                burn,
                strategy_id,
                return_holdout_start,
                return_holdout_end,
                63,
                b"not-read",
                b"not-read",
                "2026-01-01T00:00:00+00:00",
            ),
        ).lastrowid
    assert holdout is not None
    return holdout


def test_opt_in_projects_complete_valid_evidence_for_the_selected_run(
    repo: SqliteStrategyRepository,
) -> None:
    strategy = repo.add("alpha")
    holdout_id = _holdout(repo, strategy.id)
    run_id = repo.record_run(
        "gate",
        "alpha",
        strategy_id=strategy.id,
        provenance={
            "config_hash": "gate-run-config-hash-deliberately-not-burn-config-hash",
            "snapshot_id": "snapshot-exact",
            "timeframe": "1d",
            "period_start": "2025-01-01",
            "period_end": "2025-12-31",
        },
        metrics={"n_obs_oos": 63, "sharpe_oos": 0.4},
        series_holdout_id=holdout_id,
    )
    provenance = {
        "status": "VALID",
        "reason": None,
        "value": {
            "schema_version": "pilot-provenance/v1",
            "data_tier": "synthetic_fixture",
            "universe_method": "fixture/v1",
            "limitations": ["synthetic_not_market_data"],
            "coverage_start": "2025-01-01",
            "coverage_end": "2025-12-31",
            "provider": "fixture",
        },
    }

    payload = strategy_board_payload(
        repo,
        snapshot_evidence=lambda snapshot_id: provenance
        if snapshot_id == "snapshot-exact"
        else pytest.fail("selected snapshot pointer changed"),
    )

    assert payload["evidence_schema_version"] == "strategy-board-evidence/v1"
    (row,) = payload["rows"]
    assert row["latest_gate"]["run_id"] == run_id
    assert row["evidence"] == {
        "run_id": run_id,
        "evaluation": {
            "status": "VALID",
            "reason": None,
            "value": {
                "period_start": "2025-01-01",
                "period_end": "2025-12-31",
                "timeframe": "1d",
                "metric_schema_version": 1,
            },
        },
        "oos_interval": {
            "status": "VALID",
            "reason": None,
            "value": {
                "holdout_start": "2025-10-01",
                "holdout_end": "2025-12-31",
                "n_bars": 63,
            },
        },
        "snapshot_provenance": provenance,
        "comparison": {
            "status": "UNKNOWN",
            "observed_metric_sort_enabled": False,
            "reasons": [
                "historical_cost_context_unavailable",
                "homogeneous_comparison_context_unavailable",
            ],
        },
    }


@pytest.mark.parametrize(
    ("holdout_context", "expected_reason"),
    [
        ({"snapshot_id": "snapshot-wrong"}, "snapshot_binding_mismatch"),
        ({"period_start": "2024-01-01"}, "evaluation_binding_mismatch"),
    ],
)
def test_oos_interval_rejects_same_strategy_and_count_from_wrong_evaluation_context(
    repo: SqliteStrategyRepository,
    holdout_context: dict[str, object],
    expected_reason: str,
) -> None:
    strategy = repo.add("alpha")
    valid_holdout_id = _holdout(repo, strategy.id)
    holdout_id = _holdout(repo, strategy.id, **holdout_context)
    run_id = repo.record_run(
        "gate",
        "alpha",
        strategy_id=strategy.id,
        provenance={
            "snapshot_id": "snapshot-exact",
            "timeframe": "1d",
            "period_start": "2025-01-01",
            "period_end": "2025-12-31",
        },
        metrics={"n_obs_oos": 63},
        series_holdout_id=valid_holdout_id,
    )
    assert strategy_board_payload(
        repo, snapshot_evidence=lambda _: {}
    )["rows"][0]["evidence"]["oos_interval"]["status"] == "VALID"
    with repo.connection:
        repo.connection.execute(
            "UPDATE runs SET series_holdout_id=? WHERE id=?", (holdout_id, run_id)
        )

    interval = strategy_board_payload(
        repo,
        snapshot_evidence=lambda _snapshot_id: {
            "status": "UNAVAILABLE",
            "reason": "provenance_absent",
            "value": None,
        },
    )["rows"][0]["evidence"]["oos_interval"]

    assert interval == {"status": "INVALID", "reason": expected_reason, "value": None}


def test_default_projection_is_legacy_shape_and_never_resolves_snapshot(
    repo: SqliteStrategyRepository,
) -> None:
    strategy = repo.add("alpha")
    repo.record_run("gate", "alpha", strategy_id=strategy.id)

    assert strategy_board_payload(repo) == {
        "schema_version": "strategy-board/v1",
        "count": 1,
        "rows": [
            {
                "strategy_id": strategy.id,
                "name": "alpha",
                "family": None,
                "stage": "idea",
                "latest_gate": {
                    "run_id": 1,
                    "created_at": ANY,
                    "passed": None,
                    "sharpe_oos": None,
                    "total_return_oos": None,
                    "max_drawdown_oos": None,
                    "n_obs_oos": None,
                    "mean_window_sharpe": None,
                    "min_window_sharpe": None,
                    "pct_positive_windows": None,
                },
            }
        ],
    }


def test_opt_in_keeps_bare_row_and_invalid_timestamp_evidence_null(
    repo: SqliteStrategyRepository,
) -> None:
    bare = repo.add("bare")
    malformed = repo.add("malformed")
    run_id = repo.record_run("gate", "malformed", strategy_id=malformed.id)
    with repo.connection:
        repo.connection.execute("UPDATE runs SET created_at='naive' WHERE id=?", (run_id,))

    payload = strategy_board_payload(
        repo, snapshot_evidence=lambda _snapshot_id: pytest.fail("no valid selected gate")
    )

    rows = {row["strategy_id"]: row for row in payload["rows"]}
    assert rows[bare.id]["latest_gate"] is None
    assert rows[bare.id]["evidence"] is None
    assert rows[malformed.id]["latest_gate"] is None
    assert rows[malformed.id]["evidence"] is None


def test_evidence_is_latest_not_best_and_uses_only_that_run_pointer(
    repo: SqliteStrategyRepository,
) -> None:
    strategy = repo.add("alpha")
    older = repo.record_run(
        "gate",
        "alpha",
        strategy_id=strategy.id,
        provenance={
            "snapshot_id": "older-labeled",
            "timeframe": "1d",
            "period_start": "2024-01-01",
            "period_end": "2024-12-31",
        },
        metrics={"sharpe_oos": 9.0},
    )
    newest = repo.record_run(
        "gate",
        "alpha",
        strategy_id=strategy.id,
        provenance={"snapshot_id": "newest-unlabeled"},
        metrics={"sharpe_oos": -2.0},
    )
    with repo.connection:
        repo.connection.execute(
            "UPDATE runs SET created_at='2026-01-01T00:00:00+00:00' WHERE id=?", (older,)
        )
        repo.connection.execute(
            "UPDATE runs SET created_at='2026-02-01T00:00:00+00:00' WHERE id=?", (newest,)
        )
    seen: list[str] = []

    def resolve(snapshot_id: str) -> dict[str, object]:
        seen.append(snapshot_id)
        return {"status": "UNAVAILABLE", "reason": "provenance_absent", "value": None}

    (row,) = strategy_board_payload(repo, snapshot_evidence=resolve)["rows"]

    assert row["latest_gate"]["run_id"] == newest
    assert row["latest_gate"]["sharpe_oos"] == -2.0
    assert row["evidence"]["run_id"] == newest
    assert row["evidence"]["evaluation"] == {
        "status": "UNAVAILABLE",
        "reason": "missing_fields",
        "value": None,
    }
    assert seen == ["newest-unlabeled"]


@pytest.mark.parametrize(
    ("updates", "expected"),
    [
        ({"period_start": None}, ("UNAVAILABLE", "missing_fields")),
        ({"period_start": "2025-1-1"}, ("INVALID", "malformed_fields")),
        ({"period_start": "2026-01-01", "period_end": "2025-01-01"},
         ("INVALID", "malformed_fields")),
        ({"timeframe": b"1d"}, ("INVALID", "malformed_fields")),
        ({"metric_schema_version": "oops"}, ("INVALID", "malformed_fields")),
    ],
)
def test_evaluation_is_atomic_for_missing_or_malformed_fields(
    repo: SqliteStrategyRepository,
    updates: dict[str, object],
    expected: tuple[str, str],
) -> None:
    strategy = repo.add("alpha")
    run_id = repo.record_run(
        "gate",
        "alpha",
        strategy_id=strategy.id,
        provenance={
            "timeframe": "1d",
            "period_start": "2025-01-01",
            "period_end": "2025-12-31",
        },
    )
    with repo.connection:
        for column, value in updates.items():
            repo.connection.execute(f"UPDATE runs SET {column}=? WHERE id=?", (value, run_id))

    evidence = strategy_board_payload(
        repo,
        snapshot_evidence=lambda _snapshot_id: pytest.fail("snapshot pointer is absent"),
    )["rows"][0]["evidence"]

    assert evidence["evaluation"] == {
        "status": expected[0],
        "reason": expected[1],
        "value": None,
    }


def _run_with_holdout(
    repo: SqliteStrategyRepository,
    *,
    run_count: object = 63,
    holdout_strategy: int | None = None,
    holdout_count: object = 63,
) -> tuple[int, int, int]:
    strategy = repo.add("alpha")
    foreign = repo.add("foreign")
    holdout_id = _holdout(repo, holdout_strategy or strategy.id)
    with repo.connection:
        repo.connection.execute(
            "UPDATE holdout_returns SET n_bars=? WHERE id=?", (holdout_count, holdout_id)
        )
    run_id = repo.record_run(
        "gate",
        "alpha",
        strategy_id=strategy.id,
        provenance={
            "snapshot_id": "snapshot-exact",
            "timeframe": "1d",
            "period_start": "2025-01-01",
            "period_end": "2025-12-31",
        },
        metrics={"n_obs_oos": 63},
        series_holdout_id=holdout_id,
    )
    with repo.connection:
        repo.connection.execute("UPDATE runs SET n_obs_oos=? WHERE id=?", (run_count, run_id))
    return run_id, strategy.id, foreign.id


@pytest.mark.parametrize(
    ("holdout_context", "expected_reason"),
    [
        ({"committed_at": None}, "malformed_fields"),
        ({"committed_at": "not-a-timestamp"}, "malformed_fields"),
        ({"snapshot_id": None}, "malformed_fields"),
        ({"snapshot_id": b"snapshot-exact"}, "malformed_fields"),
        ({"period_start": ""}, "malformed_fields"),
        ({"period_end": "2025-1-1"}, "malformed_fields"),
        ({"evaluation_holdout_start": None}, "malformed_fields"),
        ({"evaluation_holdout_start": "2025-10-02"}, "interval_binding_mismatch"),
        ({"return_holdout_end": "2025-12-30"}, "interval_binding_mismatch"),
    ],
)
def test_oos_interval_fails_closed_for_malformed_or_mismatched_burn_context(
    repo: SqliteStrategyRepository,
    holdout_context: dict[str, object],
    expected_reason: str,
) -> None:
    strategy = repo.add("alpha")
    holdout_id = _holdout(repo, strategy.id, **holdout_context)
    repo.record_run(
        "gate",
        "alpha",
        strategy_id=strategy.id,
        provenance={
            "snapshot_id": "snapshot-exact",
            "timeframe": "1d",
            "period_start": "2025-01-01",
            "period_end": "2025-12-31",
        },
        metrics={"n_obs_oos": 63},
        series_holdout_id=holdout_id,
    )

    interval = strategy_board_payload(
        repo,
        snapshot_evidence=lambda _snapshot_id: {
            "status": "UNAVAILABLE",
            "reason": "provenance_absent",
            "value": None,
        },
    )["rows"][0]["evidence"]["oos_interval"]

    assert interval == {"status": "INVALID", "reason": expected_reason, "value": None}


def test_oos_interval_rejects_mismatched_associated_evaluation_strategy(
    repo: SqliteStrategyRepository,
) -> None:
    strategy = repo.add("alpha")
    foreign = repo.add("foreign")
    holdout_id = _holdout(repo, strategy.id)
    with repo.connection:
        repo.connection.execute(
            "UPDATE holdout_evaluations SET strategy_id=? WHERE id=("
            "SELECT holdout_evaluation_id FROM holdout_returns WHERE id=?)",
            (foreign.id, holdout_id),
        )
    repo.record_run(
        "gate",
        "alpha",
        strategy_id=strategy.id,
        provenance={
            "snapshot_id": "snapshot-exact",
            "timeframe": "1d",
            "period_start": "2025-01-01",
            "period_end": "2025-12-31",
        },
        metrics={"n_obs_oos": 63},
        series_holdout_id=holdout_id,
    )

    interval = strategy_board_payload(
        repo,
        snapshot_evidence=lambda _snapshot_id: {
            "status": "UNAVAILABLE",
            "reason": "provenance_absent",
            "value": None,
        },
    )["rows"][0]["evidence"]["oos_interval"]

    assert interval == {"status": "INVALID", "reason": "strategy_mismatch", "value": None}


def test_oos_interval_rejects_dangling_associated_evaluation(
    repo: SqliteStrategyRepository,
) -> None:
    strategy = repo.add("alpha")
    holdout_id = _holdout(repo, strategy.id)
    repo.record_run(
        "gate",
        "alpha",
        strategy_id=strategy.id,
        provenance={
            "snapshot_id": "snapshot-exact",
            "timeframe": "1d",
            "period_start": "2025-01-01",
            "period_end": "2025-12-31",
        },
        metrics={"n_obs_oos": 63},
        series_holdout_id=holdout_id,
    )
    evaluation_id = repo.connection.execute(
        "SELECT holdout_evaluation_id FROM holdout_returns WHERE id=?", (holdout_id,)
    ).fetchone()[0]
    repo.connection.execute("PRAGMA foreign_keys=OFF")
    with repo.connection:
        repo.connection.execute("DELETE FROM holdout_evaluations WHERE id=?", (evaluation_id,))
    repo.connection.execute("PRAGMA foreign_keys=ON")

    interval = strategy_board_payload(
        repo,
        snapshot_evidence=lambda _snapshot_id: {
            "status": "UNAVAILABLE",
            "reason": "provenance_absent",
            "value": None,
        },
    )["rows"][0]["evidence"]["oos_interval"]

    assert interval == {
        "status": "INVALID",
        "reason": "dangling_evaluation_pointer",
        "value": None,
    }


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("no_pointer", ("UNAVAILABLE", "no_holdout_pointer")),
        ("dangling", ("INVALID", "dangling_holdout_pointer")),
        ("wrong_strategy", ("INVALID", "strategy_mismatch")),
        ("missing_run_count", ("UNAVAILABLE", "missing_run_oos_count")),
        ("malformed_run_count", ("INVALID", "malformed_fields")),
        ("count_mismatch", ("INVALID", "count_mismatch")),
    ],
)
def test_oos_interval_identity_and_count_validation(
    repo: SqliteStrategyRepository,
    case: str,
    expected: tuple[str, str],
) -> None:
    if case == "no_pointer":
        strategy = repo.add("alpha")
        repo.record_run("gate", "alpha", strategy_id=strategy.id)
    elif case == "dangling":
        strategy = repo.add("alpha")
        run_id = repo.record_run("gate", "alpha", strategy_id=strategy.id)
        repo.connection.execute("PRAGMA foreign_keys=OFF")
        with repo.connection:
            repo.connection.execute("UPDATE runs SET series_holdout_id=999 WHERE id=?", (run_id,))
        repo.connection.execute("PRAGMA foreign_keys=ON")
    elif case == "wrong_strategy":
        first = repo.add("alpha")
        foreign = repo.add("foreign")
        holdout_id = _holdout(repo, foreign.id)
        repo.record_run(
            "gate", "alpha", strategy_id=first.id, metrics={"n_obs_oos": 63},
            series_holdout_id=holdout_id,
        )
    else:
        run_count: object = 63
        holdout_count: object = 63
        if case == "missing_run_count":
            run_count = None
        elif case == "malformed_run_count":
            run_count = "oops"
        elif case == "count_mismatch":
            holdout_count = 62
        _run_with_holdout(repo, run_count=run_count, holdout_count=holdout_count)

    interval = strategy_board_payload(
        repo,
        snapshot_evidence=lambda _snapshot_id: {
            "status": "UNAVAILABLE",
            "reason": "provenance_absent",
            "value": None,
        },
    )["rows"][0]["evidence"]["oos_interval"]
    assert interval == {"status": expected[0], "reason": expected[1], "value": None}


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("snapshot_id", None),
        ("snapshot_id", ""),
        ("snapshot_id", b"snapshot-exact"),
        ("period_start", None),
        ("period_start", "2025-1-1"),
        ("period_end", "2024-12-31"),
    ],
)
def test_oos_interval_requires_authoritative_selected_run_context(
    repo: SqliteStrategyRepository, column: str, value: object,
) -> None:
    run_id, _, _ = _run_with_holdout(repo)
    with repo.connection:
        repo.connection.execute(f"UPDATE runs SET {column}=? WHERE id=?", (value, run_id))
    interval = strategy_board_payload(
        repo, snapshot_evidence=lambda _: {}
    )["rows"][0]["evidence"]["oos_interval"]
    assert interval == {"status": "INVALID", "reason": "malformed_fields", "value": None}


def test_projection_never_reads_holdout_vectors_or_writes(
    repo: SqliteStrategyRepository,
) -> None:
    strategy = repo.add("alpha")
    holdout_id = _holdout(repo, strategy.id)
    repo.record_run(
        "gate", "alpha", strategy_id=strategy.id,
        provenance={
            "snapshot_id": "snapshot-exact",
            "timeframe": "1d",
            "period_start": "2025-01-01",
            "period_end": "2025-12-31",
        },
        metrics={"n_obs_oos": 63},
        series_holdout_id=holdout_id,
    )
    forbidden = {"returns_blob", "bar_dates_blob"}
    reads: set[tuple[str, str]] = set()

    def authorize(action: int, table: str, column: str, _db: str, _trigger: str) -> int:
        if action == sqlite3.SQLITE_READ:
            reads.add((table, column))
        if action == sqlite3.SQLITE_READ and table == "holdout_returns" and column in forbidden:
            return sqlite3.SQLITE_DENY
        if action in {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    repo.connection.set_authorizer(authorize)
    before = repo.connection.total_changes
    payload = strategy_board_payload(
        repo,
        snapshot_evidence=lambda _snapshot_id: {
            "status": "UNAVAILABLE",
            "reason": "provenance_absent",
            "value": None,
        },
    )
    assert payload["rows"][0]["evidence"]["oos_interval"]["status"] == "VALID"
    assert repo.connection.total_changes == before
    assert {column for table, column in reads if table == "holdout_returns"} == {
        "id",
        "holdout_evaluation_id",
        "strategy_id",
        "holdout_start",
        "holdout_end",
        "n_bars",
    }
    assert {column for table, column in reads if table == "holdout_evaluations"} == {
        "id",
        "strategy_id",
        "snapshot_id",
        "period_start",
        "period_end",
        "committed_at",
        "holdout_start",
        "holdout_end",
    }


def test_default_projection_does_not_read_any_opt_in_evidence_columns(
    repo: SqliteStrategyRepository,
) -> None:
    strategy = repo.add("alpha")
    holdout_id = _holdout(repo, strategy.id)
    repo.record_run(
        "gate",
        "alpha",
        strategy_id=strategy.id,
        provenance={
            "snapshot_id": "internal-only",
            "timeframe": "1d",
            "period_start": "2025-01-01",
            "period_end": "2025-12-31",
        },
        metrics={"n_obs_oos": 63},
        series_holdout_id=holdout_id,
    )
    evidence_run_columns = {
        "metric_schema_version",
        "timeframe",
        "period_start",
        "period_end",
        "snapshot_id",
        "series_holdout_id",
    }

    def authorize(action: int, table: str, column: str, _db: str, _trigger: str) -> int:
        if action == sqlite3.SQLITE_READ and (
            table == "holdout_returns"
            or table == "holdout_evaluations"
            or (table == "runs" and column in evidence_run_columns)
        ):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    repo.connection.set_authorizer(authorize)

    payload = strategy_board_payload(repo)

    assert payload["rows"][0]["latest_gate"]["n_obs_oos"] == 63
    assert "evidence_schema_version" not in payload
    assert "evidence" not in payload["rows"][0]


@pytest.mark.parametrize(
    ("start", "end", "valid"),
    [
        ("2024-10-01", "2024-12-31", False),
        ("2026-01-01", "2026-03-31", False),
        ("2024-12-31", "2025-10-01", False),
        ("2025-10-01", "2026-01-01", False),
        ("2025-01-01", "2025-12-31", True),
        ("2025-01-01", "2025-01-01", True),
        ("2025-12-31", "2025-12-31", True),
        ("2025-10-01", "2025-12-31", True),
        ("2025-12-31", "2025-01-01", False),
        ("2025-02-30", "2025-12-31", False),
        ("20250101", "2025-12-31", False),
        ("", "2025-12-31", False),
        (b"bad", "2025-12-31", False),
    ],
)
@pytest.mark.parametrize("source", ["both", "returns", "evaluation"])
def test_matching_oos_interval_requires_containment(
    repo: SqliteStrategyRepository, start: object, end: object, valid: bool, source: str,
) -> None:
    strategy = repo.add("alpha")
    pointer = _holdout(repo, strategy.id)
    repo.record_run(
        "gate", "alpha", strategy_id=strategy.id,
        provenance={"snapshot_id": "snapshot-exact", "timeframe": "1d",
                    "period_start": "2025-01-01", "period_end": "2025-12-31"},
        metrics={"n_obs_oos": 63}, series_holdout_id=pointer,
    )
    def interval() -> dict[str, object]:
        return strategy_board_payload(repo, snapshot_evidence=lambda _: {})[
            "rows"][0]["evidence"]["oos_interval"]

    assert interval()["status"] == "VALID"
    if valid and source != "both":
        return  # Valid controls above; changed single-source intervals must disagree.
    with repo.connection:
        if source in {"both", "returns"}:
            repo.connection.execute(
                "UPDATE holdout_returns SET holdout_start=?,holdout_end=? WHERE id=?",
                (start, end, pointer),
            )
        if source in {"both", "evaluation"}:
            repo.connection.execute(
                "UPDATE holdout_evaluations SET holdout_start=?,holdout_end=? "
                "WHERE id=(SELECT holdout_evaluation_id FROM holdout_returns WHERE id=?)",
                (start, end, pointer),
            )
    result = interval()
    if valid:
        assert result == {"status": "VALID", "reason": None, "value": {
            "holdout_start": start, "holdout_end": end, "n_bars": 63}}
    else:
        assert result == {"status": "INVALID", "reason": "malformed_fields", "value": None}
