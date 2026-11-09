"""Isolated paper smoke fixtures; no venue/network or promotion evidence."""
from datetime import UTC, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from algua.execution.paper_mechanics import initialize, operate
from algua.execution.paper_mechanics_broker import MechanicsBroker
from algua.execution.paper_mechanics_state import ledger
from algua.registry.db import connect, migrate
from algua.registry.drawdown_store import account_state
from algua.risk.layered import DrawdownPolicy


class Venue(MechanicsBroker):
    def __init__(self):
        super().__init__("fixture", "fixture")
        self.account_id = "isolated-paper"
        self.qty = 0
        self.orders = {}
        self.activities = []
        self.posts = []
        self.canceled = []
        self.market_open = True
        self.fail_submit = False
        self.fractionable = True

    def clock(self):
        return datetime.now(UTC).isoformat()

    def regular_market_open(self):
        return self.market_open

    def mechanics_readiness(self, symbol):
        return {"id": self.account_id, "status": "ACTIVE", "currency": "USD",
                "trading_blocked": False, "account_blocked": False,
                "asset": {"symbol": symbol, "status": "active", "tradable": True,
                          "fractionable": self.fractionable, "class": "us_equity"}}

    def account(self):
        return SimpleNamespace(account_id=self.account_id, equity=1000, cash=1000-self.qty*100,
                               buying_power=1000, last_equity=1000)

    def snapshot(self, symbols):
        return SimpleNamespace(equity=1000, market_values={"CSL": self.qty*100},
                               qtys={"CSL": self.qty})

    def get_positions(self):
        return pd.Series({"CSL": self.qty} if self.qty else {}, dtype=float)

    def list_open_orders(self):
        return [o for o in self.orders.values() if o["status"] in {"new", "partially_filled"}]

    def get_order_by_client_order_id(self, coid):
        return self.orders.get(coid)

    def account_activities_window(self, after, until):
        return self.activities

    def submit_sized(self, intent, snap, client_order_id=None, reserve=None):
        assert reserve("CSL", 5) == 5
        row = {"id": "venue-"+client_order_id, "client_order_id": client_order_id,
               "symbol": "CSL", "side": "buy", "notional": "5.00", "type": "market",
               "time_in_force": "day", "status": "new", "filled_qty": "0"}
        self.orders[client_order_id] = row
        self.posts.append(row)
        if self.fail_submit:
            raise TimeoutError("fixture accepted; acknowledgement lost")
        return row["id"]

    def cancel_order(self, order_id):
        self.canceled.append(order_id)
        next(o for o in self.orders.values() if o["id"] == order_id)["status"] = "canceled"

    def reduction_quote(self, symbol, feed):
        return {"bp": 100, "ap": 100.1, "bs": 1, "as": 1, "t": self.clock()}

    def submit_reduction(self, symbol, qty, price, coid):
        assert float(qty) <= self.qty
        row = {"id": "venue-"+coid, "client_order_id": coid, "symbol": symbol,
               "side": "sell", "type": "limit", "limit_price": price, "qty": qty,
               "time_in_force": "day", "status": "new", "filled_qty": "0"}
        self.orders[coid] = row
        self.posts.append(row)
        return row["id"]

    def fill(self, side, qty, *, status="filled"):
        order = next(o for o in reversed(list(self.orders.values())) if o["side"] == side)
        order.update(status=status, filled_qty=str(qty))
        self.qty += qty if side == "buy" else -qty
        self.activities.append({"id": str(len(self.activities)), "activity_type": "FILL",
                                "order_id": order["id"], "symbol": "CSL", "side": side,
                                "qty": str(qty), "price": "100", "transaction_time": self.clock()})


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr("algua.execution.paper_mechanics.source_identity", lambda: {
        "commit": "SYNTHETIC_FIXTURE", "dependency_hash": "SYNTHETIC_FIXTURE"})
    conn = connect(tmp_path / "risk.db")
    migrate(conn)
    venue = Venue()
    stamp = venue.clock()
    policy = DrawdownPolicy("5.00", permitted_symbols=("CSL",))
    import json
    pid = conn.execute("INSERT INTO drawdown_policies "
                       "(lane,account_id,policy_json,principal,created_at) VALUES (?,?,?,?,?)",
                       ("paper", venue.account_id, json.dumps(policy.to_dict()), "fixture", stamp)
                       ).lastrowid
    state = {"lane": "paper", "account_id": venue.account_id, "policy_id": pid,
             "baseline_at": stamp, "baseline_equity": "1000", "baseline_nav": "5",
             "baseline_seen": {}, "activity_fingerprints": {}, "peak_nav": "5",
             "last_nav": "5", "last_equity": "1000", "severity": 0,
             "blocked_reason": None, "last_human_action": {"principal": "fixture"}}
    conn.execute("INSERT INTO drawdown_accounts VALUES (?,?,?,?,?)",
                 ("paper", venue.account_id, pid, 0, json.dumps(state)))
    conn.commit()
    yield conn, venue, tmp_path / "mechanics.db"
    conn.close()


