"""Fresh quotes and exact-identity limit sells for guarded long-position reductions."""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any
from urllib.parse import quote

import requests

from algua.contracts.net import require_https_allowlisted_host
from algua.execution.alpaca_rejections import is_duplicate_client_order_id
from algua.execution.errors import BrokerError
from algua.risk.layered import DrawdownPolicy, decimal


def reduction_price(raw: dict, policy: DrawdownPolicy, now: datetime) -> Decimal:
    bid, ask = decimal(raw.get("bp")), decimal(raw.get("ap"))
    stamp = datetime.fromisoformat(raw["t"])
    if (
        stamp.tzinfo is None
        or now.tzinfo is None
        or bid <= 0
        or ask < bid
        or decimal(raw.get("bs")) <= 0
        or decimal(raw.get("as")) <= 0
        or not 0 <= (now - stamp).total_seconds() <= float(policy.quote_age_seconds)
        or (ask - bid) / bid > decimal(policy.max_spread)
    ):
        raise ValueError("quote is stale, crossed, empty or too wide")
    if bid < 1:
        raise ValueError("sub-dollar controlled exits require a separately reviewed price tick")
    return (bid * (1 - decimal(policy.limit_offset))).quantize(
        Decimal(".01"), rounding=ROUND_CEILING
    )


class ReductionOrders:
    """Mixin uses only the broker's existing authenticated, host-checked transport."""

    def regular_market_open(self: Any) -> bool:
        raw = self._read(self._get("/v2/clock"), "/v2/clock")
        return isinstance(raw, dict) and raw.get("is_open") is True

    def reduction_quote(self: Any, symbol: str, *, feed: str) -> dict:
        if feed not in ("iex", "sip"):
            raise BrokerError("unsupported quote feed")
        url = "https://data.alpaca.markets/v2/stocks/" + quote(symbol, safe="") + "/quotes/latest"
        require_https_allowlisted_host(url, frozenset({"data.alpaca.markets"}))
        try:
            response = requests.get(
                url,
                params={"feed": feed},
                headers=self._headers(),
                timeout=10,
                allow_redirects=False,
            )
            raw = self._read(response, "latest stock quote")
            if not isinstance(raw, dict) or raw.get("symbol") != symbol:
                raise ValueError("quote symbol mismatch")
            return raw["quote"]
        except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
            raise BrokerError("could not read a verified latest quote") from exc

    def submit_reduction(self: Any, symbol: str, qty: str, limit_price: str, coid: str) -> str:
        count, price = (
            decimal(qty).quantize(Decimal("1e-9"), rounding=ROUND_FLOOR),
            decimal(limit_price),
        )
        if count <= 0 or price <= 0 or not coid or len(coid) > 128:
            raise BrokerError("invalid guarded reduction order")
        body = {
            "symbol": symbol,
            "qty": format(count, "f"),
            "side": "sell",
            "type": "limit",
            "limit_price": format(price, "f"),
            "time_in_force": "day",
            "client_order_id": coid,
            "extended_hours": False,
        }
        response = self._post("/v2/orders", body)
        if is_duplicate_client_order_id(response.status_code, response.text):
            raw = self.get_order_by_client_order_id(coid)
        else:
            raw = self._read(response, "guarded reduction", ok=(200, 201))
        if (
            not isinstance(raw, dict)
            or raw.get("client_order_id") != coid
            or raw.get("symbol") != symbol
            or raw.get("side") != "sell"
            or raw.get("type") != "limit"
            or raw.get("time_in_force") != "day"
            or decimal(raw.get("qty")) != count
            or decimal(raw.get("limit_price")) != price
            or str(raw.get("status", "")).lower()
            in {"rejected", "canceled", "cancelled", "expired", "replaced"}
            or not isinstance(raw.get("id"), str)
            or not raw["id"]
        ):
            raise BrokerError("reduction response does not match the exact submitted order")
        return raw["id"]
