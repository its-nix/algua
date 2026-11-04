"""Public command-tree integration over actual retained fixture experiments."""
from __future__ import annotations

import json
import shutil

import pytest

from algua.cli.main import main
from algua.registry.db import connect
from algua.registry.store import SqliteStrategyRepository
from tests.test_cli_research_memory import cli_memory as cli_memory


def _invoke(arguments, capsys):
    with pytest.raises(SystemExit) as stopped:
        main(["research", "memory", *arguments])
    return stopped.value.code, json.loads(capsys.readouterr().out)


def test_public_memory_commands_preserve_real_fixture_evidence_after_cleanup(cli_memory, capsys):
    authority, cycle, worker, source, _ = cli_memory
    before = list(authority.iterdump())
    run = cycle.cycle_id
    code, seeded = _invoke(["seed", "--run", run, "--worker-root", str(worker)], capsys)
    assert code == 0 and seeded["ok"] is True

    conn = connect(source)
    with conn:
        SqliteStrategyRepository(conn).record_run(
            "backtest", "SYNTHETIC_FIXTURE public-command-negative",
            config={"params": {"lookback": 3}}, metrics={"total_return_is": -0.25})
    conn.close()
    code, captured = _invoke([
        "capture", "--run", run, "--worker-root", str(worker),
        "--worker-exit", "0", "--source-commit", "b" * 40,
    ], capsys)
    assert code == 0 and captured["receipt"]["reference"].startswith("mlflow:")
    code, checked = _invoke([
        "cleanup-check", "--run", run, "--worker-root", str(worker),
    ], capsys)
    assert code == 0 and checked["cleanup_allowed"] is True
    shutil.rmtree(worker)
    code, archived = _invoke(["show", "--run", run], capsys)
    assert code == 0 and archived["authority"] == "none"
    assert archived["evaluations"][0]["metrics"]["total_return_is"] == -0.25
    assert list(authority.iterdump()) == before


@pytest.mark.parametrize("arguments", [
    ["seed", "--worker-root", "."],
    ["capture", "--run", "fixture", "--worker-root", ".", "--worker-exit", "not-an-int",
     "--source-commit", "b" * 40],
])
def test_public_memory_parse_errors_are_json(arguments, capsys):
    code, payload = _invoke(arguments, capsys)
    assert code == 1 and payload["ok"] is False
    assert payload["code"] == "usage_error"
