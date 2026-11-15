"""Operations alerts do not depend on registered strategies or successful delivery."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from backend import poller, push
from backend.poller_ops import diff_operations

NOW = datetime(2026, 11, 15, tzinfo=UTC)


def _ops(health: str = "ok") -> dict[str, Any]:
    return {"loops": {"research": {"health": health, "detail": "research detail"},
                      "paper": {"health": "idle"}, "mergeback": {"health": "idle"}}}


def _baseline(health: str = "ok") -> dict[str, Any]:
    notifications, state = diff_operations(_ops(health), None, now=NOW)
    assert notifications == []
    return state


@pytest.mark.parametrize("health", ["failing", "rate_limited", "stale", "unknown"])
@pytest.mark.parametrize("loop", ["research", "paper", "mergeback"])
def test_loop_alerts_without_any_strategies(health: str, loop: str) -> None:
    payload = _ops()
    payload["loops"][loop] = {"health": health, "detail": "loop detail"}
    notes, state = diff_operations(payload, _baseline(), now=NOW)
    assert len(notes) == 1
    assert notes[0]["payload"] == {
        "title": f"{loop} loop {health.replace('_', ' ')}", "body": "loop detail",
        "tag": f"operation:{loop}",
        "url": "/research" if loop in ("research", "mergeback") else "/fleet",
        "renotify": True}
    assert state["operations"][loop]["last_bad_notified_at"] is None


@pytest.mark.parametrize("health", ["ok", "idle"])
def test_idle_and_ok_are_quiet(health: str) -> None:
    assert diff_operations(_ops(health), _baseline("failing"), now=NOW)[0] == []


def test_first_observation_is_baseline_even_with_existing_fleet_state() -> None:
    notes, state = diff_operations(_ops("failing"), {"strategies": {}}, now=NOW)
    assert notes == []
    assert state["strategies"] == {}
    assert _baseline("failing")["operations"]["research"]["observed_health"] == "failing"


def test_failed_send_retries_cross_verdict_cooldown_daily_repeat_and_recovery() -> None:
    notes, state = diff_operations(_ops("failing"), _baseline(), now=NOW)
    retry, state = diff_operations(_ops("failing"), state, now=NOW)
    assert retry == notes
    poller.mark_notified(state, notes[0], NOW.isoformat())
    assert diff_operations(_ops("stale"), state, now=NOW + timedelta(hours=23))[0] == []
    assert len(diff_operations(_ops("stale"), state, now=NOW + timedelta(hours=25))[0]) == 1
    _, state = diff_operations(_ops("idle"), state, now=NOW + timedelta(hours=1))
    assert len(diff_operations(_ops("failing"), state, now=NOW + timedelta(hours=2))[0]) == 1


def test_sources_preserve_each_others_state() -> None:
    state = _baseline()
    _, state = poller.diff_fleet({"rows": []}, state, now=NOW)
    assert "operations" in state
    _, updated = diff_operations(_ops("stale"), state, now=NOW)
    assert updated["strategies"] == state["strategies"]
    assert updated["global_halt"] == state["global_halt"]


@pytest.mark.parametrize("bad", [{}, {"loops": {}}, {"loops": {"research": {"health": "bogus"}}}])
def test_malformed_health_does_not_change_state(bad: dict[str, Any]) -> None:
    state = _baseline()
    before = repr(state)
    with pytest.raises(ValueError, match="invalid ops status"):
        diff_operations(bad, state, now=NOW)
    assert repr(state) == before


async def test_delivery_marks_only_accepted_sends(monkeypatch: pytest.MonkeyPatch) -> None:
    push.save_notify_state(_baseline())
    sends: list[dict[str, Any]] = []
    accepted = 0

    async def send(payload: dict[str, Any], *, urgency: str) -> int:
        sends.append(payload)
        return accepted

    monkeypatch.setattr(push, "send_to_all", send)
    await poller._diff_and_notify(_ops("failing"), operations=True)
    await poller._diff_and_notify(_ops("failing"), operations=True)
    assert len(sends) == 2
    accepted = 1
    await poller._diff_and_notify(_ops("failing"), operations=True)
    await poller._diff_and_notify(_ops("stale"), operations=True)
    assert len(sends) == 3
    assert push.load_notify_state()["operations"]["research"]["last_bad_notified_at"]


@pytest.mark.parametrize("failure", [None, "stale", "cli", "unexpected"])
async def test_ops_freshness_and_failure_isolation(
    monkeypatch: pytest.MonkeyPatch, failure: str | None,
) -> None:
    import asyncio
    import contextlib

    from backend.algua_cli import CliError

    monkeypatch.setenv("ALGUA_WEB_POLL_SECONDS", "0.01")
    diffed: list[bool] = []
    calls = 0

    async def run(*args: str, **kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if args == ("ops", "status"):
            if failure == "cli":
                raise CliError("cli_timeout", "ops timeout")
            if failure == "unexpected":
                raise RuntimeError("ops failed")
            return {"data": _ops("failing"), "stale": failure == "stale"}
        return {"data": {"rows": []}, "stale": False}

    async def diff(payload: dict[str, Any], *, operations: bool = False) -> None:
        diffed.append(operations)

    monkeypatch.setattr(poller, "run_cli", run)
    monkeypatch.setattr(poller, "_diff_and_notify", diff)
    task = asyncio.create_task(poller.poll_loop())
    try:
        for _ in range(100):
            if calls >= 6:
                break
            await asyncio.sleep(0.01)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    assert calls >= 6
    assert diffed.count(False) >= 2  # fleet remains fresh regardless of ops failure
    assert (True in diffed) == (failure is None)


async def test_malformed_payload_preserves_durable_observations() -> None:
    initial = _baseline("failing")
    push.save_notify_state(initial)
    with pytest.raises(ValueError, match="invalid ops status"):
        await poller._diff_and_notify({"loops": {}}, operations=True)
    assert push.load_notify_state() == initial
