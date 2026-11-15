"""/api/push endpoints: key shape, subscribe validation/limit, idempotent delete, owner gate."""

from __future__ import annotations

from typing import Any

import backend.main as main_mod
import httpx
import pytest
from backend import push
from py_vapid import b64urldecode

OWNER = "owner@example.com"
OWNER_HEADERS = {"Tailscale-User-Login": OWNER}


@pytest.fixture(autouse=True)
def owner_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALGUA_WEB_OWNER_LOGIN", OWNER)


def _client(headers: dict[str, str] | None = OWNER_HEADERS) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=main_mod.app)
    return httpx.AsyncClient(transport=transport, base_url="http://test", headers=headers)


def _sub(i: int = 0) -> dict[str, Any]:
    return {
        "endpoint": f"https://push.example.com/v1/{i}",
        "keys": {"p256dh": f"p256dh-{i}", "auth": f"auth-{i}"},
    }


async def test_push_key_shape() -> None:
    async with _client() as client:
        resp = await client.get("/api/push/key")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    raw = b64urldecode(body["key"].encode())
    assert len(raw) == 65 and raw[0] == 0x04  # uncompressed P-256 point


async def test_subscribe_persists() -> None:
    async with _client() as client:
        resp = await client.post("/api/push/subscribe", json=_sub())
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert _sub()["endpoint"] in push.load_subscriptions()


async def test_subscribe_invalid_is_422_invalid_param() -> None:
    async with _client() as client:
        resp = await client.post(
            "/api/push/subscribe",
            json={
                "endpoint": "http://insecure.example.com/x",
                "keys": {"p256dh": "p", "auth": "a"},
            },
        )
    assert resp.status_code == 422
    body = resp.json()
    assert body["ok"] is False
    assert body["code"] == "invalid_param"
    assert push.load_subscriptions() == {}


async def test_subscribe_non_object_body_is_422() -> None:
    async with _client() as client:
        resp = await client.post("/api/push/subscribe", json=[1, 2, 3])
    assert resp.status_code == 422
    assert resp.json()["code"] == "invalid_param"


async def test_subscribe_body_over_16k_is_422_body_too_large() -> None:
    # httpx sets Content-Length for json= bodies -> exercises the header check.
    big = _sub()
    big["padding"] = "x" * (17 * 1024)
    async with _client() as client:
        resp = await client.post("/api/push/subscribe", json=big)
    assert resp.status_code == 422
    body = resp.json()
    assert body["ok"] is False
    assert body["code"] == "invalid_param"
    assert body["error"] == "body too large"
    assert push.load_subscriptions() == {}


async def test_subscribe_chunked_oversize_body_hits_the_backstop() -> None:
    # A chunked request carries no Content-Length -> the post-read size check.
    async def chunks() -> Any:
        yield b'{"padding": "' + b"x" * (17 * 1024) + b'"}'

    async with _client() as client:
        resp = await client.post(
            "/api/push/subscribe",
            content=chunks(),
            headers={"content-type": "application/json"},
        )
    assert resp.status_code == 422
    assert resp.json()["error"] == "body too large"
    assert push.load_subscriptions() == {}


async def test_subscribe_limit_is_422_subscription_limit() -> None:
    for i in range(push.MAX_SUBSCRIPTIONS):
        push.add_subscription(_sub(i))
    async with _client() as client:
        resp = await client.post("/api/push/subscribe", json=_sub(99))
    assert resp.status_code == 422
    body = resp.json()
    assert body["ok"] is False
    assert body["code"] == "subscription_limit"


async def test_delete_is_idempotent() -> None:
    push.add_subscription(_sub())
    async with _client() as client:
        first = await client.delete(
            "/api/push/subscribe", params={"endpoint": _sub()["endpoint"]}
        )
        second = await client.delete(
            "/api/push/subscribe", params={"endpoint": _sub()["endpoint"]}
        )
    assert first.status_code == 200 and first.json() == {"ok": True}
    assert second.status_code == 200 and second.json() == {"ok": True}
    assert push.load_subscriptions() == {}


_NOT_OWNER = [
    pytest.param(None, id="no-header"),
    pytest.param({"Tailscale-User-Login": "mallory@example.com"}, id="authenticated-non-owner"),
    pytest.param({"Tailscale-User-Login": ""}, id="blank-header"),
    pytest.param({**OWNER_HEADERS, "Sec-Fetch-Site": "cross-site"}, id="owner-cross-site"),
    pytest.param({**OWNER_HEADERS, "Sec-Fetch-Site": "same-site"}, id="owner-same-site"),
]


@pytest.mark.parametrize("headers", _NOT_OWNER)
async def test_subscribe_refuses_non_owner(headers: dict[str, str] | None) -> None:
    async with _client(headers) as client:
        resp = await client.post("/api/push/subscribe", json=_sub())
    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"
    assert push.load_subscriptions() == {}


@pytest.mark.parametrize("headers", _NOT_OWNER)
async def test_unsubscribe_refuses_non_owner(headers: dict[str, str] | None) -> None:
    push.add_subscription(_sub())
    async with _client(headers) as client:
        resp = await client.delete(
            "/api/push/subscribe", params={"endpoint": _sub()["endpoint"]})
    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"
    assert _sub()["endpoint"] in push.load_subscriptions()


@pytest.mark.parametrize("env", [None, "", "   "])
async def test_push_writes_disabled_without_owner_env(
    monkeypatch: pytest.MonkeyPatch, env: str | None,
) -> None:
    if env is None:
        monkeypatch.delenv("ALGUA_WEB_OWNER_LOGIN", raising=False)
    else:
        monkeypatch.setenv("ALGUA_WEB_OWNER_LOGIN", env)
    push.add_subscription(_sub(1))
    async with _client({"Tailscale-User-Login": ""}) as client:
        sub = await client.post("/api/push/subscribe", json=_sub())
        unsub = await client.delete(
            "/api/push/subscribe", params={"endpoint": _sub(1)["endpoint"]})
    assert sub.status_code == 403 and unsub.status_code == 403
    assert list(push.load_subscriptions()) == [_sub(1)["endpoint"]]


async def test_owner_gate_runs_before_the_body_is_read() -> None:
    big = _sub()
    big["padding"] = "x" * (17 * 1024)
    async with _client({"Tailscale-User-Login": "mallory@example.com"}) as client:
        resp = await client.post("/api/push/subscribe", json=big)
    assert resp.status_code == 403  # not 422 body-too-large: refused before any read


async def test_owner_same_origin_subscribe_is_allowed() -> None:
    async with _client({**OWNER_HEADERS, "Sec-Fetch-Site": "same-origin"}) as client:
        resp = await client.post("/api/push/subscribe", json=_sub())
    assert resp.status_code == 200
    assert _sub()["endpoint"] in push.load_subscriptions()
