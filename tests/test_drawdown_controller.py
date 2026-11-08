"""Owned synthetic venue only: no credentials, broker network or real trading."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from algua.execution.drawdown_cycle import manage_cycle
from algua.execution.drawdown_guard import cycle_active, effective_allocation, reserve
from algua.execution.live_ledger import (
    LedgerKind,
    backfill_paper_venue_broker_order_id,
    ingest_activities,
    record_paper_venue_order,
)
from algua.registry import live_gate
from algua.registry.db import connect, migrate
from algua.registry.drawdown_auth import signed_change
from algua.registry.drawdown_store import account_state
from algua.risk.layered import DrawdownPolicy
from tests.test_human_actor import _anchor, _make_key, _sign


class Venue:
    def __init__(self):
        self.equity = 1000.0
        self.last_equity = 1000.0
        self.account_id = "synthetic-paper"
        self.positions = {}
        self.activities = []
        self.sent = []
        self.orders = {}
        self.cancel_count = 0
        self.stale = False
        self.open = True
        self.cancel_settles = True
        self.fail_submit = False

    def clock(self):
        return datetime.now(UTC).isoformat()

    def account(self):
        return SimpleNamespace(
            account_id=self.account_id,
            equity=self.equity,
            cash=self.equity - sum(self.positions.values()) * 100,
            buying_power=self.equity,
            last_equity=self.last_equity,
        )

    def get_positions(self):
        return pd.Series(self.positions, dtype=float)

    def list_open_orders(self):
        return [v for v in self.orders.values() if v["status"] == "new"]

    def cancel_open_orders(self):
        self.cancel_count += 1
        if self.cancel_settles:
            for order in self.orders.values():
                order["status"] = "canceled"

    def snapshot(self, symbols):
        return SimpleNamespace(
            qtys=dict(self.positions), market_values={s: q * 100 for s, q in self.positions.items()}
        )

    def account_activities_window(self, after, until):
        return self.activities

    def account_activities(self, after=None):
        return self.activities

    def get_order_by_client_order_id(self, coid):
        return self.orders.get(coid)

    def regular_market_open(self):
        return self.open

    def reduction_quote(self, symbol, feed):
        t = datetime.now(UTC) - timedelta(seconds=120 if self.stale else 0)
        return {"t": t.isoformat(), "bp": 100, "ap": 100.1, "bs": 10, "as": 10}

    def submit_reduction(self, symbol, qty, price, coid):
        row = {
            "id": "venue-" + coid,
            "client_order_id": coid,
            "symbol": symbol,
            "side": "sell",
            "qty": qty,
            "limit_price": price,
            "type": "limit",
            "time_in_force": "day",
            "status": "new",
        }
        self.orders[coid] = row
        if self.fail_submit:
            raise TimeoutError("SYNTHETIC accepted but acknowledgment lost")
        self.sent.append(row)
        return row["id"]


@pytest.fixture
def world(tmp_path, monkeypatch):
    conn = connect(tmp_path / "risk.db")
    migrate(conn)
    venue = Venue()
    key, pub = _make_key(tmp_path)
    anchor = _anchor(tmp_path, "owner", pub, namespaces="algua-go-live")
    monkeypatch.setattr(live_gate, "ALLOWED_SIGNERS_PATH", anchor)
    calls = []
    from algua.execution import drawdown_cycle

    monkeypatch.setattr(drawdown_cycle, "emit_alert", lambda *args, **kwargs: calls.append(args))

    def signed(purpose="configure", policy=None, lane="paper"):
        cfg = (policy or DrawdownPolicy("1000")) if purpose == "configure" else None
        challenge = signed_change(conn, venue, lane, purpose=purpose, policy=cfg, signature=None)
        folder = tmp_path / ("sig-" + str(len(list(tmp_path.glob("sig-*")))))
        folder.mkdir()
        signature = _sign(key, challenge["challenge"], folder, namespace="algua-go-live")
        result = signed_change(conn, venue, lane, purpose=purpose, policy=cfg, signature=signature)
        return result, signature

    signed()
    yield conn, venue, signed, calls
    conn.close()


def held(conn, venue, qty=8.0):
    conn.execute(
        "INSERT INTO strategies(id,name,stage,created_at,updated_at) "
        "VALUES (1,'synthetic_s','paper','t','t')"
    )
    conn.execute(
        "INSERT INTO strategy_allocations(strategy_id,capital,effective_ts,actor) "
        "VALUES (1,1000,'t','human')"
    )
    conn.commit()
    record_paper_venue_order(conn, "synthetic_s", "AAPL", "buy", None, "seed", strategy_id=1)
    backfill_paper_venue_broker_order_id(conn, "seed", "seed-order")
    fill = {
        "id": "seed-fill",
        "activity_type": "FILL",
        "order_id": "seed-order",
        "side": "buy",
        "qty": str(qty),
        "price": "100",
        "symbol": "AAPL",
        "transaction_time": venue.clock(),
    }
    venue.activities.append(fill)
    ingest_activities(conn, [fill], LedgerKind.PAPER, cursor_value=venue.clock())
    venue.positions = {"AAPL": qty}


def test_normal_cycle_shared_cap_and_mid_tick_revision_guard(world):
    conn, venue, _, _ = world
    result = manage_cycle(conn, venue, "paper")
    assert result["ready"] and cycle_active(conn, venue, "paper")
    buy_a = reserve(conn, venue, "paper", None)
    buy_b = reserve(conn, venue, "paper", None)
    assert buy_a("AAPL", 700) == 700
    assert buy_b("MSFT", 700) == 300
    assert effective_allocation(conn, venue, "paper", 2000) == 1000
    manage_cycle(conn, venue, "paper", observe_only=True)
    assert not cycle_active(conn, venue, "paper")
    with pytest.raises(ValueError, match="changed or cycle expired"):
        buy_a("NVDA", 1)


def test_ten_percent_trims_existing_holdings_with_attributed_limit_orders(world):
    conn, venue, _, _ = world
    held(conn, venue)
    venue.equity = venue.last_equity = 900
    result = manage_cycle(conn, venue, "paper")
    assert not result["ready"] and result["reductions_submitted"] == 1
    assert result["state"]["severity"] == 1
    order = venue.sent[0]
    assert order["side"] == "sell" and order["type"] == "limit"
    assert float(order["qty"]) == 3 and float(order["limit_price"]) >= 99.75
    assert (
        conn.execute(
            "SELECT strategy FROM paper_venue_orders WHERE client_order_id=?",
            (order["client_order_id"],),
        ).fetchone()[0]
        == "synthetic_s"
    )


@pytest.mark.parametrize("fault", ["stale", "closed", "cancel_pending", "reconcile", "account"])
def test_unhealthy_execution_never_sends_reductions(world, fault):
    conn, venue, _, alerts = world
    held(conn, venue)
    venue.equity = venue.last_equity = 800
    if fault == "stale":
        venue.stale = True
    elif fault == "closed":
        venue.open = False
    elif fault == "cancel_pending":
        venue.cancel_settles = False
        venue.orders["resting"] = {"status": "new"}
    elif fault == "reconcile":
        venue.positions["AAPL"] = 7
    else:
        venue.account_id = "wrong-account"
    result = manage_cycle(conn, venue, "paper")
    assert not result["ready"] and not venue.sent
    assert result["state"]["severity"] == 2 and venue.cancel_count > 0
    assert alerts


def test_reduced_state_survives_price_recovery_and_legacy_resume(world):
    from algua.execution.peaks import rebase_all_peaks
    from algua.risk import global_halt

    conn, venue, _, _ = world
    venue.equity = venue.last_equity = 900
    assert manage_cycle(conn, venue, "paper")["state"]["severity"] == 1
    rebase_all_peaks(conn)
    global_halt.clear(conn)
    venue.equity = venue.last_equity = 1000
    assert manage_cycle(conn, venue, "paper")["ready"]
    assert effective_allocation(conn, venue, "paper", 1000) == 500


def test_twenty_percent_halts_flat_and_only_signature_restores(world):
    conn, venue, signed, _ = world
    venue.equity = venue.last_equity = 800
    assert manage_cycle(conn, venue, "paper")["reason"] == "drawdown_halted_flat"
    assert not cycle_active(conn, venue, "paper")
    signed("restore")
    assert manage_cycle(conn, venue, "paper")["ready"]
    assert account_state(conn, "paper")["severity"] == 0
    assert (
        conn.execute("SELECT COUNT(*) FROM drawdown_events WHERE kind='restore'").fetchone()[0] == 1
    )


def test_signature_replay_and_unsigned_config_cannot_change_policy(world):
    conn, venue, signed, _ = world
    result, signature = signed()
    with pytest.raises(ValueError, match="fresh matching"):
        signed_change(conn, venue, "paper", purpose="configure", policy=None, signature=signature)
    before = account_state(conn, "paper")
    challenge = signed_change(
        conn,
        venue,
        "paper",
        purpose="configure",
        policy=DrawdownPolicy("1000", halt_at=".3"),
        signature=None,
    )
    assert challenge["action"] == "drawdown_challenge"
    assert account_state(conn, "paper") == before


def test_daily_loss_is_independent_and_no_unknown_market_fallback(world):
    conn, venue, _, _ = world
    venue.equity = 950
    venue.last_equity = 1000
    result = manage_cycle(conn, venue, "paper")
    assert result["state"]["severity"] == 2 and result["state"]["drawdown"] == "0.05"


def test_accepted_but_unacknowledged_reduction_recovers_original_identity(world):
    conn, venue, _, _ = world
    held(conn, venue)
    venue.equity = venue.last_equity = 900
    venue.fail_submit = True
    first = manage_cycle(conn, venue, "paper")
    assert not first["ready"]
    coid = conn.execute("SELECT client_order_id FROM drawdown_reductions").fetchone()[0]
    venue.fail_submit = False
    manage_cycle(conn, venue, "paper")
    recovered = conn.execute(
        "SELECT broker_order_id FROM drawdown_reductions WHERE client_order_id=?", (coid,)
    ).fetchone()[0]
    assert recovered == "venue-" + coid
    assert len([r for r in venue.sent if r["client_order_id"] == coid]) == 0


def test_reduced_sizing_keeps_economic_nav_and_peak_comparable(world):
    from algua.execution.drawdown_guard import sizing_snapshot
    from algua.execution.live_sizing import SizingSnapshot

    conn, venue, _, _ = world
    venue.equity = venue.last_equity = 900
    assert manage_cycle(conn, venue, "paper")["ready"]
    snapshot, nav = sizing_snapshot(
        conn, venue, "paper", (SizingSnapshot(900, {"AAPL": 400}, {"AAPL": 4}), 900)
    )
    assert snapshot.equity == 450 and nav == 900
    assert snapshot.market_values == {"AAPL": 400}


def test_twenty_percent_submits_full_attributed_exit_without_claiming_flat(world):
    conn, venue, _, _ = world
    held(conn, venue)
    venue.equity = venue.last_equity = 800
    result = manage_cycle(conn, venue, "paper")
    assert result["state"]["severity"] == 2 and result["reductions_submitted"] == 1
    assert float(venue.sent[0]["qty"]) == 8
    assert result["reason"] == "risk_reductions_submitted_waiting_for_reconciliation"


def test_ambiguous_flow_latches_and_cancels_before_any_reduction(world):
    conn, venue, _, _ = world
    venue.activities.append(
        {
            "id": "late-deposit",
            "activity_type": "CSD",
            "net_amount": "10000",
            "date": datetime.now(UTC).date().isoformat(),
        }
    )
    venue.equity += 10000
    result = manage_cycle(conn, venue, "paper")
    assert result["state"]["severity"] == 2 and not venue.sent and venue.cancel_count > 0


def test_deposit_during_baseline_activity_capture_refuses_signed_change(world, monkeypatch):
    conn, venue, signed, _ = world
    before = account_state(conn, "paper")
    original = venue.account_activities_window
    calls = []

    def window(after, until):
        calls.append(1)
        if len(calls) == 2:
            venue.equity += 100
            venue.activities.append(
                {
                    "id": "baseline-race",
                    "activity_type": "CSD",
                    "net_amount": "100",
                    "transaction_time": venue.clock(),
                }
            )
        return original(after, until)

    monkeypatch.setattr(venue, "account_activities_window", window)
    with pytest.raises(ValueError, match="baseline activity capture"):
        signed()
    assert account_state(conn, "paper") == before


def test_cash_is_refreshed_after_a_buy_fills_during_cancellation(world, monkeypatch):
    conn, venue, _, _ = world
    venue.equity = venue.last_equity = 950
    venue.orders["resting"] = {"status": "new"}
    original = venue.cancel_open_orders

    def cancel():
        original()
        held(conn, venue, qty=5)

    monkeypatch.setattr(venue, "cancel_open_orders", cancel)
    result = manage_cycle(conn, venue, "paper")
    assert result["ready"], result
    assert venue.account().cash == 450
    assert venue._drawdown_cycle["available"] == 450


def test_funding_before_signed_baseline_does_not_corrupt_daily_reference(world):
    conn, venue, signed, _ = world
    venue.equity = 2000
    venue.last_equity = 1000
    venue.activities.append(
        {
            "id": "initial-funding",
            "activity_type": "CSD",
            "net_amount": "1000",
            "transaction_time": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        }
    )
    signed("restore")
    result = manage_cycle(conn, venue, "paper")
    assert result["ready"] and result["state"]["daily_loss"] == "0"


def test_live_reduction_rechecks_authorization_immediately_before_send(world, monkeypatch):
    from decimal import Decimal

    from algua.execution import drawdown_actions

    conn, venue, signed, _ = world
    signed(lane="live")
    state = account_state(conn, "live")
    conn.execute(
        "INSERT INTO strategies(id,name,stage,created_at,updated_at) "
        "VALUES (1,'synthetic_s','live','t','t')"
    )
    conn.commit()
    venue.authorization = SimpleNamespace(strategy_id=1)
    monkeypatch.setattr(drawdown_actions, "authorization_active", lambda *args: False)
    with pytest.raises(ValueError, match="authorization revoked"):
        drawdown_actions._record_and_send(
            conn, venue, state, {"name": "synthetic_s", "id": 1}, "AAPL", Decimal(1), Decimal(100)
        )
    assert not venue.sent


def test_cli_paper_checks_risk_even_without_tickable_strategies(world, monkeypatch):
    import json

    from typer.testing import CliRunner

    from algua.cli import paper_cmd
    from algua.cli.main import app

    conn, venue, _, _ = world
    monkeypatch.setenv("ALGUA_DB_PATH", conn.execute("PRAGMA database_list").fetchone()["file"])
    monkeypatch.setattr(paper_cmd, "_alpaca_broker_from_settings", lambda: venue)
    venue.equity = venue.last_equity = 800
    result = CliRunner().invoke(app, ["paper", "run-all", "--snapshot", "unused"])
    assert result.exit_code == 1, result.stdout
    assert json.loads(result.stdout)["code"] == "drawdown_control_blocked"
    assert venue.cancel_count > 0 and not venue.sent


def test_cli_live_surfaces_intervention_without_inventing_live_authority(world, monkeypatch):
    import json

    from typer.testing import CliRunner

    from algua.cli import layered_runtime, live_cmd
    from algua.cli.main import app

    conn, venue, signed, _ = world
    signed(lane="live")
    monkeypatch.setenv("ALGUA_DB_PATH", conn.execute("PRAGMA database_list").fetchone()["file"])
    monkeypatch.setattr(layered_runtime, "build_broker", lambda *args: venue)
    monkeypatch.setattr(live_cmd, "_alpaca_live_broker", lambda *args: pytest.fail("no authority"))
    venue.equity = venue.last_equity = 800
    result = CliRunner().invoke(app, ["live", "run-all", "--snapshot", "unused"])
    assert result.exit_code == 1, result.stdout
    assert json.loads(result.stdout)["code"] == "drawdown_control_blocked"
    assert not venue.sent and account_state(conn, "live")["severity"] == 2


def test_unsigned_cli_config_only_issues_challenge(world, monkeypatch, tmp_path):
    import json

    from typer.testing import CliRunner

    from algua.cli import risk_cmd
    from algua.cli.main import app

    conn, venue, _, _ = world
    monkeypatch.setenv("ALGUA_DB_PATH", conn.execute("PRAGMA database_list").fetchone()["file"])
    monkeypatch.setattr(risk_cmd, "_broker", lambda lane: venue)
    policy = tmp_path / "policy.json"
    policy.write_text('{"normal_capital":"1000","halt_at":".3"}')
    before = account_state(conn, "paper")
    result = CliRunner().invoke(app, ["risk", "configure", "paper", "--policy", str(policy)])
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["action"] == "drawdown_challenge"
    assert account_state(conn, "paper") == before


def test_live_watcher_requires_existing_signature_verified_allocated_source(world, monkeypatch):
    from algua.execution import drawdown_watch
    from algua.execution.broker_factory import BrokerKind

    conn, _, _, _ = world
    selected = []
    monkeypatch.setattr(drawdown_watch, "build_broker", lambda *args: selected.append(args) or args)
    assert drawdown_watch.live_check_broker(conn) == (BrokerKind.ALPACA_LIVE_DRAIN,)
    conn.execute(
        "INSERT INTO strategies(id,name,stage,created_at,updated_at) "
        "VALUES (1,'synthetic_live','live','t','t')"
    )
    conn.execute(
        "INSERT INTO strategy_allocations(strategy_id,capital,effective_ts,actor) "
        "VALUES (1,1000,'t','human')"
    )
    conn.commit()
    auth = object()
    checked = []
    monkeypatch.setattr(
        live_gate, "verify_live_authorization", lambda *args: checked.append(args[2]) or auth
    )
    assert drawdown_watch.live_check_broker(conn) == (BrokerKind.ALPACA_LIVE, auth)
    assert checked == ["synthetic_live"]


def test_failed_second_assessment_also_latches_halt(world, monkeypatch):
    from algua.execution import drawdown_cycle

    conn, venue, _, _ = world
    original = drawdown_cycle._observe
    calls = []

    def observe(*args):
        calls.append(1)
        if len(calls) == 2:
            raise ValueError("SYNTHETIC post-cancel account failure")
        return original(*args)

    monkeypatch.setattr(drawdown_cycle, "_observe", observe)
    result = manage_cycle(conn, venue, "paper")
    assert result["state"]["severity"] == 2
    monkeypatch.setattr(drawdown_cycle, "_observe", original)
    assert manage_cycle(conn, venue, "paper")["reason"] == "drawdown_halted_flat"


def test_revocation_after_recording_does_not_poison_restoration(world, monkeypatch):
    from decimal import Decimal

    from algua.execution import drawdown_actions

    conn, venue, signed, _ = world
    signed(lane="live")
    state = account_state(conn, "live")
    conn.execute(
        "INSERT INTO strategies(id,name,stage,created_at,updated_at) "
        "VALUES (1,'synthetic_s','live','t','t')"
    )
    conn.commit()
    venue.authorization = SimpleNamespace(strategy_id=1)
    checks = iter([True, False])
    monkeypatch.setattr(drawdown_actions, "authorization_active", lambda *args: next(checks))
    with pytest.raises(ValueError, match="authorization revoked"):
        drawdown_actions._record_and_send(
            conn, venue, state, {"name": "synthetic_s", "id": 1}, "AAPL", Decimal(1), Decimal(100)
        )
    assert not venue.sent
    assert conn.execute("SELECT phase FROM drawdown_reductions").fetchone()[0] == "not_submitted"
    assert conn.execute("SELECT COUNT(*) FROM live_orders").fetchone()[0] == 0
    result, _ = signed("restore", lane="live")
    assert result["ok"]
