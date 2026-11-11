"""Per-tenant observations from real scheduled paper runs; replay is never elapsed evidence."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, date, datetime
from typing import Any, Protocol

from algua.contracts.canonical import canonical_json

PROFILE_JSON = canonical_json({
    'name': 'experimental_historical_ops', 'version': 1,
    'historical': {'current_research_gate': True, 'pit_required': True,
                   'sealed_holdout_bars': 63, 'holdout_sharpe_above': 0.0,
                   'statistical_checks': 'advisory'},
    'paper': {'completed_scheduled_sessions': 5, 'contiguous': True,
              'broker_clock': True, 'reconciled': True, 'paper_sharpe_test': False},
    'authority': 'experimental_qualification_only_not_live',
})
PROFILE_DIGEST = hashlib.sha256(PROFILE_JSON.encode()).hexdigest()


class SessionCalendar(Protocol):
    def previous_session(self, day: date) -> date: ...


def session_status(conn: sqlite3.Connection, deployment_id: int, *, last_completed: date,
                   calendar: SessionCalendar) -> dict[str, Any]:
    expected = [last_completed]
    for _ in range(4):
        expected.append(calendar.previous_session(expected[-1]))
    rows = conn.execute(
        'SELECT * FROM experimental_paper_sessions WHERE deployment_id=? ORDER BY id',
        (deployment_id,)).fetchall()
    latest = {row['session']: row for row in rows}
    chosen = [latest.get(day.isoformat()) for day in reversed(expected)]
    valid = [row for row in chosen if row is not None and row['passed'] == 1
             and row['profile_digest'] == PROFILE_DIGEST and row['account_id']]
    accounts = {row['account_id'] for row in valid}
    passed = len(valid) == 5 and len(accounts) == 1 and not any(
        day > last_completed.isoformat() for day in latest)
    return {'passed': passed, 'required_sessions': 5,
            'account_id': next(iter(accounts)) if len(accounts) == 1 else None,
            'sessions': [{'observation_id': row['id'], 'session': row['session'],
                          'evidence': json.loads(row['evidence_json'])} for row in valid],
            'expected_sessions': [day.isoformat() for day in reversed(expected)]}


def _now() -> datetime:
    return datetime.now(UTC)


def capture_session(conn: sqlite3.Connection, *, session: date, after_tick_id: int,
                    payload: dict, observed_at: datetime) -> int:
    """Called only by the real, non-overridden operator completion hook under its run lock.

    Store refusals too; latest successful retry may resolve a session, but gaps cannot disappear.
    No external timestamp, arbitrary account or synthetic return can be supplied by a CLI flag.
    """
    from algua.calendar.factory import get_calendar
    from algua.operator.schedule import target_session

    actual = _now()
    if (observed_at.tzinfo is None or abs((actual - observed_at).total_seconds()) > 60
            or target_session(actual, get_calendar()) != session):
        raise ValueError('experimental sessions require the actual completed exchange session')
    entries = payload.get('strategies', [])
    if not isinstance(entries, list):
        raise ValueError('paper completion payload must contain strategy results')
    count = 0
    for entry in entries:
        name = entry.get('strategy') if isinstance(entry, dict) else None
        if not isinstance(name, str):
            continue
        dep = conn.execute(
            "SELECT d.id AS deployment_id,d.activated_at,a.* FROM strategy_deployments d "
            "JOIN strategies s ON s.id=d.strategy_id "
            "JOIN deployment_artifacts a ON a.id=d.artifact_id "
            "WHERE s.name=? AND d.retired_at IS NULL AND a.source_kind='frozen'", (name,)
        ).fetchone()
        if dep is None:
            continue
        tick = conn.execute(
            'SELECT t.*,i.id AS linked FROM tick_snapshots t LEFT JOIN frozen_invocations i '
            "ON i.id=t.frozen_invocation_id AND i.phase='b' AND i.deployment_id=t.deployment_id "
            "AND i.snapshot_id=t.snapshot_id AND i.failure_code IS NULL "
            "AND i.result_kind IN ('decision','late_no_decision') "
            "WHERE t.strategy=? AND t.deployment_id=? AND t.lane='paper' AND t.id>? "
            'ORDER BY t.id DESC LIMIT 1', (name, dep['deployment_id'], after_tick_id)).fetchone()
        passed = entry.get('ok') is True and tick is not None
        evidence: dict[str, Any] = {'strategy': name, 'reason': 'no_eligible_tick'}
        account = None
        if tick is not None:
            account = tick['account_id']
            try:
                tick_time = datetime.fromisoformat(tick['tick_ts'])
                decision = datetime.fromisoformat(tick['decision_ts'])
                recorded = datetime.fromisoformat(tick['recorded_at'])
                passed = passed and bool(
                    tick['linked'] and account and tick['snapshot_id'] and tick['reconcile_ok'] == 1
                    and tick['clock_source'] == 'broker' and decision.date() == session
                    and tick_time.tzinfo is not None and recorded.tzinfo is not None
                    and decision.tzinfo is not None and tick_time <= actual and recorded <= actual
                    and tick_time.date() >= session
                    and session >= datetime.fromisoformat(dep['activated_at']).date()
                    and all(tick[key] == dep[key] for key in
                            ('code_hash','config_hash','dependency_hash')))
            except (TypeError, ValueError):
                passed = False
            evidence = {'strategy': name, 'tick_id': tick['id'],
                        'invocation_id': tick['frozen_invocation_id'],
                        'snapshot_id': tick['snapshot_id'],
                        'manifest_digest': dep['manifest_digest'],
                        'provider': 'alpaca-paper', 'reason': None if passed else 'invalid_tick'}
        conn.execute('INSERT INTO experimental_paper_sessions '
            '(deployment_id,session,account_id,profile_digest,passed,evidence_json) '
            'VALUES (?,?,?,?,?,?)', (dep['deployment_id'], session.isoformat(), account,
                                   PROFILE_DIGEST, int(passed), canonical_json(evidence)))
        count += 1
    conn.commit()
    return count
