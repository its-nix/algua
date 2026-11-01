"""Bounded public projection of existing loop evidence; never delivers alerts or writes state."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from algua.calendar.market_calendar import MarketCalendar
from algua.operator.alerts import research_fault, research_incidents
from algua.operator.loop_health import (
    _QUEUE_TERMINAL,
    LOOPS,
    PAPER_STALE_AFTER_SESSIONS,
    _digest_stamp,
    _parse_utc,
    _read_digest_tail,
    _read_json,
    loop_status,
)

_OUTCOMES = (
    "completed", "skipped_lock", "pool_empty", "setup_failed", "claim_failed", "driver_failed",
)
_HEALTH = ("ok", "idle", "failing", "rate_limited", "stale", "unknown")


def _valid_record(record: dict, now: datetime) -> bool:
    origin = record.get("research_cycle_id", record.get("stamp"))
    stamp = _digest_stamp(record)
    if (not isinstance(origin, str) or not 1 <= len(origin) <= 128
            or stamp is None or stamp > now or record.get("outcome") not in _OUTCOMES):
        return False
    previous = None
    for key in ("started_at", "finished_at", "recorded_at"):
        if key not in record:
            continue
        instant = _parse_utc(record[key])
        if instant is None or instant > now or (previous is not None and instant < previous):
            return False
        previous = instant
    if any(type(record.get(key, False)) is not bool for key in ("timed_out", "rate_limited")):
        return False
    rc = record.get("exit_code")
    return ((rc is None and record["outcome"] != "completed")
            or (type(rc) is int and -255 <= rc <= 255))


def _paper_session(payload: Any, now: datetime, calendar: MarketCalendar) -> datetime | None:
    entry = payload.get("paper") if isinstance(payload, dict) else None
    if not isinstance(entry, dict):
        return None
    stamp = _parse_utc(entry.get("recorded_at"))
    rc = entry.get("last_rc", entry.get("rc"))
    if stamp is None or stamp > now or type(rc) is not int or not -255 <= rc <= 255:
        return None
    raw_session = entry.get("session")
    if not isinstance(raw_session, str):
        return None
    try:
        session = date.fromisoformat(raw_session)
    except ValueError:
        return None
    try:
        if not calendar.is_session(session):
            return None
        close = calendar.session_close(session)
    except Exception:  # noqa: BLE001 — invalid or unavailable exchange evidence fails closed
        return None
    return close if close <= stamp <= now else None


def _valid_queue(payload: Any, now: datetime) -> bool:
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, dict) or len(items) > 1000:
        return False
    for row in items.values():
        if not isinstance(row, dict):
            return False
        if row.get("status") not in (*_QUEUE_TERMINAL, "pending", "in_progress", "gate_failed"):
            return False
        attempts, stamp = row.get("attempts"), _parse_utc(row.get("enqueued_at"))
        if (type(attempts) is not int or not 0 <= attempts <= 1000000
                or stamp is None or stamp > now):
            return False
    return True


def machine_health(
    data_dir: Path, calendar: MarketCalendar, *, now: datetime, fixture: bool = False,
) -> dict[str, Any]:
    """Project only fixed health enums and digest-based incident lineage from retained artifacts.

    Missing/malformed evidence is unknown even where the older private view treats absence as
    idle. Explicit empty queues are known idle. Bounds never silently truncate incident history.
    """
    status = loop_status(data_dir, calendar, now=now, digest_limit=1000, strict=True)
    loops = {name: status["loops"][name]["health"] for name in LOOPS}
    loops = {name: health if health in _HEALTH else "unknown" for name, health in loops.items()}
    records, error = _read_digest_tail(data_dir / "research-runs.jsonl", 1000, strict=True)
    valid = [record for record in records if _valid_record(record, now)]
    if error or not records or len(valid) != len(records):
        loops["research"] = "unknown"
    elif research_fault(records[-1]) is not None:
        loops["research"] = "rate_limited" if records[-1].get("rate_limited") else "failing"
    paper, _ = _read_json(data_dir / "operator_sessions.json", bounded=True)
    session = _paper_session(paper, now, calendar)
    if session is None:
        loops["paper"] = "unknown"
    else:
        try:
            if (session < now and calendar.sessions_between_instants(session, now)
                    > PAPER_STALE_AFTER_SESSIONS):
                loops["paper"] = "stale"
        except Exception:  # noqa: BLE001 — unavailable calendar evidence is never healthy
            loops["paper"] = "unknown"
    queue, _ = _read_json(data_dir / "mergeback-queue.json", bounded=True)
    if not _valid_queue(queue, now):
        loops["mergeback"] = "unknown"
    incidents = research_incidents(valid, now=now)
    return {"ok": all(h in ("ok", "idle") for h in loops.values()) and not incidents,
            "schema": "machine-health/v1",
            "checked_at": now.isoformat(), "evidence_mode": "FIXTURE" if fixture else "OBSERVED",
            "loops": loops, "incidents": incidents}
