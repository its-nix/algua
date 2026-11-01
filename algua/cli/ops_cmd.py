"""`algua ops status` and `algua book status` — the two read-only surfaces the monitor's triage
screen is built on (spec: 2026-08-15-monitor-dashboard-redesign).

Both are pure reads: no broker call, no writes, no locks. Thin command bodies — the rollup logic
lives in ``algua.operator.loop_health`` and ``algua.execution.book`` so it is unit-testable without
a CLI, matching the domain-extraction convention (#165).
"""

from __future__ import annotations

from datetime import UTC, datetime

import typer
from typer._click.core import Context
from typer._click.exceptions import UsageError
from typer.core import TyperCommand

from algua.calendar.factory import get_calendar
from algua.cli._common import ok
from algua.cli.app import app, emit
from algua.cli.errors import json_errors
from algua.config.settings import get_settings
from algua.execution.book import book_status
from algua.operator.loop_health import loop_status
from algua.operator.machine_health import machine_health
from algua.registry.db import registry_conn

ops_app = typer.Typer(help="Machine liveness: are the autonomous loops still running?",
                      no_args_is_help=True)
book_app = typer.Typer(help="Book capital: who holds a slice, and who should but doesn't",
                       no_args_is_help=True)
app.add_typer(ops_app, name="ops")
app.add_typer(book_app, name="book")


def _machine_health_error() -> None:
    emit({"ok": False, "error": "machine_health_unavailable",
          "code": "machine_health_unavailable", "retryable": False})


class _MachineHealthCommand(TyperCommand):
    """Keep arbitrary argv out of this public command's pre-callback error envelope."""

    def parse_args(self, ctx: Context, args: list[str]) -> list[str]:
        try:
            return super().parse_args(ctx, args)
        except UsageError:
            _machine_health_error()
            raise typer.Exit(1) from None


@ops_app.command("status")
@json_errors
def ops_status() -> None:
    """Liveness of every autonomous loop (research / paper / merge-back), worst-first.

    Answers the question the fleet rollup structurally CANNOT: a dead research loop produces no
    strategy rows to be unhealthy about, so ``fleet health`` stays green while the top of the funnel
    is stopped. Reads only the durable artifacts the loops already write — never systemd.

    Exits 0 always: this is an operator VIEW, not a watchdog gate (``fleet health`` is the gate).
    ``ok: false`` in the payload carries the verdict.
    """
    settings = get_settings()
    emit(ok(loop_status(settings.data_dir, get_calendar(), now=datetime.now(UTC))))


@ops_app.command("machine-health", cls=_MachineHealthCommand)
def machine_health_cmd(
    now: str | None = typer.Option(None, help="Aware ISO instant for evidence replay."),
    fixture: bool = typer.Option(False, help="Label disposable evidence FIXTURE."),
) -> None:
    """Public aggregate health and engineering incidents. Pure read; exits 1 unless healthy."""
    try:
        instant = datetime.now(UTC) if now is None else datetime.fromisoformat(now)
        if instant.tzinfo is None:
            raise ValueError("aware instant required")
        payload = machine_health(get_settings().data_dir, get_calendar(),
                                 now=instant.astimezone(UTC), fixture=fixture)
    except Exception:  # noqa: BLE001 — this public boundary must never echo raw exception text
        _machine_health_error()
        raise typer.Exit(1) from None
    emit(payload)
    if not payload["ok"]:
        raise typer.Exit(1)


@book_app.command("status")
@json_errors
def book_status_cmd() -> None:
    """Active capital slices, plus every operational strategy holding NO slice.

    An operational strategy without an allocation is skipped by the operator loop forever and
    surfaces only as an unexplained ``idle`` — the standing condition that stranded
    ``liquidity_stable_quality_momentum`` after a `dormant` round-trip.

    Capital headroom is deliberately absent: it needs the account equity, and the only path to that
    is a broker call this view must not make. Count headroom is reported instead.
    """
    with registry_conn() as conn:
        payload = book_status(conn, capacity=get_settings().paper_book_capacity)
    emit(ok(payload))