def init(world):
    conn, venue, path = world
    with ledger(path) as db:
        return initialize(db, conn, venue, "isolated-paper", "CSL")


def run(world, action="step"):
    conn, venue, path = world
    with ledger(path) as db:
        return operate(db, conn, venue, "isolated-paper", action)


def test_one_durable_opening_and_restart(world):
    init(world)
    _, venue, path = world
    venue.fail_submit = True
    with pytest.raises(TimeoutError):
        run(world)
    assert len(venue.posts) == 1
    venue.fail_submit = False
    out = run(world)
    assert out["opening_budget_consumed"] == "5.00"
    assert len(venue.posts) == 1
    with ledger(path) as db:
        assert db.execute("SELECT count(*) FROM intents").fetchone()[0] == 1


def test_missing_acceptance_never_reposts(world):
    init(world)
    run(world)
    _, venue, _ = world
    venue.orders.clear()
    with pytest.raises(ValueError, match="acceptance"):
        run(world)
    assert len(venue.posts) == 1


@pytest.mark.parametrize("failure", ["account", "host", "policy", "market", "asset"])
def test_refusals_never_open(world, failure):
    conn, venue, _ = world
    if failure == "account":
        venue.account_id = "wrong"
    elif failure == "host":
        venue.base_url = "https://api.alpaca.markets"
    elif failure == "policy":
        conn.execute("UPDATE drawdown_accounts SET lane='live'")
        conn.commit()
    elif failure == "market":
        venue.market_open = False
    else:
        venue.fractionable = False
    if failure in {"account", "host", "policy", "asset"}:
        with pytest.raises(ValueError):
            init(world)
    else:
        init(world)
        with pytest.raises(ValueError, match="market"):
            run(world)
    assert not venue.posts


def test_partial_cancel_exit_and_no_qualification_evidence(world):
    conn, venue, _ = world
    init(world)
    run(world)
    venue.fill("buy", .02, status="partially_filled")
    run(world, "close")
    assert len(venue.canceled) == 1
    assert venue.posts[-1]["side"] == "sell"
    assert venue.posts[-1]["qty"] == "0.020000000"
    assert run(world, "close")["phase"] == "closing_pending"
    assert len(venue.canceled) == 1
    assert len(venue.posts) == 2
    venue.fill("sell", .02)
    assert run(world, "close")["phase"] == "closed"
    assert run(world)["phase"] == "closed"
    assert len(venue.posts) == 2
    for table in ("strategies", "tick_snapshots", "gate_evaluations", "paper_orders",
                  "paper_venue_orders", "experimental_paper_sessions", "forward_gate_evaluations"):
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    assert account_state(conn, "paper") is not None


def test_unknown_activity_and_positions_stop(world):
    init(world)
    _, venue, _ = world
    venue.activities.append({"id": "unknown", "activity_type": "FILL"})
    with pytest.raises(ValueError):
        run(world)
    assert not venue.posts


