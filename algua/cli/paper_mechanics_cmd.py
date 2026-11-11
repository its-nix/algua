"""Explicit isolated paper mechanics commands; no strategy admission or promotion authority."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

import typer

from algua.cli.app import emit
from algua.cli.errors import json_errors
from algua.config.settings import get_settings
from algua.execution.paper_mechanics import initialize, operate
from algua.execution.paper_mechanics_broker import SYMBOL, MechanicsBroker, readiness
from algua.execution.paper_mechanics_state import ledger, state
from algua.operator.paper_account_lock import paper_account_lock

mechanics_app = typer.Typer(help="Isolated USD5 paper broker smoke; zero qualification credit")


@mechanics_app.callback()
@json_errors
def mechanics_options(
    ctx: typer.Context,
    state_path: Path | None = typer.Option(None, "--state", help="Separate mechanics journal"),
    risk_db: Path | None = typer.Option(None, "--risk-db", help="Dedicated paper risk registry"),
    expected_account: str | None = typer.Option(None, "--expected-account"),
) -> None:
    if ctx.invoked_subcommand == "account":
        ctx.obj = {"expected_account": expected_account}
        return
    if state_path is None or risk_db is None or not expected_account:
        raise ValueError("--state, --risk-db and --expected-account are required")
    paths = (state_path.absolute(), risk_db.absolute())
    if (paths[0] == paths[1] or any(p.resolve() != p for p in paths)
            or (paths[0].exists() and paths[1].exists() and paths[0].samefile(paths[1]))
            or not expected_account.strip()):
        raise ValueError("distinct regular mechanics/risk paths and expected account required")
    ctx.obj = {"state_path": paths[0], "risk_db": paths[1],
               "expected_account": expected_account}


def _broker() -> MechanicsBroker:
    settings = get_settings()
    if not settings.alpaca_api_key or not settings.alpaca_api_secret:
        raise ValueError("isolated Alpaca paper credentials are not configured")
    return MechanicsBroker(settings.alpaca_api_key, settings.alpaca_api_secret,
                           base_url=settings.alpaca_paper_url)


@contextmanager
def _resources(options):
    risk_path = options["risk_db"]
    if not risk_path.is_file():
        raise ValueError("dedicated paper risk registry must already exist")
    # The immutable release precreates its existing Git operator.lock for the paper runtime user.
    with paper_account_lock("paper"):
        risk = sqlite3.connect(risk_path.as_uri() + "?mode=rw", uri=True)
        risk.row_factory = sqlite3.Row
        risk.execute("PRAGMA foreign_keys=ON")
        try:
            with ledger(options["state_path"]) as journal:
                yield journal, risk
        finally:
            risk.close()


@mechanics_app.command("account")
@json_errors
def account(ctx: typer.Context, symbol: str = typer.Option(SYMBOL, "--symbol")) -> None:
    """Read account identity and asset readiness; never create a state or submit an order."""
    emit({"ok": True, "paper_only": True, "qualification_credit": False,
          "account": readiness(_broker(), ctx.obj["expected_account"], symbol)})


@mechanics_app.command("init")
@json_errors
def init(ctx: typer.Context, symbol: str = typer.Option(SYMBOL, "--symbol")) -> None:
    """Bind one approved midcap symbol to an empty baseline and matching paper policy."""
    with _resources(ctx.obj) as (journal, risk):
        result = initialize(journal, risk, _broker(), ctx.obj["expected_account"], symbol)
    emit({"ok": True, "mechanics": result})


@mechanics_app.command("status")
@json_errors
def status(ctx: typer.Context) -> None:
    """Read the local receipt only; it is not a fresh venue reconciliation or flatness proof."""
    if not ctx.obj["state_path"].is_file():
        raise ValueError("paper mechanics journal does not exist")
    with ledger(ctx.obj["state_path"]) as journal:
        current = state(journal)
        if current["account_id"] != ctx.obj["expected_account"]:
            raise ValueError("mechanics expected account mismatch")
        intents = [dict(row) for row in journal.execute("SELECT * FROM intents")]
    emit({"ok": True, "cached": True, "mechanics": current, "intents": intents})


def _operate(ctx, action):
    with _resources(ctx.obj) as (journal, risk):
        result = operate(journal, risk, _broker(), ctx.obj["expected_account"], action)
    emit({"ok": True, "mechanics": result})


@mechanics_app.command("step")
@json_errors
def step(ctx: typer.Context) -> None:
    """Submit the single opening once, or recover/reconcile its original identity."""
    _operate(ctx, "step")


@mechanics_app.command("close")
@json_errors
def close(ctx: typer.Context) -> None:
    """Cancel only own orders, then place one guarded limit exit for verified held shares."""
    _operate(ctx, "close")
