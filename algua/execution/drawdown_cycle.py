"""Shared account intervention: durable assessment precedes cancellation and guarded reductions."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from algua.config.settings import get_settings
from algua.execution.drawdown_actions import (
    owned_book,
    recover_reductions,
    reduce_book,
    synchronize,
)
from algua.execution.drawdown_flows import cash_flows, previous_close
from algua.operator.alerts import emit_alert
from algua.registry.drawdown_auth import activity_start
from algua.registry.drawdown_store import account_state, block, policy_for, write_state
from algua.risk import global_halt
from algua.risk.layered import decimal, evaluate


def _observe(conn, broker, state):
    policy = policy_for(conn, state)
    before = datetime.fromisoformat(broker.clock())
    account = broker.account()
    now = datetime.fromisoformat(broker.clock())
    if (
        account.account_id != state["account_id"]
        or before.tzinfo is None
        or now.tzinfo is None
        or not 0 <= (now - before).total_seconds() <= 60
        or abs((datetime.now(UTC) - now).total_seconds()) > 60
        or decimal(account.equity) <= 0
        or decimal(account.cash) < 0
    ):
        raise ValueError("risk account identity, clock or equity is unusable")
    prior_close = previous_close(now)
    activities = broker.account_activities_window(
        activity_start(state["baseline_at"]), now.isoformat()
    )
    flows, daily_flows, seen = cash_flows(
        activities, state, before_read=before, prior_close=prior_close
    )
    nav = (
        decimal(state["baseline_nav"])
        + decimal(account.equity)
        - decimal(state["baseline_equity"])
        - flows
    )
    risk = evaluate(policy, nav, decimal(state["peak_nav"]), state["severity"])
    daily_base = (
        decimal(state["baseline_nav"])
        + decimal(account.last_equity)
        - decimal(state["baseline_equity"])
        - flows
        + daily_flows
    )
    if daily_base <= 0:
        raise ValueError("daily-loss reference is unusable")
    daily_limit = min(Decimal(".05"), decimal(get_settings().book_max_daily_loss))
    if not 0 < daily_limit <= 1:
        raise ValueError("daily-loss policy is unusable")
    daily_loss = 1 - nav / daily_base
    daily_trip = daily_loss >= daily_limit
    updated = state | {
        "peak_nav": str(risk.peak),
        "drawdown": str(risk.drawdown),
        "severity": max(risk.severity, 2 if daily_trip else 0),
        "last_nav": str(nav),
        "last_equity": str(decimal(account.equity)),
        "last_cash": str(decimal(account.cash)),
        "flow_total": str(flows),
        "daily_loss": str(daily_loss),
        "activity_fingerprints": seen,
        "observed_at": now.isoformat(),
        "blocked_reason": None,
    }
    with conn:
        updated = write_state(conn, state, updated, "assessment")
    if updated["severity"] > state["severity"]:
        emit_alert(
            "drawdown_intervention",
            {
                "lane": state["lane"],
                "severity": updated["severity"],
                "drawdown": updated["drawdown"],
            },
            alert_cmd=get_settings().alert_cmd,
        )
    return updated, policy


def _assessment_failed(conn, broker, lane: str, exc: Exception) -> dict:
    state = block(conn, lane, f"account_assessment_failed:{type(exc).__name__}", halt=True)
    try:
        broker.cancel_open_orders()
    except Exception:
        pass
    emit_alert(
        "drawdown_control_blocked",
        {"lane": lane, "reason": state["blocked_reason"]},
        alert_cmd=get_settings().alert_cmd,
    )
    return {"ready": False, "state": state, "reason": state["blocked_reason"]}


def manage_cycle(conn, broker, lane: str, *, observe_only: bool = False) -> dict | None:
    state = account_state(conn, lane)
    if state is None:
        return None
    try:
        state, policy = _observe(conn, broker, state)
    except Exception as exc:
        return _assessment_failed(conn, broker, lane, exc)
    try:
        if state["severity"] > 0:
            broker.cancel_open_orders()
        if observe_only:
            return {"ready": False, "state": state, "reason": "observed_without_trading_authority"}
        if global_halt.is_engaged(conn):
            raise ValueError("independent global halt remains engaged")
        if broker.list_open_orders():
            broker.cancel_open_orders()
            if broker.list_open_orders():
                raise ValueError("order cancellation is not settled")
        recover_reductions(conn, broker, state)
        snapshot = synchronize(conn, broker, lane)
        # Cancellations may fill orders. Refresh economic state/cash before reducing or arming buys.
        prior_level = state["severity"]
        try:
            state, policy = _observe(conn, broker, state)
        except Exception as exc:
            return _assessment_failed(conn, broker, lane, exc)
        if state["severity"] > prior_level:
            broker.cancel_open_orders()
            if broker.list_open_orders():
                raise ValueError("new intervention cancellation is not settled")
            snapshot = synchronize(conn, broker, lane)
        owners = owned_book(conn, lane, snapshot)
        fraction = (Decimal(1), decimal(policy.reduced_fraction), Decimal(0))[state["severity"]]
        submitted = reduce_book(conn, broker, state, policy, fraction, snapshot, owners)
        if submitted:
            state = block(conn, lane, "risk_reductions_submitted_waiting_for_reconciliation")
            return {
                "ready": False,
                "state": state,
                "reductions_submitted": submitted,
                "reason": state["blocked_reason"],
            }
        if state["severity"] >= 2:
            return {
                "ready": False,
                "state": state,
                "reason": (
                    "drawdown_halted_residual"
                    if any(snapshot.qtys.values())
                    else "drawdown_halted_flat"
                ),
            }
        gross = sum((decimal(v) for v in snapshot.market_values.values()), Decimal(0))
        available = max(
            Decimal(0),
            min(decimal(state["last_cash"]), decimal(policy.normal_capital) * fraction - gross),
        )
        # One shared pool per account cycle. Independent venue writers remain unsupported.
        broker._drawdown_cycle = {
            "lane": lane,
            "revision": state["revision"],
            "policy_id": state["policy_id"],
            "account_id": state["account_id"],
            "fraction": fraction,
            "available": available,
            "observed_at": state["observed_at"],
        }
        return {"ready": True, "state": state, "reason": None}
    except Exception as exc:
        state = block(conn, lane, str(exc))
        emit_alert(
            "drawdown_control_blocked",
            {"lane": lane, "reason": state["blocked_reason"]},
            alert_cmd=get_settings().alert_cmd,
        )
        return {"ready": False, "state": state, "reason": state["blocked_reason"]}
