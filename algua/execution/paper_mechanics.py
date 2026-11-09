"""One owner-approved USD5 paper mechanics smoke, with no strategy/lifecycle evidence writes."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_FLOOR, Decimal

from algua.contracts.types import OrderIntent, Side
from algua.execution.alpaca_broker import TickSnapshot
from algua.execution.alpaca_reductions import reduction_price
from algua.execution.paper_mechanics_broker import (
    PAPER_URL,
    MechanicsBroker,
    opening_coid,
    readiness,
    risk_guard,
    source_identity,
)
from algua.execution.paper_mechanics_reconcile import (
    TERMINAL,
    reconcile,
    recover,
    recover_opening,
)
from algua.execution.paper_mechanics_state import acknowledge, intent, prepare, save, state
from algua.registry.drawdown_store import account_state
from algua.risk import global_halt
from algua.risk.layered import decimal


def _binding(current, expected_account, observed, symbol):
    if (current["account_id"] != expected_account or current["symbol"] != symbol
            or current["policy_id"] != observed["policy_id"]
            or current["baseline_at"] != observed["baseline_at"]):
        raise ValueError("mechanics account, recorded policy or baseline changed")


def initialize(conn, risk_conn, broker, expected_account: str, symbol: str) -> dict:
    identity = source_identity()
    readiness(broker, expected_account, symbol)
    observed, _ = risk_guard(risk_conn, broker, expected_account, opening=True, symbol=symbol)
    if conn.execute("SELECT 1 FROM smoke").fetchone():
        current = state(conn)
        _binding(current, expected_account, observed, symbol)
        return current
    started = broker.clock()
    coid = opening_coid(risk_conn, observed, symbol)
    if (broker.get_order_by_client_order_id(coid) is not None
            or any(decimal(q) != 0 for q in broker.get_positions().values)
            or broker.list_open_orders()
            or broker.account_activities_window(observed["baseline_at"], broker.clock())):
        raise ValueError("mechanics requires an unused recorded policy and empty settled baseline")
    if any(decimal(q) != 0 for q in broker.get_positions().values) or broker.list_open_orders():
        raise ValueError("mechanics baseline changed during initialization")
    current = {"account_id": expected_account, "symbol": symbol, "phase": "ready",
               "policy_id": observed["policy_id"], "baseline_at": observed["baseline_at"],
               "started_at": started, "opening_coid": coid, "opening_budget_consumed": "0.00",
               "qualification_credit": False, "live_authority": False,
               "source": identity}
    save(conn, current, "initialized")
    return current


def _guarded_send(conn, risk_conn, broker, current, observed, policy, kind, held):
    symbol = current["symbol"]
    if not broker.regular_market_open():
        raise ValueError("regular paper market must be open; orders are not queued overnight")
    readiness(broker, current["account_id"], symbol)
    account = broker.account()
    if account.account_id != current["account_id"] or decimal(account.cash) < 0:
        raise ValueError("paper account identity/cash changed before submit")
    risk_conn.execute("BEGIN IMMEDIATE")
    try:
        if account_state(risk_conn, "paper") != observed:
            raise ValueError("recorded risk state changed before mechanics submit")
        if kind == "buy" and global_halt.is_engaged(risk_conn):
            raise ValueError("global halt blocks mechanics opening purchases")
        if kind == "buy":
            amount = min(Decimal(5), decimal(policy.normal_capital), decimal(account.cash),
                         decimal(account.buying_power)).quantize(Decimal(".01"), ROUND_FLOOR)
            if amount < 1:
                raise ValueError("smoke amount is below venue minimum; do not raise the cap")
            snap = broker.snapshot([symbol])
            if any(decimal(q) != 0 for q in snap.qtys.values()):
                raise ValueError("account is no longer flat before mechanics opening")
            reduction_price(broker.reduction_quote(symbol, feed=policy.feed),
                            policy, datetime.fromisoformat(broker.clock()))
            request = {"notional": str(amount), "type": "market"}
            coid = current["opening_coid"]
            prepare(conn, current, kind, coid, request)

            def reserved(order_symbol, requested):
                age = (datetime.now(UTC) - datetime.fromisoformat(
                    observed["observed_at"])).total_seconds()
                if (order_symbol != symbol or account_state(risk_conn, "paper") != observed
                        or not 0 <= age <= 60 or global_halt.is_engaged(risk_conn)):
                    raise ValueError("mechanics reservation account/policy changed")
                return float(min(amount, max(Decimal(0), decimal(requested))))

            # The approved fixed-capital denominator sizes the smoke; account NAV is unchanged.
            sized = TickSnapshot(float(amount), snap.market_values, snap.qtys)
            order_id = broker.submit_sized(
                OrderIntent(symbol, Side.BUY, 1.0, datetime.now(UTC)), sized,
                client_order_id=coid, reserve=reserved)
        else:
            if broker.list_open_orders():
                raise ValueError("own order cancellation must settle before a mechanics exit")
            actual = decimal(broker.get_positions().get(symbol, 0))
            qty = min(held, actual).quantize(Decimal("1e-9"), ROUND_FLOOR)
            if qty <= 0:
                raise ValueError("no verified sellable mechanics shares")
            price = reduction_price(broker.reduction_quote(symbol, feed=policy.feed),
                                    policy, datetime.fromisoformat(broker.clock()))
            coid = current["opening_coid"].replace("pm-open-", "pm-exit-")
            request = {"qty": str(qty), "type": "limit", "limit_price": str(price)}
            prepare(conn, current, kind, coid, request)
            order_id = broker.submit_reduction(symbol, str(qty), str(price), coid)
        if order_id in {"noop", "skipped"} or not order_id:
            raise ValueError("mechanics order not submitted; original intent remains consumed")
        acknowledge(conn, kind, order_id)
    finally:
        risk_conn.rollback()  # Release the policy/configuration write lock; no invented risk grant.


def _cancel_opening(conn, broker, current):
    # Reverify the account even when canceling after a failed risk assessment.
    if not isinstance(broker, MechanicsBroker) or broker.base_url != PAPER_URL:
        raise ValueError("exact paper broker host is required for safe cancellation")
    if broker.account().account_id != current["account_id"]:
        raise ValueError("cannot verify mechanics account for safe opening cancellation")
    raw = recover_opening(conn, broker, current)
    if raw is not None and raw["status"] not in TERMINAL:
        current["phase"] = "opening_cancel_pending"
        save(conn, current, "own_opening_cancel_requested")
        broker.cancel_order(raw["id"])


def operate(conn, risk_conn, broker, expected_account: str, action: str) -> dict:
    if action not in {"step", "close"}:
        raise ValueError("unknown mechanics action")
    current = state(conn)
    if current["account_id"] != expected_account:
        raise ValueError("mechanics expected account mismatch")
    if current["source"] != source_identity():
        raise ValueError("mechanics source/dependency identity changed")
    try:
        readiness(broker, expected_account, current["symbol"])
        observed, policy = risk_guard(risk_conn, broker, expected_account, opening=False,
                                      symbol=current["symbol"])
        _binding(current, expected_account, observed, current["symbol"])
    except Exception:
        try:
            _cancel_opening(conn, broker, current)
        except Exception as cancel_error:
            current["cancel_unresolved"] = type(cancel_error).__name__
        current["phase"] = "risk_assessment_blocked"
        save(conn, current, "risk_assessment_blocked")
        raise
    if observed["severity"] > 0 or global_halt.is_engaged(risk_conn):
        # The USD5 smoke fully exits on either intervention, stricter than partial reduction.
        current["risk_intervention"] = {
            "severity": observed["severity"], "global_halt": global_halt.is_engaged(risk_conn)}
        action = "close"
    if action == "close":
        # Cancellation needs exact order ownership, not complete publication of asynchronous fills.
        current["phase"] = "closing_reconcile_pending"
        save(conn, current, "close_requested")
        _cancel_opening(conn, broker, current)
    orders = recover(conn, broker, current)
    held = reconcile(conn, broker, current, orders)
    if action == "close":
        if "sell" in orders and orders["sell"]["status"] not in TERMINAL:
            current["phase"] = "closing_pending"
            save(conn, current, "reconciled")
            return current
        if any(raw["status"] not in TERMINAL for raw in orders.values()):
            raise ValueError("own mechanics cancellation has not settled")
        if held > 0 and intent(conn, "sell") is None:
            _guarded_send(conn, risk_conn, broker, current, observed, policy, "sell", held)
            return current
        if held > 0:
            raise ValueError("original mechanics exit is terminal with residual shares; review")
        current["phase"] = "closed"
    elif intent(conn, "buy") is None and current["phase"] != "closed":
        observed, policy = risk_guard(risk_conn, broker, expected_account, opening=True,
                                      symbol=current["symbol"])
        _binding(current, expected_account, observed, current["symbol"])
        _guarded_send(conn, risk_conn, broker, current, observed, policy, "buy", held)
        return current
    elif orders:
        current["phase"] = "held" if held else "opening_pending"
        if all(raw["status"] in TERMINAL for raw in orders.values()) and not held:
            current["phase"] = "closed"
    save(conn, current, "reconciled")
    return current
