from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from algua.execution.alpaca_broker import AlpacaPaperBroker
from algua.execution.alpaca_reductions import reduction_price
from algua.execution.errors import BrokerError
from algua.risk.layered import DrawdownPolicy


def quote():
    return {"t": datetime.now(UTC).isoformat(), "bp": "100", "ap": "100.1", "bs": 10, "as": 10}


@pytest.mark.parametrize("fault", ["old", "future", "crossed", "wide", "empty", "nan", "bool"])
def test_bad_quote_never_produces_a_limit(fault):
    raw = quote()
    if fault in ("old", "future"):
        raw["t"] = (datetime.now(UTC) + timedelta(seconds=-11 if fault == "old" else 1)).isoformat()
    elif fault == "crossed":
        raw["ap"] = "99"
    elif fault == "wide":
        raw["ap"] = "102"
    elif fault == "empty":
        raw["bs"] = 0
    elif fault == "nan":
        raw["bp"] = "NaN"
    else:
        raw["bp"] = True
    with pytest.raises(ValueError):
        reduction_price(raw, DrawdownPolicy("1000"), datetime.now(UTC))


def test_limit_price_rounds_upward_to_preserve_sell_bound():
    raw = quote() | {"bp": "100.01", "ap": "100.02"}
    bound = reduction_price(raw, DrawdownPolicy("1000"), datetime.now(UTC))
    assert bound == Decimal("99.76")


def response(payload, status=200, text=""):
    return SimpleNamespace(status_code=status, text=text, json=lambda: payload)


@pytest.mark.parametrize("fault", [None, "qty", "price", "side", "coid", "type", "tif"])
def test_duplicate_reduction_requires_exact_original_request(monkeypatch, fault):
    broker = AlpacaPaperBroker("synthetic-key", "synthetic-secret")
    order = {
        "id": "order",
        "symbol": "AAPL",
        "side": "sell",
        "type": "limit",
        "qty": "1.123456789",
        "limit_price": "99.75",
        "time_in_force": "day",
        "client_order_id": "reduction-1",
    }
    if fault:
        key = {"price": "limit_price", "coid": "client_order_id", "tif": "time_in_force"}.get(
            fault, fault
        )
        order[key] = {
            "qty": "2",
            "price": "98",
            "side": "buy",
            "coid": "wrong",
            "type": "market",
            "tif": "gtc",
        }[fault]
    monkeypatch.setattr(
        broker, "_post", lambda *args: response(None, 422, "client_order_id must be unique")
    )
    monkeypatch.setattr(broker, "get_order_by_client_order_id", lambda coid: order)
    if fault:
        with pytest.raises((BrokerError, ValueError)):
            broker.submit_reduction("AAPL", "1.1234567899", "99.75", "reduction-1")
    else:
        assert broker.submit_reduction("AAPL", "1.1234567899", "99.75", "reduction-1") == "order"


def test_limit_post_never_falls_back_to_market(monkeypatch):
    broker = AlpacaPaperBroker("synthetic-key", "synthetic-secret")
    posts = []

    def post(path, body):
        posts.append((path, body))
        return response({"id": "order", **body})

    monkeypatch.setattr(broker, "_post", post)
    assert broker.submit_reduction("AAPL", "1", "99.75", "reduction-1") == "order"
    assert posts[0][1]["type"] == "limit" and posts[0][1]["extended_hours"] is False
    assert "notional" not in posts[0][1]


def test_quote_endpoint_is_pinned_and_redirects_disabled(monkeypatch):
    import requests

    seen = []

    def get(url, **kwargs):
        seen.append((url, kwargs))
        return response({"symbol": "AAPL", "quote": quote()})

    monkeypatch.setattr(requests, "get", get)
    broker = AlpacaPaperBroker("synthetic-key", "synthetic-secret")
    broker.reduction_quote("AAPL", feed="iex")
    assert seen[0][0] == "https://data.alpaca.markets/v2/stocks/AAPL/quotes/latest"
    assert seen[0][1]["allow_redirects"] is False
    assert seen[0][1]["params"] == {"feed": "iex"}
