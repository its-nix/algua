"""Experimental activation explicitly signs qualification, frozen identity and requested capital."""

from pathlib import Path

import typer

from algua.cli.app import emit
from algua.cli.errors import json_errors
from algua.contracts.lifecycle import Actor, Stage
from algua.operator.deployment_lock import operator_transition_lock
from algua.primitives.bounded_file import read_relative_regular
from algua.registry.capped_auth import authorize
from algua.registry.capped_state import revoke
from algua.registry.db import registry_conn
from algua.registry.store import SqliteStrategyRepository

capped_live_app = typer.Typer(no_args_is_help=True)


@capped_live_app.command("activate-experimental")
@json_errors
def activate(
    name: str,
    capital: str = typer.Option(..., "--capital"),
    actor: str = typer.Option("agent", "--actor"),
    signature: Path | None = typer.Option(None, "--signature"),
) -> None:
    """Agent previews; human signs the capped frozen-live challenge. Never funds the account."""
    raw = (
        read_relative_regular(signature.absolute().parent, signature.name, 64 * 1024)
        if signature
        else None
    )
    # A handoff/live operation must exclude the paper timer even while human signing is pending.
    with operator_transition_lock(Stage.FORWARD_TESTED, Stage.LIVE), registry_conn() as conn:
        emit(authorize(conn, name, capital=capital, actor=Actor(actor), signature=raw))


@capped_live_app.command("revoke")
@json_errors
def revoke_live(name: str, reason: str = typer.Option(..., "--reason")) -> None:
    """End future experimental and legacy orders immediately; preserves all authority history."""
    if not reason.strip():
        raise ValueError("revocation requires a reason")
    with registry_conn() as conn, conn:
        rec = SqliteStrategyRepository(conn).get(name)
        revoke(conn, rec.id, reason)
        conn.execute(
            "UPDATE live_authorizations SET revoked_at=datetime('now') "
            "WHERE strategy_id=? AND revoked_at IS NULL",
            (rec.id,),
        )
    emit({"ok": True, "strategy": name, "revoked": True})
