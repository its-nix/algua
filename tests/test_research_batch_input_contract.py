"""Batch JSON must preserve CLI types before any numerical task or registry write."""
from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from algua.cli.main import app

runner = CliRunner()


def _invoke(tmp_path, tasks):
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps(tasks), encoding="utf-8")
    return runner.invoke(app, ["research", "run-all", "--tasks", str(path)])


@pytest.mark.parametrize("params", [
    {"demo": "false"},
    {"demo": True, "register": "false"},
])
def test_string_false_cannot_select_demo_or_register(tmp_path, monkeypatch, params):
    database = tmp_path / "registry.db"
    monkeypatch.setenv("ALGUA_DB_PATH", str(database))
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path / "data"))
    result = _invoke(tmp_path, [
        {"action": "backtest", "name": "cross_sectional_momentum", **params},
    ])
    assert result.exit_code == 1, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "tasks_total" not in payload  # Rejected before entering the task loop.
    assert not database.exists()


@pytest.mark.parametrize(("action", "key", "value"), [
    ("backtest", "demo", "false"),
    ("backtest", "register", 1),
    ("backtest", "assume_terminal_last_close", "false"),
    ("backtest", "start", None),
    ("backtest", "snapshot", False),
    ("backtest", "universe", ["proxy"]),
    ("backtest", "emit_series", True),
    ("sweep", "windows", True),
    ("sweep", "windows", 2.5),
    ("sweep", "top", "2"),
    ("sweep", "holdout_frac", "0.2"),
    ("sweep", "holdout_frac", False),
    ("sweep", "holdout_frac", float("inf")),
    ("sweep", "param", "lookback=20,40"),
    ("sweep", "param", ["lookback=20,40", 5]),
    ("sweep", "rank_by", None),
    ("promote", "n_combos", True),
    ("promote", "min_holdout_sharpe", None),
    ("promote", "min_holdout_sharpe", float("nan")),
    ("promote", "min_holdout_return", 10 ** 400),
    ("promote", "allow_non_pit", "false"),
    ("promote", "allow_holdout_reuse", 0),
    ("promote", "actor", ["agent"]),
    ("promote", "new_family", {}),
])
def test_malformed_later_task_prevents_all_dispatch(tmp_path, monkeypatch, action, key, value):
    import algua.cli.research_batch_cmd as batch

    called = []

    def task(name, **kwargs):
        called.append((name, kwargs))
        return {}

    monkeypatch.setattr(batch, "_DISPATCH", dict.fromkeys(batch._DISPATCH, task))
    result = _invoke(tmp_path, [
        {"action": "backtest", "name": "first", "demo": True},
        {"action": action, "name": "second", key: value},
    ])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False and "tasks_total" not in payload
    assert called == []


@pytest.mark.parametrize("fields", [
    '"action":"backtest","action":"sweep","name":"x"',
    '"action":"backtest","name":"x","name":"y"',
    '"action":"backtest","name":"x","demo":false,"demo":true',
    '"action":"backtest","name":"x","register":false,"register":true',
    '"action":"sweep","name":"x","param":[],"param":["lookback=20,40"]',
])
def test_ambiguous_duplicate_fields_prevent_all_dispatch(tmp_path, monkeypatch, fields):
    import algua.cli.research_batch_cmd as batch

    called = []

    def task(name, **kwargs):
        called.append((name, kwargs))
        return {}

    monkeypatch.setattr(batch, "_DISPATCH", dict.fromkeys(batch._DISPATCH, task))
    path = tmp_path / "tasks.json"
    path.write_text('[{"action":"backtest","name":"first","demo":true},{'
                    + fields + '}]', encoding="utf-8")
    result = runner.invoke(app, ["research", "run-all", "--tasks", str(path)])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False and "tasks_total" not in payload
    assert called == []


@pytest.mark.parametrize("task", [
    {"action": "backtest", "name": "first", "start": "2025-01-01", "end": "2026-01-01",
     "demo": False, "snapshot": "bars", "universe": None, "fundamentals_snapshot": None,
     "news_snapshot": None, "delistings": None, "assume_terminal_last_close": False,
     "register": False, "emit_series": None},
    {"action": "sweep", "name": "second", "start": "2025-01-01", "end": "2026-01-01",
     "demo": True, "snapshot": None, "universe": None, "fundamentals_snapshot": "funds",
     "news_snapshot": "news", "delistings": "delisted", "assume_terminal_last_close": False,
     "windows": 2, "top": 3, "holdout_frac": 0.2, "param": ["lookback=20,40"],
     "rank_by": "mean_sharpe"},
    {"action": "promote", "name": "third", "start": "2025-01-01", "end": "2026-01-01",
     "demo": False, "snapshot": "bars", "universe": "universe", "fundamentals_snapshot": None,
     "news_snapshot": None, "delistings": None,
     "windows": 4, "holdout_frac": 0.2, "min_holdout_sharpe": 1, "min_holdout_return": 0,
     "actor": "agent"},
    {"action": "sweep", "name": "no-params", "param": None},
    {"action": "sweep", "name": "empty-params", "param": []},
    {"action": "promote", "name": "count", "windows": 1},
])
def test_valid_json_parameters_are_forwarded_without_coercion(tmp_path, monkeypatch, task):
    import algua.cli.research_batch_cmd as batch

    called = []

    def dispatch(name, **kwargs):
        called.append((name, kwargs))
        return {}

    monkeypatch.setattr(batch, "_DISPATCH", dict.fromkeys(batch._DISPATCH, dispatch))
    result = _invoke(tmp_path, [task])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True and payload["ok_count"] == 1
    expected = {k: v for k, v in task.items() if k not in ("action", "name")}
    assert called == [(task["name"], expected | {"reload": True})]
    assert {k: type(v) for k, v in called[0][1].items() if k != "reload"} == {
        k: type(v) for k, v in expected.items()}


@pytest.mark.parametrize("action", [[], {}, None, True, 1])
def test_non_string_action_has_structural_error(tmp_path, action):
    result = _invoke(tmp_path, [{"action": action, "name": "x"}])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False and "unknown action" in payload["error"]
