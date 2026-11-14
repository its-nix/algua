"""Value each cash activity once; timing ambiguity, transfers and feed rewrites fail closed."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from algua.calendar.factory import get_calendar
from algua.contracts.canonical import canonical_json
from algua.registry.forward_evidence import EXTERNAL_CAPITAL_TYPES
from algua.risk.layered import decimal

_RETURNS = frozenset(
    {
        "FILL",
        "DIV",
        "DIVFEE",
        "DIVNRA",
        "DIVCGL",
        "DIVCGS",
        "DIVROC",
        "DIVTXEX",
        "INT",
        "INTNRA",
        "INTTW",
        "FEE",
        "CFEE",
        "PTC",
        "CGD",
    }
)
_CASH = EXTERNAL_CAPITAL_TYPES - {"ACATS", "JNLS"}


def previous_close(now: datetime) -> datetime:
    calendar = get_calendar()
    session = calendar.session_on_or_before(now.date())
    prior = calendar.previous_session(session) if session == now.date() else session
    return calendar.session_close(prior)


def fingerprints(activities: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in activities:
        aid = row.get("id") if isinstance(row, dict) else None
        if not isinstance(aid, str) or not aid:
            raise ValueError("activity identity unavailable")
        digest = hashlib.sha256(canonical_json(row).encode()).hexdigest()
        if aid in out and out[aid] != digest:
            raise ValueError("inconsistent duplicate activity")
        out[aid] = digest
    return out


def cash_flows(
    activities: list[dict], state: dict, *, before_read: datetime, prior_close: datetime
) -> tuple[Decimal, Decimal, dict[str, str]]:
    """Return post-baseline flow and prior-close-to-now flow, on distinct cash-flow windows."""
    current = fingerprints(activities)
    previous = state.get("activity_fingerprints", {})
    if any(current.get(aid) != digest for aid, digest in previous.items()):
        raise ValueError("activity history missing or changed")
    baseline = datetime.fromisoformat(state["baseline_at"])
    total, daily = Decimal(0), Decimal(0)
    unique = {row["id"]: row for row in activities}
    for aid, row in unique.items():
        kind = row.get("activity_type")
        if kind in _RETURNS:
            continue
        known = aid in state["baseline_seen"]
        text = row.get("transaction_time") or row.get("date")
        if not isinstance(text, str):
            raise ValueError("capital flow timing is ambiguous")
        try:
            occurred = datetime.fromisoformat(text)
        except (ValueError, TypeError) as exc:
            raise ValueError("capital flow timing is ambiguous") from exc
        date_only = occurred.tzinfo is None and isinstance(text, str) and len(text) == 10
        if date_only and known:
            start = occurred.replace(tzinfo=UTC)
            if start + timedelta(days=1) <= prior_close:
                continue
            if start <= prior_close or start > baseline:
                raise ValueError("baseline daily cash-flow timing is ambiguous")
            # Already included in the verified flat baseline; its whole date is after prior close.
            occurred = start
        elif occurred.tzinfo is None or not isinstance(text, str) or "T" not in text:
            raise ValueError("capital flow needs an exact timezone-aware occurrence time")
        if occurred > before_read:
            raise ValueError("capital flow overlaps account valuation")
        if occurred <= baseline and occurred <= prior_close:
            continue
        if kind not in _CASH:
            raise ValueError("unsupported or in-kind activity; human review required")
        amount = decimal(row.get("net_amount"))
        if (kind == "CSD" and amount <= 0) or (kind == "CSW" and amount >= 0):
            raise ValueError("capital flow sign is inconsistent")
        if not known and occurred > baseline:
            total += amount
        if occurred > prior_close:
            daily += amount
    return total, daily, current
