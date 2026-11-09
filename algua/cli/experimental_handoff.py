"""Risk-reducing paper handoff; a completed handoff supplies no live authority."""

from __future__ import annotations

from datetime import UTC, datetime

from algua.audit.log import append as audit_append
from algua.calendar.factory import get_calendar
from algua.contracts.lifecycle import Stage
from algua.execution.broker_factory import BrokerKind, build_broker
from algua.execution.dust import paper_dust
from algua.execution.flatten import flatten_strategy
from algua.execution.live_ledger import LedgerKind, owned_open_order_ids, paper_believed_positions
from algua.execution.paper_exit_drain import CANCEL_REQUESTED, PaperExitGuard
from algua.execution.venue_sync import ingest_paper_venue_keep_cursor
from algua.registry.allocations import revoke_active_locked
from algua.registry.capped_qualification import verified_qualification
from algua.registry.store import SqliteStrategyRepository


def handoff(conn, name: str) -> dict:
    repo = SqliteStrategyRepository(conn)
    rec = repo.get(name)
    if rec.stage not in (Stage.PAPER, Stage.FORWARD_TESTED):
        raise ValueError("handoff requires a paper-lane strategy")
    dep = repo.active_deployment(rec.id)
    if dep is None or dep.source_kind != "frozen":
        raise ValueError("experimental handoff requires a frozen deployment")
    q = conn.execute(
        "SELECT id FROM experimental_qualifications WHERE deployment_id=? ORDER BY id DESC LIMIT 1",
        (dep.id,),
    ).fetchone()
    if q is None:
        raise ValueError("record a passing experimental qualification before handoff")
    evidence = verified_qualification(
        conn, dep, q["id"], calendar=get_calendar(), at=datetime.now(UTC), require_fresh=True
    )
    broker = build_broker(BrokerKind.ALPACA_PAPER)
    if broker.account().account_id != evidence["paper_account_id"]:
        raise ValueError("paper account changed since qualification")
    # Persist unallocation first: a subsequent paper cycle cannot recreate this exposure.
    with conn:
        revoke_active_locked(conn, rec.id)
    guard = PaperExitGuard(conn, broker, name)
    result = flatten_strategy(
        conn,
        broker,
        name,
        LedgerKind.PAPER,
        lane="paper",
        strategy_id=rec.id,
        cancel=lambda: _scoped_cancel(conn, broker, name),
        ingest=lambda: ingest_paper_venue_keep_cursor(conn, broker, broker.clock()),
    )
    held = {
        s: q for s, q in paper_believed_positions(conn, name).items() if not paper_dust(conn, s, q)
    }
    # Pending offsets settle on a later handoff; an accepted order is not a completed exit.
    complete = False
    if result.flatten_error is None and not held:
        guard.cancel_and_ingest()
        complete = not guard.owned_open_order_ids()
    audit_append(
        conn,
        actor="agent",
        action="paper_handoff",
        strategy=name,
        reason="complete" if complete else "pending",
    )
    return {
        "ok": result.flatten_error is None,
        "strategy": name,
        "handoff_complete": complete,
        "offsets_submitted": result.n_offsets,
        "error": result.flatten_error,
        "live_authority": False,
    }


def _scoped_cancel(conn, broker, name) -> None:
    for oid in owned_open_order_ids(conn, broker, name, kind=LedgerKind.PAPER):
        audit_append(conn, actor="system", action=CANCEL_REQUESTED, strategy=name, reason=oid)
        broker.cancel_order(oid)
    ingest_paper_venue_keep_cursor(conn, broker, broker.clock())
    if owned_open_order_ids(conn, broker, name, kind=LedgerKind.PAPER):
        raise ValueError("paper handoff cancellation is still pending")
