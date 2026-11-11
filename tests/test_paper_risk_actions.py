"""Unsigned paper account operations use synthetic venue truth, never trading credentials."""

import json
import sqlite3

import pytest
from typer.testing import CliRunner

from algua.cli import risk_cmd
from algua.cli.main import app
from algua.registry.db import connect, migrate
from algua.registry.drawdown_auth import paper_change, signed_change
from algua.registry.drawdown_store import account_state, write_state
from algua.risk.layered import DrawdownPolicy
from tests.test_drawdown_controller import Venue


@pytest.fixture
def world(tmp_path, monkeypatch):
    conn = connect(tmp_path / "risk.db")
    migrate(conn)
    venue = Venue()
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps(DrawdownPolicy("1000").to_dict()))
    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "risk.db"))
    monkeypatch.setattr(risk_cmd, "_broker", lambda lane: venue)
    paper_change(conn, venue, purpose="configure", policy=DrawdownPolicy("1000"))
    yield conn, venue, policy
    conn.close()


def invoke(*args):
    result = CliRunner().invoke(app, ["risk", *args])
    return result.exit_code, json.loads(result.stdout)


def halt(conn):
    prior = account_state(conn, "paper")
    with conn:
        return write_state(conn, prior, prior | {"severity": 2, "last_nav": "800",
                                                "drawdown": ".2"}, "observed")


def test_paper_configure_preserves_failed_episode_and_live_state(world):
    conn, venue, policy = world
    prior = halt(conn)
    # An unsigned live operation only issues its signed challenge; PAPER cannot consume it.
    live_challenge = signed_change(conn, venue, "live", purpose="configure",
                                   policy=DrawdownPolicy("1000"), signature=None)
    code, result = invoke("configure", "paper", "--policy", str(policy))
    assert code == 0 and result["action"] == "configure"
    state = result["state"]
    for field in ("severity", "baseline_at", "baseline_nav", "baseline_equity", "peak_nav",
                  "last_nav", "drawdown"):
        assert state[field] == prior[field]
    assert state["policy_id"] != prior["policy_id"]
    assert state["last_paper_action"]["prior_episode"]["severity"] == 2
    assert account_state(conn, "live") is None
    assert conn.execute("SELECT consumed_at FROM drawdown_challenges WHERE nonce=?",
                        (live_challenge["nonce"],)).fetchone()[0] is None
    assert conn.execute("SELECT count(*) FROM approvals").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM strategy_allocations").fetchone()[0] == 0


def test_paper_restore_requires_reason_and_records_actual_episode(world):
    conn, venue, _ = world
    prior = halt(conn)
    code, result = invoke("restore", "paper", "--reason", "   ")
    assert code == 1 and "reason" in result["error"]
    assert account_state(conn, "paper") == prior
    venue.equity = venue.last_equity = 800
    code, result = invoke("restore", "paper", "--reason", "settled synthetic failed trial")
    assert code == 0 and result["action"] == "restore"
    state = result["state"]
    assert state["severity"] == 0 and state["baseline_equity"] == "800"
    assert state["policy_id"] == prior["policy_id"]
    assert "last_human_action" not in state and "principal" not in result
    action = state["last_paper_action"]
    assert action["actor"] == "agent" and action["purpose"] == "restore"
    assert action["reason"] == "settled synthetic failed trial"
    assert action["prior_episode"]["severity"] == 2
    assert action["prior_episode"]["last_nav"] == "800"
    event = conn.execute("SELECT state_json FROM drawdown_events WHERE kind='restore'").fetchone()
    assert json.loads(event[0]) == state
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("UPDATE drawdown_events SET kind='configured' WHERE kind='restore'")
    conn.rollback()
    assert conn.execute(
        "SELECT count(*) FROM drawdown_events WHERE kind='observed'"
    ).fetchone()[0] == 1


@pytest.mark.parametrize("purpose", ["configure", "restore"])
@pytest.mark.parametrize("fault", ["position", "order", "account", "host", "quarantine"])
def test_paper_mutations_refuse_unsettled_or_wrong_account(world, purpose, fault):
    conn, venue, policy = world
    prior = account_state(conn, "paper")
    if fault == "position":
        venue.positions = {"AAPL": 1}
    elif fault == "order":
        venue.orders["pending"] = {"status": "new"}
    elif fault == "account":
        venue.account_id = "other-paper-account"
    elif fault == "host":
        venue.base_url = "https://api.alpaca.markets"
    else:
        conn.execute("INSERT INTO paper_venue_activity_quarantine(activity_id,error,raw) "
                     "VALUES ('synthetic-poison','malformed','{}')")
        conn.commit()
    args = [purpose, "paper"] + (["--policy", str(policy)] if purpose == "configure"
                                  else ["--reason", "synthetic settled recovery"])
    code, result = invoke(*args)
    assert code == 1 and not result["ok"]
    assert account_state(conn, "paper") == prior
    assert conn.execute("SELECT count(*) FROM drawdown_policies").fetchone()[0] == 1
    assert not venue.sent


