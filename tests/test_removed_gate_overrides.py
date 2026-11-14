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


def _backtested(repo, name="alpha"):
    rec = repo.add(name)
    repo.apply_transition(rec, Stage.BACKTESTED, Actor.AGENT, "bt")


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
        _backtested(repo)
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


def test_human_and_agent_preflight_agree_with_no_families(tmp_path):
    """Strategy-family governance is gone (lean trim step 7): on a registry with no families a
    human-labelled preflight resolves exactly the breadth an agent's does, and neither writes a
    family row."""
    ctxs = {}
    for actor in (Actor.AGENT, Actor.HUMAN):
        repo = _repo(tmp_path / actor.value)
        _backtested(repo)
        repo.record_search_trial("alpha", 4, "{}")
        ctxs[actor] = _preflight(repo, actor)
        assert repo._conn.execute("SELECT COUNT(*) c FROM families").fetchone()["c"] == 0
    assert ctxs[Actor.HUMAN] == ctxs[Actor.AGENT]


# --- paper promote and the rest of the signed path ----------------------------------------------

def test_paper_promote_refuses_actor_signature():
    _assert_unknown_option(runner.invoke(
        app, ["paper", "promote", "s", "--actor", "human", "--actor-signature", "x.sig"]))


def test_qualify_experimental_refuses_actor_signature():
    _assert_unknown_option(runner.invoke(
        app, ["paper", "qualify-experimental", "s", "--actor-signature", "x.sig"]))


# Each threshold moved one step in its LOOSE direction from today's default.
_LOOSENED = [
    ("--degradation-factor", "0.4"),
    ("--sharpe-floor", "0.2"),
    ("--min-observations", "62"),
    ("--min-coverage", "0.8"),
    ("--min-vol", "0.01"),
    ("--max-drawdown", "0.3"),
    ("--max-staleness", "6"),
    ("--forward-sharpe-confidence", "0.9"),
]


def _paper_tenant(name="fwd"):
    from algua.registry.db import registry_conn
    from tests._deployment_helpers import force_legacy_strategy

    with registry_conn() as conn:
        rec = SqliteStrategyRepository(conn).add(name)
        force_legacy_strategy(conn, rec.id)


@pytest.mark.parametrize(("flag", "value"), _LOOSENED)
def test_paper_promote_human_cannot_loosen(flag, value):
    """A loosened threshold is refused for `--actor human` exactly as for an agent, before the
    broker is built and before any evaluation row."""
    _paper_tenant()
    errors = {}
    for actor in ("agent", "human"):
        r = runner.invoke(app, ["paper", "promote", "fwd", "--actor", actor, flag, value])
        assert r.exit_code == 1, r.output
        payload = json.loads(r.stdout)
        assert payload["ok"] is False
        assert "relax" in payload["error"]
        errors[actor] = payload["error"]
    assert errors["human"] == errors["agent"]
    from algua.registry.db import registry_conn
    with registry_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM forward_gate_evaluations").fetchone()[0] == 0


@pytest.mark.parametrize("actor", [Actor.AGENT, Actor.HUMAN])
def test_forward_guard_allows_tightening_for_every_actor(actor):
    from algua.registry.forward_promotion import guard_forward_relaxations
    from algua.research.forward_gates import ForwardGateCriteria

    guard_forward_relaxations(
        actor, ForwardGateCriteria(sharpe_floor=0.5, max_staleness_sessions=3))
    with pytest.raises(ValueError, match="sharpe_floor"):
        guard_forward_relaxations(actor, ForwardGateCriteria(sharpe_floor=0.1))


_PUB = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl t"


@pytest.mark.parametrize("namespace", ["human-actor", "both"])
def test_enroll_approver_rejects_human_actor_namespace(tmp_path, monkeypatch, namespace):
    anchor = tmp_path / "allowed_signers"
    monkeypatch.setattr("algua.cli.registry_cmd.ALLOWED_SIGNERS_PATH", anchor)
    r = runner.invoke(app, ["registry", "enroll-approver", "--name", "alice", "--pubkey", _PUB,
                            "--namespace", namespace])
    assert r.exit_code != 0, r.output
    assert not anchor.exists() or "human-actor" not in anchor.read_text()


def test_enroll_approver_go_live_still_accepted(tmp_path, monkeypatch):
    anchor = tmp_path / "allowed_signers"
    monkeypatch.setattr("algua.cli.registry_cmd.ALLOWED_SIGNERS_PATH", anchor)
    r = runner.invoke(app, ["registry", "enroll-approver", "--name", "alice", "--pubkey", _PUB,
                            "--namespace", "go-live"])
    assert r.exit_code == 0, r.output
    assert 'namespaces="algua-go-live"' in anchor.read_text()


@pytest.mark.parametrize(("source", "target", "gate"), [
    (Stage.BACKTESTED, Stage.CANDIDATE, "research promote"),
    (Stage.PAPER, Stage.FORWARD_TESTED, "paper promote"),
])
def test_raw_service_transition_needs_the_gate_token_for_a_human(tmp_path, source, target, gate):
    """transitions.transition_strategy has no human exemption on the two gated edges: a human
    label without a gate token is refused exactly like an agent."""
    from algua.contracts.lifecycle import TransitionError
    from algua.registry.transitions import transition_strategy
    from tests._deployment_helpers import force_legacy_strategy

    repo = _repo(tmp_path)
    rec = repo.add("cross_sectional_momentum")
    if source is Stage.BACKTESTED:
        repo.apply_transition(rec, Stage.BACKTESTED, Actor.AGENT, "bt")
    else:
        force_legacy_strategy(repo._conn, rec.id)
    with pytest.raises(TransitionError, match=gate):
        transition_strategy(repo, "cross_sectional_momentum", target, Actor.HUMAN, "manual")
    assert repo.get("cross_sectional_momentum").stage is source


def test_human_actor_module_is_gone():
    import importlib.util

    assert importlib.util.find_spec("algua.registry.human_actor") is None
