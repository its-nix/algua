"""Attach actual paper-session observations to scheduled runs; --now is ineligible."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from algua.registry.db import registry_conn
from algua.registry.experimental_sessions import capture_session


def completed_session_observer(job: str, *, clock_overridden: bool,
                               ) -> Callable[[date, dict], None] | None:
    if job != 'paper' or clock_overridden:
        return None
    with registry_conn() as conn:
        after_id = int(conn.execute('SELECT coalesce(max(id),0) FROM tick_snapshots').fetchone()[0])

    def completed(session: date, payload: dict[str, Any]) -> None:
        with registry_conn() as conn:
            capture_session(conn, session=session, after_tick_id=after_id,
                            payload=payload, observed_at=datetime.now(UTC))

    return completed