def test_journal_rejects_amount_above_lifetime_cap(world):
    from algua.execution.paper_mechanics_state import prepare

    current = init(world)
    with ledger(world[2]) as db, pytest.raises(ValueError, match="cap"):
        prepare(db, current, "buy", "bad-cap", {"notional": "5.01", "type": "market"})


def test_hard_stop_before_post_leaves_consumed_intent(world, monkeypatch):
    import sqlite3

    init(world)
    _, venue, path = world

    def crash(*args, **kwargs):
        check = sqlite3.connect(path)
        try:
            assert check.execute("SELECT count(*) FROM intents").fetchone()[0] == 1
            assert '5.00' in check.execute("SELECT payload FROM smoke").fetchone()[0]
        finally:
            check.close()
        raise SystemExit("SYNTHETIC_FIXTURE crash before transport")

    monkeypatch.setattr(venue, "submit_sized", crash)
    with pytest.raises(SystemExit):
        run(world)
    with pytest.raises(ValueError, match="acceptance"):
        run(world)
    assert not venue.posts


def test_foreign_order_is_never_canceled(world):
    init(world)
    run(world)
    venue = world[1]
    venue.orders["foreign"] = {"id": "foreign", "client_order_id": "foreign", "status": "new"}
    with pytest.raises(ValueError, match="unexpected open order"):
        run(world, "close")
    opening = next(o for o in venue.orders.values() if o["client_order_id"] != "foreign")
    assert venue.canceled == [opening["id"]]
    assert venue.orders["foreign"]["status"] == "new"


def test_late_fill_and_false_order_identity_refuse(world):
    init(world)
    run(world)
    venue = world[1]
    raw = next(iter(venue.orders.values()))
    raw["filled_qty"] = "0.02"
    with pytest.raises(ValueError, match="publication"):
        run(world, "close")
    raw["side"] = "sell"
    with pytest.raises(ValueError, match="identity"):
        run(world)
    assert len(venue.posts) == 1


def test_same_signed_policy_cannot_start_second_smoke(world):
    conn, venue, path = world
    init(world)
    run(world)
    run(world, "close")
    with ledger(path.with_name("second.db")) as db, pytest.raises(ValueError, match="unused"):
        initialize(db, conn, venue, "isolated-paper", "CSL")
    assert len(venue.posts) == 1


def test_source_drift_refuses_even_original_intent(world, monkeypatch):
    init(world)
    monkeypatch.setattr("algua.execution.paper_mechanics.source_identity", lambda: {
        "commit": "different", "dependency_hash": "different"})
    with pytest.raises(ValueError, match="identity"):
        run(world)
    assert not world[1].posts


def test_existing_alpaca_sizer_posts_exact_durable_budget(world, monkeypatch):
    import sqlite3

    init(world)
    _, venue, path = world
    sent = []

    def post(endpoint, body):
        assert endpoint == "/v2/orders"
        assert body["notional"] == "5.00"
        assert body["side"] == "buy" and body["type"] == "market"
        assert body["client_order_id"].startswith("pm-open-")
        check = sqlite3.connect(path)
        try:
            assert check.execute("SELECT client_order_id FROM intents").fetchone()[0] == (
                body["client_order_id"])
        finally:
            check.close()
        sent.append(body)
        return SimpleNamespace(status_code=201, text="", json=lambda: {"id": "fixture-order"})

    monkeypatch.setattr(venue, "submit_sized", MechanicsBroker.submit_sized.__get__(venue))
    monkeypatch.setattr(venue, "_post", post)
    run(world)
    assert len(sent) == 1


