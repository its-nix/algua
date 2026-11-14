"""``backtest_returns`` persistence (#222 Task 7). The table outlived the family clustering it was
added for: run views (``series_backtest_id``) and the merge-back intake precondition read it."""
from __future__ import annotations

import json
import sqlite3

import pandas as pd
import pytest

from algua.registry.db import migrate


def _make_series(values: list[float], start: str = "2020-01-01") -> pd.Series:
    idx = pd.bdate_range(start, periods=len(values))
    return pd.Series(values, index=idx, dtype=float)


@pytest.fixture()
def store():
    """Create an in-memory SqliteStrategyRepository with migrated schema."""
    from algua.registry.store import SqliteStrategyRepository

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    migrate(conn)
    return SqliteStrategyRepository(conn)


def test_backtest_returns_table_roundtrip(store):
    """persist_backtest_returns + load_backtest_returns roundtrips correctly."""
    returns = _make_series([0.01, -0.02, 0.03, 0.0, 0.015], start="2023-06-01")
    row_id = store.persist_backtest_returns(
        strategy_name="test_strategy",
        period_start="2023-06-01",
        period_end="2023-06-08",
        returns=returns,
    )
    assert isinstance(row_id, int)

    loaded = store.load_backtest_returns("test_strategy")
    assert loaded is not None
    assert len(loaded) == len(returns)
    # Roundtrip does not preserve freq (JSON has no concept of freq), so check values + dates
    pd.testing.assert_index_equal(loaded.index, returns.index, check_names=False)
    assert list(loaded.values) == pytest.approx(list(returns.values))


def test_load_backtest_returns_nonexistent(store):
    """load_backtest_returns for unknown strategy -> None."""
    assert store.load_backtest_returns("nonexistent") is None


def test_load_backtest_returns_most_recent(store):
    """Multiple persisted series -> loads the most recent one."""
    old = _make_series([0.01, 0.02], start="2023-01-01")
    store.persist_backtest_returns("strat", "2023-01-01", "2023-01-03", old)
    new = _make_series([0.05, 0.06, 0.07], start="2023-06-01")
    store.persist_backtest_returns("strat", "2023-06-01", "2023-06-04", new)
    loaded = store.load_backtest_returns("strat")
    assert loaded is not None
    assert len(loaded) == 3


def test_load_backtest_returns_same_timestamp_id_tiebreak(store):
    """Two rows with identical created_at -> the higher id (later insert) wins (#257).

    created_at alone is not a deterministic ordering key (microsecond timestamps can
    collide for back-to-back runs); the id DESC tiebreak makes 'latest' well-defined.
    """
    ts = "2023-06-01T00:00:00+00:00"
    first = json.dumps([["2023-06-01", 0.01], ["2023-06-02", 0.02]])
    second = json.dumps([["2023-06-01", 0.05], ["2023-06-02", 0.06], ["2023-06-03", 0.07]])
    # Insert both rows with the SAME created_at so only the id can break the tie.
    store._conn.execute(
        "INSERT INTO backtest_returns"
        " (strategy_name, period_start, period_end, returns_json, created_at)"
        " VALUES (?,?,?,?,?)",
        ("strat", "2023-06-01", "2023-06-03", first, ts),
    )
    store._conn.execute(
        "INSERT INTO backtest_returns"
        " (strategy_name, period_start, period_end, returns_json, created_at)"
        " VALUES (?,?,?,?,?)",
        ("strat", "2023-06-01", "2023-06-04", second, ts),
    )
    store._conn.commit()
    loaded = store.load_backtest_returns("strat")
    assert loaded is not None
    # The later-inserted (higher id) row deterministically wins the tie.
    assert len(loaded) == 3
    assert list(loaded.values) == pytest.approx([0.05, 0.06, 0.07])