def test_paper_restore_preserves_reconciliation_guard(world):
    from tests.test_drawdown_controller import held

    conn, venue, _ = world
    prior = account_state(conn, "paper")
    held(conn, venue)
    venue.positions = {}  # Broker flatness alone cannot erase attributed ledger holdings.
    code, result = invoke("restore", "paper", "--reason", "synthetic recovery")
    assert code == 1 and "reconciliation" in result["error"]
    assert account_state(conn, "paper") == prior


def test_paper_change_keeps_cas_guard(world, monkeypatch):
    from algua.registry import drawdown_auth

    conn, venue, _ = world
    original = drawdown_auth.fingerprints
    external = []

    def raced(activities):
        external.append(halt(conn))
        return original(activities)

    monkeypatch.setattr(drawdown_auth, "fingerprints", raced)
    with pytest.raises(ValueError, match="state changed under lock"):
        paper_change(conn, venue, purpose="restore", policy=None, reason="synthetic recovery")
    assert account_state(conn, "paper") == external[0]
    assert conn.execute(
        "SELECT count(*) FROM drawdown_events WHERE kind='restore'"
    ).fetchone()[0] == 0


@pytest.mark.parametrize("purpose", ["configure", "restore"])
def test_paper_signature_is_clearly_rejected_without_challenge(world, purpose):
    conn, _, policy = world
    args = [purpose, "paper", "--signature", "unused.sig"]
    args += ["--policy", str(policy)] if purpose == "configure" else ["--reason", "synthetic"]
    code, result = invoke(*args)
    assert code == 1 and "unsigned; omit --signature" in result["error"]
    assert conn.execute("SELECT count(*) FROM drawdown_challenges").fetchone()[0] == 0



@pytest.mark.parametrize("base_url", ["https://paper-api.alpaca.markets:443",
                                     "https://paper-api.alpaca.markets/v2",
                                     "https://paper-api.alpaca.markets.evil",
                                     "http://paper-api.alpaca.markets"])
def test_paper_actions_require_exact_host(world, base_url):
    conn, venue, _ = world
    venue.base_url = base_url
    with pytest.raises(ValueError, match="exact Alpaca paper host"):
        paper_change(conn, venue, purpose="restore", policy=None, reason="synthetic")


def test_unresolved_reduction_acceptance_blocks_paper_restore(world):
    conn, venue, _ = world
    prior = account_state(conn, "paper")
    conn.execute(
        "INSERT INTO drawdown_reductions "
        "(lane,account_id,policy_id,strategy,symbol,qty,limit_price,client_order_id,"
        "phase,created_at) "
        "VALUES ('paper',?,?,'synthetic','CSL','1','100','synthetic-uncertain','submitting',?)",
        (venue.account_id, prior["policy_id"], venue.clock()),
    )
    conn.commit()
    with pytest.raises(ValueError, match="unresolved reduction acceptance"):
        paper_change(conn, venue, purpose="restore", policy=None, reason="synthetic")
    assert account_state(conn, "paper") == prior


def test_initial_flat_baseline_records_historical_external_fills_without_waiver(tmp_path):
    conn = connect(tmp_path / "initial-risk.db")
    migrate(conn)
    venue = Venue()
    # Historical cleanup fills remain observations without fabricated strategy attribution.
    venue.activities = [{"id": "synthetic-external-sell", "activity_type": "FILL",
                         "order_id": "synthetic-owner-cleanup", "side": "sell", "qty": "1",
                         "price": "100", "symbol": "CSL", "transaction_time": venue.clock()}]
    try:
        result = paper_change(conn, venue, purpose="configure", policy=DrawdownPolicy("5"))
        assert result["state"]["severity"] == 0
        fill = conn.execute("SELECT strategy,qty FROM paper_venue_fills").fetchone()
        assert fill["strategy"] is None and fill["qty"] == -1
        assert conn.execute(
            "SELECT count(*) FROM paper_venue_activity_quarantine"
        ).fetchone()[0] == 0
    finally:
        conn.close()