def test_paper_readiness_transport_is_get_only(monkeypatch):
    from algua.execution.paper_mechanics_broker import readiness

    venue = MechanicsBroker("fixture-key", "fixture-secret")
    calls = []
    account = {"id": "fixture", "status": "ACTIVE", "currency": "USD",
               "trading_blocked": False, "account_blocked": False}
    asset = {"symbol": "CSL", "class": "us_equity", "status": "active",
             "tradable": True, "fractionable": True}

    def get(url, **kwargs):
        calls.append(url)
        assert kwargs["allow_redirects"] is False
        return SimpleNamespace(status_code=200,
                               json=lambda: asset if "/assets/" in url else account)

    monkeypatch.setattr("requests.get", get)
    assert readiness(venue, None)["id"] == "fixture"
    assert calls == ["https://paper-api.alpaca.markets/v2/account",
                     "https://paper-api.alpaca.markets/v2/assets/CSL"]


def _overnight_drawdown(venue, monkeypatch, equity):
    original = venue.account

    def account():
        raw = original()
        raw.equity = equity
        raw.last_equity = equity  # Loss predates today's daily-loss reference.
        return raw

    monkeypatch.setattr(venue, "account", account)


def test_reduce_intervention_cancels_pending_smoke_buy(world, monkeypatch):
    init(world)
    run(world)
    conn, venue, _ = world
    _overnight_drawdown(venue, monkeypatch, 999.4)  # 12% of the fixed USD5 baseline.
    out = run(world)
    assert account_state(conn, "paper")["severity"] == 1
    assert len(venue.canceled) == 1
    assert not venue.list_open_orders()
    assert out["phase"] == "closed"
    assert out["risk_intervention"]["severity"] == 1
    assert len(venue.posts) == 1


@pytest.mark.parametrize("equity,severity", [(999.4, 1), (999.0, 2)])
def test_risk_intervention_exits_verified_holdings_on_step(world, monkeypatch, equity, severity):
    init(world)
    run(world)
    conn, venue, _ = world
    venue.fill("buy", .05)
    _overnight_drawdown(venue, monkeypatch, equity)
    out = run(world)
    assert account_state(conn, "paper")["severity"] == severity
    assert venue.posts[-1]["side"] == "sell"
    assert venue.posts[-1]["qty"] == "0.050000000"
    assert out["phase"] != "held"
    assert out["risk_intervention"]["severity"] == severity
    assert run(world)["phase"] == "closing_pending"
    assert len(venue.posts) == 2


def test_close_cancels_before_waiting_for_late_fill_publication(world):
    init(world)
    run(world)
    _, venue, _ = world
    opening = next(iter(venue.orders.values()))
    opening.update(status="partially_filled", filled_qty="0.02")
    venue.qty = .02
    with pytest.raises(ValueError, match="publication"):
        run(world, "close")
    assert venue.canceled == [opening["id"]]
    assert opening["status"] == "canceled"
    assert len(venue.posts) == 1  # No unverified exit or flat claim.


@pytest.mark.parametrize("account_changed", [False, True])
def test_failed_assessment_cancels_only_with_reverified_account(
    world, monkeypatch, account_changed,
):
    init(world)
    run(world)
    _, venue, _ = world
    opening = next(iter(venue.orders.values()))

    def unavailable(*args):
        if account_changed:
            venue.account_id = "different-account"
        raise ValueError("SYNTHETIC_FIXTURE account activity unavailable")

    monkeypatch.setattr(venue, "account_activities_window", unavailable)
    with pytest.raises(ValueError, match="unavailable"):
        run(world)
    assert venue.canceled == ([] if account_changed else [opening["id"]])
    assert len(venue.posts) == 1


def test_intervention_waits_for_own_cancel_settlement(world, monkeypatch):
    init(world)
    run(world)
    _, venue, path = world
    _overnight_drawdown(venue, monkeypatch, 999.4)
    monkeypatch.setattr(venue, "cancel_order", lambda oid: venue.canceled.append(oid))
    with pytest.raises(ValueError, match="not settled"):
        run(world)
    assert len(venue.canceled) == 1
    assert len(venue.posts) == 1
    with ledger(path) as db:
        from algua.execution.paper_mechanics_state import state
        assert state(db)["phase"] == "opening_cancel_pending"


