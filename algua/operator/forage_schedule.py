"""Bounded daily refresh / empty eligible-queue refill; no qualification authority."""
from __future__ import annotations

import json
import os
import re
import stat
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from algua.operator.research_memory_checkpoint import canonical, strict_json
from algua.primitives.atomic_io import write_bytes_durable
from algua.primitives.flock import file_lock
from algua.tracking.bounded_local_read import read_local_file


def _legacy_launches(path: Path, now: datetime) -> dict[str, str]:
    """Best-effort bounded tail of the operational digest; reservations remain authoritative."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except FileNotFoundError:
        return {}
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("forage_schedule:invalid_digest")
        stream.seek(0, 2)
        offset = max(0, stream.tell() - 1024 * 1024)
        stream.seek(offset)
        lines = stream.read(1024 * 1024).splitlines()
    rows = {}
    for line in lines[1:] if offset else lines:
        try:
            stamp = json.loads(line)["stamp"]
            at = datetime.strptime(stamp, "%Y%m%d-%H%M%S").replace(tzinfo=UTC)
            if at.date() == now.date():
                # Older drivers used the host's local date; don't turn a timezone offset into
                # a permanent clock-corruption error. Count the launch conservatively.
                rows[stamp] = min(at, now).isoformat()
        except (ValueError, TypeError, KeyError, UnicodeDecodeError, RecursionError):
            continue
    return rows


def forage_due(directory: Path, *, eligible: bool, reserve: str | None = None,
               daily_limit: int = 2, now: datetime | None = None) -> dict:
    """Check cheaply; atomically reserve just before a model launch. Failed launches count.

    At most two automated launches/day by default, at least two hours apart. Refresh at 03 UTC
    even with a healthy queue; otherwise refill only when research has no eligible hypothesis.
    Legacy digests count too, so deployment cannot erase today's consumption.
    """
    if type(daily_limit) is not int or not 1 <= daily_limit <= 4:
        raise ValueError("forage_schedule:invalid_daily_limit")
    if reserve is not None and re.fullmatch(r"[0-9]{8}-[0-9]{6}", reserve) is None:
        raise ValueError("forage_schedule:invalid_cycle")
    now = now or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("forage_schedule:aware_clock_required")
    now = now.astimezone(UTC)
    if reserve is not None and not reserve.startswith(now.strftime("%Y%m%d")):
        raise ValueError("forage_schedule:cycle_day_mismatch")
    directory.mkdir(parents=True, exist_ok=True)
    with file_lock(directory / "forage-budget.lock"):
        path = directory / "forage-budget.json"
        rows: dict[str, str] = {}
        if path.exists() or path.is_symlink():
            state = strict_json(read_local_file(path, root=directory.absolute(), max_bytes=16384))
            if (not isinstance(state, dict) or set(state) != {"day", "launches"}
                    or not isinstance(state["launches"], dict) or len(state["launches"]) > 100
                    or not isinstance(state["day"], str)
                    or state["day"] > now.date().isoformat()):
                raise ValueError("forage_schedule:invalid_state")
            date.fromisoformat(state["day"])
            if state["day"] == now.date().isoformat():
                rows = state["launches"]
        for stamp, legacy_time in _legacy_launches(directory / "forage-runs.jsonl", now).items():
            rows.setdefault(stamp, legacy_time)
        times = []
        for stamp, value in rows.items():
            if (not isinstance(stamp, str) or not isinstance(value, str)
                    or re.fullmatch(r"[0-9]{8}-[0-9]{6}", stamp) is None
                    or not stamp.startswith(now.strftime("%Y%m%d"))):
                raise ValueError("forage_schedule:invalid_state")
            at = datetime.fromisoformat(value)
            if at.tzinfo is None or at > now or at.astimezone(UTC).date() != now.date():
                raise ValueError("forage_schedule:invalid_state")
            times.append(at)
        remaining = max(0, daily_limit - len(rows))
        reason = ("daily_budget_exhausted" if remaining == 0 else
                  "cooldown" if times and now - max(times) < timedelta(hours=2) else
                  "no_eligible_ideas" if not eligible else
                  "daily_refresh" if now.hour == 3 else "eligible_queue_available")
        ready = reason in {"no_eligible_ideas", "daily_refresh"}
        if reserve is not None and ready:
            if reserve in rows:
                raise ValueError("forage_schedule:duplicate_cycle")
            rows[reserve] = now.isoformat()
            write_bytes_durable(canonical({"day": now.date().isoformat(), "launches": rows}), path)
            remaining -= 1
        return {"ready": ready, "reason": reason, "remaining_daily_cycles": remaining,
                "reserved": ready and reserve is not None, "authority": "none"}
