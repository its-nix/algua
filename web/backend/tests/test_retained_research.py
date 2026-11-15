"""In-process route forwarding only; no sockets or actual CLI processes."""
from __future__ import annotations

import backend.main as main
import httpx
import pytest


async def test_fixed_retained_read_forwarders(monkeypatch):
    calls = []

    async def fake(*args, **kwargs):
        calls.append(args)
        return {"ok": True, "data": {"fixture": True}, "stale": False}

    monkeypatch.setattr(main, "run_cli", fake)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                                base_url="http://test") as client:
        index = await client.get("/api/research-memory?limit=3")
        detail = await client.get("/api/research-memory/cycle-1")
    assert index.status_code == detail.status_code == 200
    assert calls == [("research", "memory", "list", "--limit=3"),
                     ("research", "memory", "show", "--run=cycle-1")]


@pytest.mark.parametrize("url", ["/api/research-memory?limit=0",
                                  "/api/research-memory?limit=101",
                                  "/api/research-memory/--help",
                                  "/api/research-memory/invalid.dot"])
async def test_bad_bounds_or_cycle_shape_never_reaches_cli(monkeypatch, url):
    async def forbidden(*args, **kwargs):
        pytest.fail("invalid retained read reached CLI")

    monkeypatch.setattr(main, "run_cli", forbidden)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                                base_url="http://test") as client:
        result = await client.get(url)
    assert result.status_code == 422 and result.json()["ok"] is False
