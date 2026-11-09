"""Paper policy mutations share the installed operator lock; live behavior stays unchanged."""
import json
import os

import pytest
from typer.testing import CliRunner

from algua.cli.risk_cmd import risk_app
from algua.operator import paper_account_lock as locks
from algua.operator.schedule import operator_run_lock
from algua.risk.layered import DrawdownPolicy


@pytest.mark.parametrize("command", ["configure", "restore"])
def test_paper_policy_contention_refuses_before_broker(tmp_path, monkeypatch, command):
    lock = tmp_path / "operator.lock"
    monkeypatch.setattr(locks, "_operator_lock_path", lambda: lock)
    calls = []
    monkeypatch.setattr("algua.cli.risk_cmd._broker", lambda lane: calls.append(lane))
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps(DrawdownPolicy("5", permitted_symbols=("CSL",)).to_dict()))
    args = [command, "paper"] + (["--policy", str(policy)] if command == "configure" else [])
    with operator_run_lock(lock, job="fixture", host="fixture", pid=os.getpid()):
        result = CliRunner().invoke(risk_app, args)
    assert result.exit_code == 1
    assert "operator.lock is held" in json.loads(result.stdout)["error"]
    assert calls == []


def test_live_policy_lock_remains_noop(monkeypatch):
    def forbidden():
        raise AssertionError("live path must not acquire paper account lock")

    monkeypatch.setattr(locks, "_operator_lock_path", forbidden)
    with locks.paper_account_lock("live"):
        pass
