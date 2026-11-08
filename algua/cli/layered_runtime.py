"""Thin CLI integration for the shared account controller; no new live authorization path."""

from __future__ import annotations

import typer

from algua.cli.app import emit
from algua.execution.broker_factory import BrokerKind, build_broker
from algua.execution.drawdown_cycle import manage_cycle
from algua.registry.drawdown_store import account_state


def checked_cycle(conn, broker, lane: str):
    result = manage_cycle(conn, broker, lane)
    if result is not None and not result["ready"]:
        emit({"ok": False, "code": "drawdown_control_blocked", "drawdown_control": result})
        raise typer.Exit(1)
    return broker


def paper_cycle(conn, factory):
    return checked_cycle(conn, factory(), "paper") if account_state(conn, "paper") else None


def observe_live(conn):
    if account_state(conn, "live") is not None:
        result = manage_cycle(
            conn, build_broker(BrokerKind.ALPACA_LIVE_DRAIN), "live", observe_only=True
        )
        if result is not None and (
            result["state"]["severity"] > 0 or result["state"]["blocked_reason"]
        ):
            # Still allow the caller to obtain existing strategy authorization for a guarded exit.
            # If it has none, the independent persisted latch remains visible in fleet/risk status.
            return result
    return None


def live_health(result):
    if result is not None:
        emit({"ok": False, "code": "drawdown_control_blocked", "drawdown_control": result})
        raise typer.Exit(1)
