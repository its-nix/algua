"""Ambiguous source JSON must retain the worker instead of archiving a salvaged value."""
from __future__ import annotations

import json

import pytest

from algua.registry.db import connect
from algua.registry.store import SqliteStrategyRepository
from tests.test_research_memory import memory_case as memory_case


@pytest.mark.parametrize("raw", [
    '{"params":{"n":1},"params":{"n":2}}',
    '{"params":{"opaque":{"sample":1,"sample":2}}}',
])
def test_duplicate_source_input_keys_refuse_capture_before_cleanup(memory_case, raw):
    _, cycle, worker, source, _, memory = memory_case
    conn = connect(source)
    with conn:
        run_id = SqliteStrategyRepository(conn).record_run(
            "backtest", "SYNTHETIC_FIXTURE ambiguous input")
        conn.execute("UPDATE runs SET config_json=? WHERE id=?", (raw, run_id))
    conn.close()

    with pytest.raises(ValueError):
        memory.capture(worker, worker_exit=0, source_commit="b" * 40)

    assert not memory.cleanup_allowed(worker)
    assert source.exists()
    assert "receipt" not in json.loads(cycle.path.read_text())["research_memory"]
