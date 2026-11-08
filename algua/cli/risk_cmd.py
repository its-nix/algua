"""Signed opt-in risk policy, status and explicit broker-backed checks."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from algua.cli.app import app, emit
from algua.cli.errors import json_errors
from algua.execution.broker_factory import BrokerKind, build_broker
from algua.execution.drawdown_cycle import manage_cycle
from algua.execution.drawdown_watch import live_check_broker
from algua.primitives.bounded_file import read_relative_regular
from algua.registry.db import registry_conn
from algua.registry.drawdown_auth import signed_change
from algua.registry.drawdown_store import account_state, status
from algua.risk.layered import DrawdownPolicy

risk_app = typer.Typer(help="Account risk controls", no_args_is_help=True)
app.add_typer(risk_app, name="risk")


def _broker(lane: str):
    if lane not in ("paper", "live"):
        raise ValueError("lane must be paper or live")
    return build_broker(
        BrokerKind.ALPACA_PAPER if lane == "paper" else BrokerKind.ALPACA_LIVE_DRAIN
    )


@risk_app.command("status")
@json_errors
def risk_status() -> None:
    with registry_conn() as conn:
        emit({"ok": True, "accounts": status(conn)})


@risk_app.command("configure")
@json_errors
def configure(
    lane: str,
    policy: Path = typer.Option(..., "--policy"),
    signature: Path | None = typer.Option(None, "--signature"),
) -> None:
    """Issue a human SSH challenge, or apply its signed policy; no money or allocation changes."""
    raw = read_relative_regular(policy.absolute().parent, policy.name, 64 * 1024)
    obj = json.loads(raw)
    parsed = DrawdownPolicy(**obj)
    sig = (
        read_relative_regular(signature.absolute().parent, signature.name, 64 * 1024)
        if signature
        else None
    )
    with registry_conn() as conn:
        emit(
            signed_change(
                conn, _broker(lane), lane, purpose="configure", policy=parsed, signature=sig
            )
        )


@risk_app.command("restore")
@json_errors
def restore(lane: str, signature: Path | None = typer.Option(None, "--signature")) -> None:
    """Human-only rebase after a flat settled account; old risk history remains immutable."""
    sig = (
        read_relative_regular(signature.absolute().parent, signature.name, 64 * 1024)
        if signature
        else None
    )
    with registry_conn() as conn:
        emit(
            signed_change(conn, _broker(lane), lane, purpose="restore", policy=None, signature=sig)
        )


@risk_app.command("check")
@json_errors
def check(lane: str) -> None:
    """Evaluate now. Live sells require existing verified live authority; otherwise cancel only."""
    with registry_conn() as conn:
        if account_state(conn, lane) is None:
            raise ValueError("no configured account policy")
        broker = live_check_broker(conn) if lane == "live" else _broker(lane)
        result = manage_cycle(conn, broker, lane)
        emit({"ok": bool(result and result["ready"]), "drawdown_control": result})
        if not result or not result["ready"]:
            raise typer.Exit(1)
