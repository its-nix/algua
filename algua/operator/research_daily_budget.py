"""Durable UTC-day launch reservations; resource limits grant no trading authority."""
from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from algua.primitives.atomic_io import write_bytes_durable
from algua.primitives.flock import file_lock
from algua.registry.read_snapshot import registry_snapshot


class DailyResearchBudget:
    def __init__(self, directory: Path, database: Path, limit: int) -> None:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('daily research budget must be between 1 and 100')
        self.directory, self.database, self.limit = directory, database, limit
        self.path = directory / 'research-budget.json'

    def _used(self, now: datetime) -> set[str]:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError('daily research budget requires a timezone-aware clock')
        day = now.astimezone(UTC).date()
        reserved: list[str] = []
        if self.path.exists():
            try:
                if self.path.stat().st_size > 128 * 1024:
                    raise ValueError
                state = json.loads(self.path.read_text())
                previous = date.fromisoformat(state['day'])
                rows = state['reserved']
                if (set(state) != {'day', 'reserved'} or not isinstance(rows, list)
                    or any(not isinstance(r, str) for r in rows) or len(set(rows)) != len(rows)
                    or previous > day):
                    raise ValueError
                reserved = rows if previous == day else []
            except (ValueError, TypeError, KeyError) as exc:
                raise ValueError('daily research budget is corrupt or clock moved backwards'
                                 ) from exc
        midnight = datetime.combine(day, datetime.min.time(), UTC)
        with registry_snapshot(self.database, label='research budget registry') as snapshot:
            claimed = {r[0] for r in snapshot.connection.execute(
                'SELECT DISTINCT run_stamp FROM idea_attempts WHERE '
                'julianday(claimed_at)>=julianday(?) AND julianday(claimed_at)<julianday(?)',
                (midnight.isoformat(), (midnight + timedelta(days=1)).isoformat()))}
        # Legacy model launches without claims still consumed resources before this cap existed.
        pattern = day.strftime('%Y%m%d') + '*.choice/menu.json'
        launches = {p.parent.name.removesuffix('.choice')
                    for p in (self.directory / 'research-cycles').glob(pattern)}
        return set(reserved) | claimed | launches

    def remaining(self, *, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        self.directory.mkdir(parents=True, exist_ok=True)
        with file_lock(self.directory / 'research-budget.lock'):
            return max(0, self.limit - len(self._used(now)))

    def reserve(self, cycle_id: str, *, now: datetime | None = None) -> bool:
        if (not isinstance(cycle_id, str)
                or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}', cycle_id) is None):
            raise ValueError('invalid research budget cycle identity')
        now = now or datetime.now(UTC)
        self.directory.mkdir(parents=True, exist_ok=True)
        with file_lock(self.directory / 'research-budget.lock'):
            used = self._used(now)
            if cycle_id in used or len(used) >= self.limit:
                return False
            used.add(cycle_id)
            payload = {'day': now.astimezone(UTC).date().isoformat(), 'reserved': sorted(used)}
            write_bytes_durable(json.dumps(payload, sort_keys=True).encode(), self.path)
        return True
