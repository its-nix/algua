"""Guard: the signed ``--actor human`` gate-override path is gone (spec 2026-11-13).

The go-live signature is the only signed approval left. Every flag that used to relax a gate for an
authenticated human is REMOVED (an unknown option, exit 2 -- never silently ignored), and a run
labelled ``--actor human`` hits exactly the preflight an agent hits.
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from algua.backtest._sample import SyntheticProvider
from algua.cli.main import app
from algua.contracts.lifecycle import Actor, Stage
from algua.contracts.types import ExecutionContract
from algua.registry import promotion
from algua.registry.db import connect, migrate
from algua.registry.store import SqliteStrategyRepository

runner = CliRunner()

_START = datetime(2024, 1, 1, tzinfo=UTC)
_END = datetime(2024, 6, 1, tzinfo=UTC)

_PROMOTE = ["research", "promote", "s", "--universe", "u",
            "--start", "2020-01-01", "--end", "2021-01-01"]


@pytest.fixture(autouse=True)
def _tmp(monkeypatch, tmp_path):
    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "r.db"))
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path))


def _assert_unknown_option(result) -> None:
    assert result.exit_code == 2, result.output
    assert "No such option" in result.output


# --- research promote ----------------------------------------------------------------------------

@pytest.mark.parametrize("flag", [
    ["--actor-signature", "x.sig"],
    ["--n-combos", "3"],
    ["--allow-holdout-reuse"],
    ["--allow-non-pit"],
    ["--assume-terminal-last-close"],
    ["--new-family", "fam"],
])
def test_research_promote_refuses_removed_flag(flag):
    _assert_unknown_option(runner.invoke(app, [*_PROMOTE, *flag]))


@pytest.mark.parametrize(("key", "value"), [
    ("n_combos", 3),
    ("allow_holdout_reuse", True),
    ("allow_non_pit", True),
    ("assume_terminal_last_close", True),
    ("new_family", "fam"),
    ("actor_signature", "x.sig"),
])
def test_batch_promote_task_refuses_removed_key(key, value):
    from algua.cli.research_batch_cmd import _validate_tasks

    with pytest.raises(ValueError, match="unsupported keys"):
        _validate_tasks([{"action": "promote", "name": "s", key: value}])


def test_human_label_cli_promote_hits_agent_breadth_refusal():
    """`--actor human` with no recorded sweep breadth is refused exactly like an agent: no
    challenge is printed and no holdout is touched."""
    reg = runner.invoke(app, ["backtest", "run", "cross_sectional_momentum", "--demo",
                              "--start", "2022-01-01", "--end", "2023-12-31", "--register"])
    assert reg.exit_code == 0, reg.output
    from algua.registry.db import registry_conn
    with registry_conn() as conn:  # pre-assign a family so breadth is the refusal under test
        repo = SqliteStrategyRepository(conn)
        fam_id = repo.create_family("csm_family", actor="agent")
        repo.assign_strategy_to_family(
            "cross_sectional_momentum", fam_id, "agent", verdict="NOVEL", similarity_score=0.0,
            clustering_version="v0", clustering_config_json="{}", axis_json="{}")
    errors = {}
    for actor in ("agent", "human"):
        r = runner.invoke(app, ["research", "promote", "cross_sectional_momentum", "--demo",
                                "--start", "2022-01-01", "--end", "2023-12-31",
                                "--actor", actor])
        assert r.exit_code == 1, r.output
        payload = json.loads(r.stdout)
        assert payload["ok"] is False
        errors[actor] = payload["error"]
    assert "search breadth" in errors["human"]
    assert errors["human"] == errors["agent"]


# --- preflight: a human label is refused wherever an agent is -----------------------------------

def _repo(tmp_path):
    conn = connect(tmp_path / "p.db")
    migrate(conn)
    return SqliteStrategyRepository(conn)


def _backtested_in_family(repo, name="alpha"):
    rec = repo.add(name)
    repo.apply_transition(rec, Stage.BACKTESTED, Actor.AGENT, "bt")
    fam_id = repo.create_family(f"{name}_family", actor="agent")
    repo.assign_strategy_to_family(
        name, fam_id, "agent", verdict="NOVEL", similarity_score=0.0,
        clustering_version="v0", clustering_config_json="{}", axis_json="{}")


def _stub_strategy(monkeypatch, *, fees=None, feature_lookback=0, universe=("AAPL",)):
    execution = (ExecutionContract(rebalance_frequency="1d") if fees is None
                 else ExecutionContract(rebalance_frequency="1d", fees=fees, slippage=0.0))
    stub = SimpleNamespace(
        execution=execution,
        config=SimpleNamespace(feature_lookback=feature_lookback, universe=list(universe)))
    monkeypatch.setattr(promotion, "load_strategy", lambda _name: stub)
    monkeypatch.setattr(promotion, "verify_signal_panel_parity", lambda *a, **k: None)


def _preflight(repo, actor, provider=None, **kw):
    return promotion.promotion_preflight(
        repo, "alpha", actor=actor, provider=provider or SyntheticProvider(seed=0),
        start=_START, end=_END, **kw)


class _NonReproducibleProvider(SyntheticProvider):
    reproducible = False


def _refusal(fn):
    with pytest.raises(ValueError) as ei:
        fn()
    return str(ei.value)


@pytest.mark.parametrize("case", ["breadth", "reproducible", "costs", "lookback", "universe"])
def test_human_actor_gets_agent_preflight(tmp_path, monkeypatch, case):
    messages = {}
    for actor in (Actor.AGENT, Actor.HUMAN):
        repo = _repo(tmp_path / actor.value)
        _backtested_in_family(repo)
        if case != "breadth":
            repo.record_search_trial("alpha", 4, "{}")
        kw: dict = {}
        provider = None
        if case == "reproducible":
            provider = _NonReproducibleProvider(seed=0)
        elif case == "costs":
            _stub_strategy(monkeypatch, fees=0.0)
        elif case == "lookback":
            _stub_strategy(monkeypatch, feature_lookback=None)
        elif case == "universe":
            _stub_strategy(monkeypatch, universe=("AAPL", "NVDA"))
            kw = {"universe_name": "u", "universe_by_date": {date(2020, 1, 1): ["AAPL"]}}
        messages[actor] = _refusal(lambda: _preflight(repo, actor, provider, **kw))  # noqa: B023
        # Refused before the holdout: no gate row, no holdout burn.
        conn = repo._conn
        assert conn.execute("SELECT COUNT(*) c FROM gate_evaluations").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) c FROM holdout_evaluations").fetchone()["c"] == 0
    assert messages[Actor.HUMAN] == messages[Actor.AGENT]


def test_human_label_cannot_found_a_family(tmp_path):
    """A NOVEL verdict founds a family only through the agent's deferred, rate-capped mint. A
    human-labelled run is refused before the holdout instead of minting a fresh 0-prior family."""
    repo = _repo(tmp_path)
    rec = repo.add("alpha")
    repo.apply_transition(rec, Stage.BACKTESTED, Actor.AGENT, "bt")
    repo.record_search_trial("alpha", 4, "{}")
    with pytest.raises(ValueError, match="NOVEL"):
        _preflight(repo, Actor.HUMAN)
    assert repo._conn.execute("SELECT COUNT(*) c FROM families").fetchone()["c"] == 0
    assert repo.strategy_family("alpha") is None
    # The agent on the same state gets the deferred spec (no family created in preflight).
    ctx = _preflight(repo, Actor.AGENT)
    assert ctx.pending_novel_family is not None
    assert repo._conn.execute("SELECT COUNT(*) c FROM families").fetchone()["c"] == 0
