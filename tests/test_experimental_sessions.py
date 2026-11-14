"""Five actual scheduled sessions are a separate qualification, never five returns or live proof."""
from datetime import UTC, date, datetime

import pytest

from algua.registry.db import connect, migrate
from algua.registry.experimental_sessions import session_status
from tests._frozen_evidence_helpers import seed_deployment


@pytest.fixture
def conn(tmp_path):
    result = connect(tmp_path / 'ops.db')
    migrate(result)
    yield result
    result.close()


class Calendar:
    def previous_session(self, day):
        from datetime import timedelta
        day -= timedelta(days=1)
        while day.weekday() > 4:
            day -= timedelta(days=1)
        return day


def add_session(conn, dep, day, *, account='paper-1', passed=True, profile=None):
    from algua.registry.experimental_sessions import PROFILE_DIGEST
    conn.execute('INSERT INTO experimental_paper_sessions '
        '(deployment_id,session,account_id,profile_digest,passed,evidence_json) '
        'VALUES (?,?,?,?,?,?)',
        (dep, day, account, profile or PROFILE_DIGEST, int(passed), '{}'))
    conn.commit()


def test_five_completed_sessions_qualify_without_a_paper_sharpe_test(conn):
    _, dep = seed_deployment(conn, 'ops_s', source_kind='frozen')
    for day in ('2026-09-24','2026-09-25','2026-09-28','2026-09-29','2026-09-30'):
        add_session(conn, dep, day)
    status = session_status(conn, dep, last_completed=date(2026,9,30), calendar=Calendar())
    assert status['passed'] and len(status['sessions']) == 5
    assert status['account_id'] == 'paper-1'
    assert conn.execute('SELECT COUNT(*) FROM forward_gate_evaluations').fetchone()[0] == 0


@pytest.mark.parametrize('fault', ['four','gap','failure','account','profile','stale'])
def test_incomplete_or_mixed_session_evidence_refuses(conn, fault):
    _, dep = seed_deployment(conn, 'ops_s', source_kind='frozen')
    days = ['2026-09-24','2026-09-25','2026-09-28','2026-09-29','2026-09-30']
    if fault == 'four':
        days = days[1:]
    if fault == 'gap':
        days[0] = '2026-09-23'
    for i, day in enumerate(days):
        add_session(conn, dep, day, account='other' if fault == 'account' and i == 0 else 'paper-1',
                    passed=not(fault == 'failure' and i == 0),
                    profile='wrong' if fault == 'profile' and i == 0 else None)
    last = date(2026,10,1) if fault == 'stale' else date(2026,9,30)
    assert not session_status(conn, dep, last_completed=last, calendar=Calendar())['passed']


def test_rows_are_append_only_and_duplicate_session_does_not_add_a_day(conn):
    _, dep = seed_deployment(conn, 'ops_s', source_kind='frozen')
    add_session(conn, dep, '2026-09-30')
    add_session(conn, dep, '2026-09-30')
    status = session_status(conn, dep, last_completed=date(2026,9,30), calendar=Calendar())
    assert not status['passed']
    with pytest.raises(Exception, match='immutable'):
        conn.execute("UPDATE experimental_paper_sessions SET passed=1")


def test_override_and_nonpaper_job_never_capture_sessions():
    from algua.operator.paper_observations import completed_session_observer
    assert completed_session_observer('paper', clock_overridden=True) is None
    assert completed_session_observer('live', clock_overridden=False) is None


@pytest.mark.parametrize('fault',
    ['valid','local_clock','prior_tick','failed_tenant','future_clock'])
def test_capture_requires_fresh_reconciled_broker_tick_for_this_tenant(conn, monkeypatch, fault):
    from algua.registry import experimental_sessions as sessions
    from tests.test_forward_evidence_frozen import linked_tick

    now = datetime(2026,9,30,22,tzinfo=UTC)
    monkeypatch.setattr(sessions, '_now', lambda: now)
    ids = seed_deployment(conn, 'ops_s', source_kind='frozen')
    tick_id = linked_tick(conn, ids, date(2026,9,30), 100., name='ops_s',
        decision_ts='2026-09-30T00:00:00+00:00',
        clock_source='local' if fault == 'local_clock' else 'broker')
    supplied = datetime(2027,1,1,tzinfo=UTC) if fault == 'future_clock' else now
    if fault == 'future_clock':
        with pytest.raises(ValueError, match='actual completed'):
            sessions.capture_session(conn, session=date(2026,9,30), after_tick_id=0,
                payload={'strategies':[{'strategy':'ops_s','ok':True}]}, observed_at=supplied)
        return
    sessions.capture_session(conn, session=date(2026,9,30),
        after_tick_id=tick_id if fault == 'prior_tick' else 0,
        payload={'strategies':[{'strategy':'ops_s','ok':fault != 'failed_tenant'}]},
        observed_at=supplied)
    row = conn.execute('SELECT * FROM experimental_paper_sessions').fetchone()
    assert row['passed'] == int(fault == 'valid')
    assert row['deployment_id'] == ids[1]


def test_sibling_success_does_not_create_evidence_for_other_tenant(conn, monkeypatch):
    from algua.registry import experimental_sessions as sessions
    now = datetime(2026,9,30,22,tzinfo=UTC)
    monkeypatch.setattr(sessions, '_now', lambda: now)
    seed_deployment(conn, 'ops_s', source_kind='frozen')
    assert sessions.capture_session(conn, session=now.date(), after_tick_id=0,
        payload={'strategies':[{'strategy':'unrelated','ok':True}]}, observed_at=now) == 0
