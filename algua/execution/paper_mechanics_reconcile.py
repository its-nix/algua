"""Exact own-order recovery and a fill-only ledger; unknown venue activity always refuses."""
from __future__ import annotations

import json
from decimal import Decimal

from algua.execution.paper_mechanics_state import event
from algua.risk.layered import decimal

TERMINAL = frozenset({"filled", "canceled", "cancelled", "expired", "rejected"})
_PENDING = frozenset({"new", "accepted", "pending_new", "partially_filled", "pending_cancel"})


def _recover_rows(conn, broker, current: dict, rows) -> dict[str, dict]:
    orders = {}
    for row in rows:
        raw = broker.get_order_by_client_order_id(row["client_order_id"])
        if raw is None:
            raise ValueError("original mechanics intent acceptance is unresolved; no resubmission")
        request = json.loads(row["request"])
        if (raw.get("client_order_id") != row["client_order_id"]
                or raw.get("symbol") != current["symbol"] or raw.get("side") != row["kind"]
                or not isinstance(raw.get("id"), str) or not raw["id"]
                or raw.get("type") != request["type"] or raw.get("time_in_force") != "day"
                or raw.get("status") not in TERMINAL | _PENDING
                or (row["broker_order_id"] and raw["id"] != row["broker_order_id"])):
            raise ValueError("recovered mechanics order identity/status mismatch")
        key = "notional" if row["kind"] == "buy" else "qty"
        if decimal(raw.get(key)) != decimal(request[key]):
            raise ValueError("recovered mechanics order amount mismatch")
        if row["kind"] == "sell" and decimal(raw.get("limit_price")) != decimal(
                request["limit_price"]):
            raise ValueError("recovered mechanics exit price mismatch")
        filled = decimal(raw.get("filled_qty"))
        prior = json.loads(row["response"]) if row["response"] else {}
        if filled < 0 or filled < decimal(prior.get("filled_qty", 0)):
            raise ValueError("mechanics filled quantity decreased")
        with conn:
            conn.execute("UPDATE intents SET broker_order_id=?,response=? WHERE kind=?",
                         (raw["id"], json.dumps(raw, sort_keys=True), row["kind"]))
            event(conn, "order_observed", raw)
        orders[row["kind"]] = raw
    return orders


def recover_opening(conn, broker, current: dict) -> dict | None:
    """Verify just the original opening identity, even when exclusive-account checks cannot pass."""
    rows = conn.execute("SELECT * FROM intents WHERE kind='buy'").fetchall()
    return _recover_rows(conn, broker, current, rows).get("buy")


def recover(conn, broker, current: dict) -> dict[str, dict]:
    rows = conn.execute("SELECT * FROM intents").fetchall()
    orders = _recover_rows(conn, broker, current, rows)
    for raw in broker.list_open_orders():
        if not any(raw.get("id") == o["id"] and raw.get("client_order_id") ==
                   o["client_order_id"] for o in orders.values()):
            raise ValueError("unexpected open order in isolated mechanics account")
    return orders


def reconcile(conn, broker, current: dict, orders: dict[str, dict]) -> Decimal:
    activities = broker.account_activities_window(current["started_at"], broker.clock())
    if not isinstance(activities, list):
        raise ValueError("mechanics activity history unavailable")
    seen, totals, spend = set(), {"buy": Decimal(0), "sell": Decimal(0)}, Decimal(0)
    by_id = {o["id"]: o for o in orders.values()}
    for row in activities:
        if (not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]
                or row.get("activity_type") != "FILL" or row.get("order_id") not in by_id
                or row.get("symbol") != current["symbol"]
                or row.get("side") != by_id[row["order_id"]]["side"]):
            raise ValueError("unexpected or unattributed mechanics account activity")
        aid, payload = row["id"], json.dumps(row, sort_keys=True)
        prior = conn.execute("SELECT payload FROM fills WHERE id=?", (aid,)).fetchone()
        if prior and prior[0] != payload:
            raise ValueError("mechanics activity changed after recording")
        qty, price = decimal(row.get("qty")), decimal(row.get("price"))
        if qty <= 0 or price <= 0:
            raise ValueError("invalid mechanics fill quantity/price")
        if aid not in seen:
            totals[row["side"]] += qty
            if row["side"] == "buy":
                spend += qty * price
        seen.add(aid)
        with conn:
            if not prior:
                conn.execute("INSERT INTO fills VALUES (?,?)", (aid, payload))
                event(conn, "fill", row)
    if any(row[0] not in seen for row in conn.execute("SELECT id FROM fills")):
        raise ValueError("mechanics activity history disappeared")
    if spend > 5 or totals["sell"] > totals["buy"]:
        raise ValueError("mechanics cumulative purchase cap or long-only bound exceeded")
    for side, raw in orders.items():
        if totals[side] != decimal(raw["filled_qty"]):
            raise ValueError("mechanics fill publication is incomplete; wait for reconciliation")
    positions = broker.get_positions()
    if any(symbol != current["symbol"] or decimal(qty) < 0
           for symbol, qty in positions.items() if decimal(qty) != 0):
        raise ValueError("unexpected holdings or short position in mechanics account")
    held = decimal(positions.get(current["symbol"], 0))
    if abs(held - (totals["buy"] - totals["sell"])) > Decimal("1e-9"):
        raise ValueError("mechanics fill ledger does not reconcile to actual holdings")
    return min(held, totals["buy"] - totals["sell"])
