"""Per-order rechecks and a shared exposure reservation for configured account policies."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from algua.execution.alpaca_broker import posted_notional
from algua.registry.drawdown_store import account_state, policy_for
from algua.risk.layered import decimal


def cycle_active(conn, broker, lane: str) -> bool:
    state = account_state(conn, lane)
    if state is None:
        return True
    cycle = getattr(broker, "_drawdown_cycle", None)
    if not isinstance(cycle, dict):
        return False
    try:
        age = (datetime.now(UTC) - datetime.fromisoformat(state["observed_at"])).total_seconds()
        return bool(
            state["severity"] < 2
            and not state["blocked_reason"]
            and all(
                cycle[key] == state[key]
                for key in ("revision", "policy_id", "account_id", "observed_at")
            )
            and 0 <= age <= 120
        )
    except (ValueError, TypeError):
        return False


def effective_allocation(conn, broker, lane: str, allocation: float) -> float:
    state = account_state(conn, lane)
    if state is None:
        return allocation
    if not cycle_active(conn, broker, lane):
        raise ValueError("configured drawdown policy requires a fresh guarded run-all cycle")
    policy = policy_for(conn, state)
    fraction = broker._drawdown_cycle["fraction"]
    return float(min(decimal(allocation), decimal(policy.normal_capital)) * fraction)


def reserve(conn, broker, lane: str, prior):
    if account_state(conn, lane) is None:
        return prior

    def checked(symbol: str, requested: float) -> float:
        if not cycle_active(conn, broker, lane):
            raise ValueError("drawdown state changed or cycle expired before buy")
        pool = broker._drawdown_cycle
        bound = min(decimal(requested), pool["available"])
        grant = min(bound, decimal(prior(symbol, float(bound)))) if prior else bound
        if grant < 0:
            raise ValueError("negative exposure reservation")
        pool["available"] -= decimal(posted_notional(float(grant)))
        return float(grant)

    return checked


def require_cycle(conn, broker, lane: str) -> None:
    if not cycle_active(conn, broker, lane):
        raise ValueError("configured drawdown policy requires a fresh guarded run-all cycle")


def sizing_snapshot(conn, broker, lane: str, pair):
    snapshot, economic_nav = pair
    # Tighten only the sizing denominator. Never manufacture a loss in the accounting NAV/peak.
    return replace(
        snapshot, equity=effective_allocation(conn, broker, lane, snapshot.equity)
    ), economic_nav
