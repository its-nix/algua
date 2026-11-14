"""Reconciled, attributed long reductions. Accepted orders are not reported as filled exits."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_FLOOR, Decimal
from uuid import uuid4

import pandas as pd

from algua.execution import live_reconcile, paper_reconcile
from algua.execution.alpaca_broker import AlpacaLiveDrainBroker
from algua.execution.alpaca_reductions import reduction_price
from algua.execution.live_ledger import (
    LedgerKind,
    backfill_broker_order_id,
    backfill_paper_venue_broker_order_id,
    believed_positions,
    fill_cursor,
    ingest_activities,
    paper_believed_positions,
    record_live_order,
    record_paper_venue_order,
)
from algua.execution.live_sizing import build_sizing_snapshot
from algua.execution.venue_sync import ingest_paper_venue, recover_stranded
from algua.registry.allocations import active_allocation
from algua.registry.drawdown_store import account_state
from algua.registry.live_gate import authorization_active
from algua.risk import global_halt
from algua.risk.layered import DrawdownPolicy, decimal


def synchronize(conn, broker, lane: str):
    kind = LedgerKind(lane)
    if kind is LedgerKind.PAPER:
        ingest_paper_venue(conn, broker, broker.clock())
    else:
        ingest_activities(conn, broker.account_activities(after=fill_cursor(conn, kind)), kind)
    recover_stranded(conn, broker, kind)
    snapshot = broker.snapshot([])
    net = {s: float(q) for s, q in snapshot.qtys.items() if decimal(q) != 0}
    reconcile = paper_reconcile if lane == "paper" else live_reconcile
    result = reconcile.reconcile(conn, net, reconcile.next_cycle(conn))
    if not result.clean:
        raise ValueError("account reconciliation is pending or mismatched")
    if any(decimal(q) < 0 for q in snapshot.qtys.values()):
        raise ValueError("short holdings require human review")
    quarantine = (
        "paper_venue_activity_quarantine" if lane == "paper" else "live_activity_quarantine"
    )
    # Quarantine is unresolved evidence, not an ingest success. No automatic waiver on resume.
    if conn.execute(f"SELECT 1 FROM {quarantine} LIMIT 1").fetchone():
        raise ValueError("account activity quarantine requires resolution")
    return snapshot


def owned_book(conn, lane: str, snapshot) -> list[dict]:
    owners = []
    aggregate: dict[str, Decimal] = {}
    for rec in conn.execute("SELECT id,name FROM strategies ORDER BY id").fetchall():
        raw_held = (
            paper_believed_positions(conn, rec["name"])
            if lane == "paper"
            else believed_positions(conn, rec["name"], LedgerKind.LIVE)
        )
        held = {s: decimal(q) for s, q in raw_held.items() if decimal(q) != 0}
        if not held:
            continue
        if any(q < 0 for q in held.values()):
            raise ValueError("offsetting strategy shorts require human review")
        gross = Decimal(0)
        for symbol, qty in held.items():
            total = decimal(snapshot.qtys.get(symbol, 0))
            mark = decimal(snapshot.market_values.get(symbol, 0))
            if total <= 0 or mark <= 0:
                raise ValueError("unusable broker position valuation")
            gross += qty * mark / total
            aggregate[symbol] = aggregate.get(symbol, Decimal(0)) + qty
        allocation = active_allocation(conn, rec["id"])
        capital = decimal(allocation["capital"]) if allocation else Decimal(0)
        # A risk-only current mark view; these rows never enter a strategy's feature inputs.
        marks = pd.DataFrame(
            [
                {
                    "symbol": symbol,
                    "close": float(
                        decimal(snapshot.market_values[symbol]) / decimal(snapshot.qtys[symbol])
                    ),
                }
                for symbol in held
            ]
        )
        sizing, _nav = build_sizing_snapshot(
            conn, rec["name"], float(capital), marks, list(held), kind=LedgerKind(lane)
        )
        owners.append(
            {
                "name": rec["name"],
                "id": rec["id"],
                "held": held,
                "gross": gross,
                "capital": max(Decimal(0), decimal(sizing.equity)),
            }
        )
    if any(
        abs(aggregate.get(s, Decimal(0)) - decimal(q)) > Decimal("0.000001")
        for s, q in snapshot.qtys.items()
    ):
        raise ValueError("broker holdings are not fully attributed")
    return owners


def _require_reduction_authority(conn, broker, state) -> None:
    lane = state["lane"]
    current = account_state(conn, lane)
    if (
        current != state
        or global_halt.is_engaged(conn)
        or not 0
        <= (datetime.now(UTC) - datetime.fromisoformat(state["observed_at"])).total_seconds()
        <= 120
    ):
        raise ValueError("drawdown policy or halt changed before reduction submit")
    if lane == "live":
        authorization = getattr(broker, "authorization", None)
        if authorization is None or not authorization_active(conn, authorization):
            raise ValueError("live authorization revoked before reduction submit")


def _abandon_prepared(conn, lane: str, coid: str) -> None:
    # The persisted phase proves this process never reached a venue POST for this identity.
    table = "paper_venue_orders" if lane == "paper" else "live_orders"
    with conn:
        conn.execute(
            f"DELETE FROM {table} WHERE client_order_id=? AND broker_order_id IS NULL", (coid,)
        )
        conn.execute(
            "UPDATE drawdown_reductions SET phase='not_submitted' "
            "WHERE client_order_id=? AND phase='prepared'",
            (coid,),
        )


def _record_and_send(
    conn, broker, state, owner: dict, symbol: str, qty: Decimal, limit: Decimal
) -> None:
    lane = state["lane"]
    _require_reduction_authority(conn, broker, state)
    stamp = datetime.now(UTC).isoformat()
    coid = f"algua-dd-{lane}-{uuid4().hex}"
    with conn:
        rid = conn.execute(
            "INSERT INTO drawdown_reductions "
            "(lane,account_id,policy_id,strategy,symbol,qty,limit_price,"
            "client_order_id,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                lane,
                state["account_id"],
                state["policy_id"],
                owner["name"],
                symbol,
                str(qty),
                str(limit),
                coid,
                stamp,
            ),
        ).lastrowid
    if lane == "paper":
        record_paper_venue_order(
            conn, owner["name"], symbol, "sell", None, coid, strategy_id=owner["id"]
        )
    else:
        record_live_order(conn, owner["name"], symbol, "sell", None, coid)
    try:
        _require_reduction_authority(conn, broker, state)
    except Exception:
        _abandon_prepared(conn, lane, coid)
        raise
    with conn:
        conn.execute("UPDATE drawdown_reductions SET phase='submitting' WHERE id=?", (rid,))
    oid = broker.submit_reduction(symbol, str(qty), str(limit), coid)
    (backfill_paper_venue_broker_order_id if lane == "paper" else backfill_broker_order_id)(
        conn, coid, oid
    )
    with conn:
        conn.execute(
            "UPDATE drawdown_reductions SET broker_order_id=?,phase='sent' WHERE id=?", (oid, rid)
        )


def recover_reductions(conn, broker, state) -> None:
    """Resolve uncertain submits by their original exact request; never invent a fresh identity."""
    rows = conn.execute(
        "SELECT * FROM drawdown_reductions WHERE lane=? AND account_id=? "
        "AND broker_order_id IS NULL AND phase IN ('prepared','submitting') ORDER BY id",
        (state["lane"], state["account_id"]),
    ).fetchall()
    for row in rows:
        if row["phase"] == "prepared":
            _abandon_prepared(conn, state["lane"], row["client_order_id"])
            continue
        if state["lane"] == "paper":
            owner = conn.execute(
                "SELECT id FROM strategies WHERE name=?", (row["strategy"],)
            ).fetchone()
            if owner is None:
                raise ValueError("reduction owner missing")
            record_paper_venue_order(
                conn,
                row["strategy"],
                row["symbol"],
                "sell",
                None,
                row["client_order_id"],
                strategy_id=owner["id"],
            )
        else:
            record_live_order(
                conn, row["strategy"], row["symbol"], "sell", None, row["client_order_id"]
            )
        existing = broker.get_order_by_client_order_id(row["client_order_id"])
        if existing is None:
            # Unknown acceptance is not proof of rejection. Retain intent and pause for review.
            raise ValueError("reduction acceptance unresolved; no replacement order submitted")
        if (
            existing.get("symbol") != row["symbol"]
            or existing.get("side") != "sell"
            or existing.get("type") != "limit"
            or existing.get("time_in_force") != "day"
            or existing.get("client_order_id") != row["client_order_id"]
            or decimal(existing.get("qty")) != decimal(row["qty"])
            or decimal(existing.get("limit_price")) != decimal(row["limit_price"])
            or not isinstance(existing.get("id"), str)
            or not existing["id"]
        ):
            raise ValueError("recovered reduction identity mismatch")
        backfill = (
            backfill_paper_venue_broker_order_id
            if state["lane"] == "paper"
            else backfill_broker_order_id
        )
        backfill(conn, row["client_order_id"], existing["id"])
        with conn:
            conn.execute(
                "UPDATE drawdown_reductions SET broker_order_id=?,phase='sent' WHERE id=?",
                (existing["id"], row["id"]),
            )


def reduce_book(
    conn, broker, state, policy: DrawdownPolicy, fraction: Decimal, snapshot, owners: list[dict]
) -> int:
    gross = sum((owner["gross"] for owner in owners), Decimal(0))
    cap = min(decimal(policy.normal_capital) * fraction, decimal(state["last_equity"]))
    global_ratio = min(Decimal(1), cap / gross) if gross else Decimal(1)
    targets = []
    for owner in owners:
        ratio = min(global_ratio, owner["capital"] * fraction / owner["gross"], Decimal(1))
        for symbol, qty in owner["held"].items():
            reduction = (qty * (1 - ratio)).quantize(Decimal("1e-9"), rounding=ROUND_FLOOR)
            if reduction > 0:
                targets.append((owner, symbol, reduction))
    if not targets:
        return 0
    if isinstance(broker, AlpacaLiveDrainBroker):
        raise ValueError("controlled exit requires an existing authorized live run-all broker")
    if not broker.regular_market_open():
        raise ValueError("market closed; risk reduction remains pending")
    # Validate every quote before submitting any leg. The limit remains bound if a later leg fails.
    quotes = {s: broker.reduction_quote(s, feed=policy.feed) for _, s, _ in targets}
    for raw in quotes.values():
        reduction_price(raw, policy, datetime.now(UTC))
    for owner, symbol, qty in targets:
        if not broker.regular_market_open():
            raise ValueError("market closed during reduction")
        held = decimal(broker.get_positions().get(symbol, 0))
        if qty > held or qty > owner["held"][symbol]:
            raise ValueError("held quantity changed before reduction")
        _record_and_send(
            conn,
            broker,
            state,
            owner,
            symbol,
            qty,
            reduction_price(quotes[symbol], policy, datetime.now(UTC)),
        )
    return len(targets)
