"""Pure operation-loop push diff using the existing ``ops status`` verdicts.

No wall-clock/session inference belongs here: the CLI owns cadence and idle semantics.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

_RENOTIFY_AFTER_S = 24 * 60 * 60.0
_LOOPS = ("research", "paper", "mergeback")
_ALERTING = frozenset({"failing", "rate_limited", "stale", "unknown"})
_KNOWN_HEALTHS = _ALERTING | {"ok", "idle"}


def cooldown_active(last_bad_notified_at: Any, now: datetime) -> bool:
    """True when ANY bad-health notification for this subject landed within 24h (R3).

    The cooldown is deliberately independent of WHICH bad health was notified —
    keying on the exact health let a stale<->drift flap notify every cycle.
    """
    if last_bad_notified_at is None:
        return False
    try:
        at = datetime.fromisoformat(str(last_bad_notified_at))
    except ValueError:
        return False  # corrupt marker -> notify rather than stay silent
    return (now - at).total_seconds() < _RENOTIFY_AFTER_S


def diff_operations(
    payload: dict[str, Any], state: dict[str, Any] | None, *, now: datetime
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Baseline each loop, then alert with an accepted-send-only 24h cooldown.

    Invalid payloads fail without touching prior observations or delivery marks.
    Idle is quiet; failed sends retry; recovery clears only that loop's cooldown.
    Fleet state and other independent source state survive this update unchanged.
    """
    loops = payload.get("loops")
    if not isinstance(loops, dict) or any(
        not isinstance(loops.get(name), dict)
        or loops[name].get("health") not in _KNOWN_HEALTHS
        for name in _LOOPS
    ):
        raise ValueError("invalid ops status loop health payload")
    previous = (state or {}).get("operations") or {}
    observed: dict[str, Any] = {}
    notifications: list[dict[str, Any]] = []
    for name in _LOOPS:
        row = loops[name]
        health = row["health"]
        prev = previous.get(name)
        last_bad = prev.get("last_bad_notified_at") if isinstance(prev, dict) else None
        if health not in _ALERTING:
            last_bad = None
        elif isinstance(prev, dict) and not cooldown_active(last_bad, now):
            notifications.append({
                "kind": "operation",
                "loop": name,
                "urgency": "normal",
                "payload": {
                    "title": f"{name} loop {health.replace('_', ' ')}",
                    "body": row.get("detail") or f"{name} loop health: {health}",
                    "tag": f"operation:{name}",
                    "url": "/research" if name in ("research", "mergeback") else "/fleet",
                    "renotify": True,
                },
            })
        observed[name] = {
            "observed_health": health,
            "observed_at": now.isoformat(),
            "last_bad_notified_at": last_bad,
        }
    return notifications, {**(state or {}), "operations": observed}