@pytest.mark.parametrize("forged_own_identity", [False, True])
def test_failed_assessment_preserves_foreign_and_unverified_orders(
    world, monkeypatch, forged_own_identity,
):
    init(world)
    run(world)
    _, venue, _ = world
    own = next(iter(venue.orders.values()))
    venue.orders["foreign"] = {"id": "foreign", "client_order_id": "foreign", "status": "new"}
    if forged_own_identity:
        own["client_order_id"] = "not-the-original-intent"

    def unavailable(*args):
        raise ValueError("SYNTHETIC_FIXTURE assessment unavailable")

    monkeypatch.setattr(venue, "account_activities_window", unavailable)
    with pytest.raises(ValueError, match="unavailable"):
        run(world)
    assert venue.canceled == ([] if forged_own_identity else [own["id"]])
    assert venue.orders["foreign"]["status"] == "new"
    assert len(venue.posts) == 1


@pytest.mark.parametrize("failure", ["asset", "asset_api", "account_blocked"])
def test_readiness_failure_still_cancels_verified_own_opening(world, monkeypatch, failure):
    init(world)
    run(world)
    _, venue, _ = world
    original = venue.mechanics_readiness

    def unavailable(symbol):
        if failure == "asset_api":
            raise ValueError("SYNTHETIC_FIXTURE asset API unavailable")
        raw = original(symbol)
        if failure == "asset":
            raw["asset"]["tradable"] = False
        else:
            raw["account_blocked"] = True
        return raw

    monkeypatch.setattr(venue, "mechanics_readiness", unavailable)
    with pytest.raises(ValueError):
        run(world)
    assert len(venue.canceled) == 1
    assert not venue.list_open_orders()
    assert len(venue.posts) == 1


def test_intervention_waiting_for_market_never_reports_held_normal(world, monkeypatch):
    from algua.execution.paper_mechanics_state import state

    init(world)
    run(world)
    _, venue, path = world
    venue.fill("buy", .05)
    _overnight_drawdown(venue, monkeypatch, 999.0)
    venue.market_open = False
    with pytest.raises(ValueError, match="market"):
        run(world)
    with ledger(path) as db:
        current = state(db)
        assert current["phase"] == "closing_reconcile_pending"
        assert current["risk_intervention"]["severity"] == 2
    assert len(venue.posts) == 1


def test_unsigned_paper_policy_supports_bounded_mechanics(world):
    from algua.registry.drawdown_auth import paper_change

    conn, venue, _ = world
    result = paper_change(conn, venue, purpose="configure",
                          policy=DrawdownPolicy("5", permitted_symbols=("CSL",)))
    assert result["actor"] == "agent"
    assert "last_human_action" not in result["state"]
    init(world)
    run(world)
    assert len(venue.posts) == 1
    assert venue.posts[0]["notional"] == "5.00"


@pytest.mark.parametrize("options", [{"normal_capital": "6"},
                                     {"permitted_symbols": ("CSL", "AAPL")},
                                     {"reduce_at": ".11"}, {"halt_at": ".21"},
                                     {"reduced_fraction": ".6"}])
def test_automated_policy_never_loosens_smoke_limits(world, options):
    from algua.registry.drawdown_auth import paper_change

    conn, venue, _ = world
    config = {"normal_capital": "5", "permitted_symbols": ("CSL",)} | options
    paper_change(conn, venue, purpose="configure", policy=DrawdownPolicy(**config))
    with pytest.raises(ValueError, match="smoke limits"):
        init(world)
    assert not venue.posts


def test_automated_policy_requires_immutable_configuration_provenance(world):
    import json

    conn, _, _ = world
    state = account_state(conn, "paper")
    # A mutable marker alone cannot turn an unrelated policy into an automated configuration.
    state.pop("last_human_action")
    state["last_paper_action"] = {"actor": "agent", "purpose": "configure"}
    conn.execute("UPDATE drawdown_accounts SET state_json=?", (json.dumps(state),))
    conn.commit()
    with pytest.raises(ValueError, match="recorded paper policy"):
        init(world)
