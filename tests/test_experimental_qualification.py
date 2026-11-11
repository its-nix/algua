"""The fast route binds current historical evidence and does not mint strict/live authority."""
import json
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from algua.calendar.factory import get_calendar
from algua.cli.main import app
from algua.contracts.lifecycle import Actor
from algua.operator.schedule import target_session
from algua.registry import experimental_qualification as qualification
from algua.registry.db import connect, migrate
from algua.registry.experimental_sessions import PROFILE_DIGEST
from algua.registry.store import SqliteStrategyRepository
from tests._frozen_evidence_helpers import seed_deployment


@pytest.fixture
def qualified(tmp_path, monkeypatch):
    path = tmp_path / 'ops.db'
    monkeypatch.setenv('ALGUA_DB_PATH', str(path))
    conn = connect(path)
    migrate(conn)
    _, dep_id = seed_deployment(conn, 'ops_s', source_kind='frozen')
    from algua.registry import frozen_runtime
    monkeypatch.setattr(frozen_runtime, 'recorded_descriptor', lambda *args: (None,None))
    monkeypatch.setattr(qualification, 'historical_evidence', lambda *args:
        {'research_gate_id': 1, 'holdout_bars':63, 'holdout_sharpe':0.4,
         'fixture':True})
    cal, now = get_calendar(), datetime.now(UTC)
    last = target_session(now, cal)
    for _ in range(5):
        conn.execute('INSERT INTO experimental_paper_sessions '
            '(deployment_id,session,account_id,profile_digest,passed,evidence_json) '
            "VALUES (?,?,?, ?,1,'{}')", (dep_id, last.isoformat(), 'acct', PROFILE_DIGEST))
        last = cal.previous_session(last)
    conn.commit()
    yield conn, cal, now, dep_id
    conn.close()


def test_report_counts_sessions_without_retesting_paper_returns(qualified):
    conn, cal, now, _ = qualified
    result = qualification.qualification_report(conn, 'ops_s', calendar=cal, now=now)
    assert result['passed'] and result['live_authority'] is False
    assert result['profile']['paper']['paper_sharpe_test'] is False
    assert len(result['operational']['sessions']) == 5


def test_seeded_gate_without_committed_lineage_is_not_historical_evidence(tmp_path):
    conn = connect(tmp_path / 'gate.db')
    migrate(conn)
    sid, _ = seed_deployment(conn, 'ops_s', source_kind='frozen')
    repo = SqliteStrategyRepository(conn)
    assert qualification.historical_evidence(repo, repo.active_deployment(sid)) is None
    conn.close()


@pytest.mark.parametrize('actor', list(Actor))
def test_qualification_records_honest_actor_idempotently_without_strict_authority(qualified, actor):
    conn, cal, now, _ = qualified
    result = qualification.qualification_report(conn, 'ops_s', calendar=cal, now=now)
    rid = qualification.record_qualification(conn, 'ops_s', calendar=cal, now=now,
                                             expected=result, actor=actor)
    assert qualification.record_qualification(conn, 'ops_s', calendar=cal, now=now,
                                              expected=result, actor=actor) == rid
    row = conn.execute('SELECT actor FROM experimental_qualifications').fetchone()
    assert row['actor'] == actor.value
    # An idempotent retry never rewrites the original author's provenance.
    assert qualification.record_qualification(conn, 'ops_s', calendar=cal, now=now,
                                              expected=result, actor=Actor.SYSTEM) == rid
    persisted = conn.execute('SELECT actor FROM experimental_qualifications').fetchone()
    assert persisted['actor'] == actor.value
    assert SqliteStrategyRepository(conn).get('ops_s').stage.value == 'paper'
    assert conn.execute('SELECT COUNT(*) FROM forward_gate_evaluations').fetchone()[0] == 0
    assert conn.execute('SELECT COUNT(*) FROM approvals').fetchone()[0] == 0
    assert conn.execute('SELECT COUNT(*) FROM experimental_qualifications').fetchone()[0] == 1
    with pytest.raises(Exception, match='immutable'):
        conn.execute('DELETE FROM experimental_qualifications')
    conn.rollback()


def test_changed_evidence_refuses_under_write_lock(qualified):
    conn, cal, now, dep = qualified
    result = qualification.qualification_report(conn, 'ops_s', calendar=cal, now=now)
    conn.execute('INSERT INTO experimental_paper_sessions '
        '(deployment_id,session,account_id,profile_digest,passed,evidence_json) '
        'VALUES (?,?,?,?,0,?)',
        (dep, result['operational']['sessions'][-1]['session'], 'acct', PROFILE_DIGEST, '{}'))
    conn.commit()
    with pytest.raises(ValueError, match='changed or failed'):
        qualification.record_qualification(conn, 'ops_s', calendar=cal, now=now,
                                           expected=result, actor=Actor.AGENT)
    assert conn.execute('SELECT COUNT(*) FROM experimental_qualifications').fetchone()[0] == 0


def test_cli_preview_is_read_only_and_default_records_agent_idempotently(qualified, monkeypatch):
    from algua.cli import paper_experimental

    conn, *_ = qualified
    monkeypatch.setattr(paper_experimental, 'verify_frozen_artifact', lambda *args, **kw: None)
    runner = CliRunner()
    args = ['paper', 'qualify-experimental', 'ops_s']
    preview = runner.invoke(app, [*args, '--preview'])
    assert preview.exit_code == 0, preview.stdout
    assert json.loads(preview.stdout)['recorded'] is False
    assert conn.execute('SELECT COUNT(*) FROM experimental_qualifications').fetchone()[0] == 0
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.stdout
    assert json.loads(first.stdout)['recorded'] is True
    repeated = runner.invoke(app, args)
    assert repeated.exit_code == 0, repeated.stdout
    assert json.loads(first.stdout)['experimental_qualification_id'] == json.loads(
        repeated.stdout)['experimental_qualification_id']
    assert conn.execute('SELECT actor FROM experimental_qualifications').fetchone()[0] == 'agent'
    assert conn.execute('SELECT COUNT(*) FROM actor_challenges').fetchone()[0] == 0


@pytest.mark.parametrize('actor', ['human', 'system'])
def test_cli_compatibility_actor_is_unsigned_provenance(qualified, monkeypatch, actor):
    from algua.cli import paper_experimental

    conn, *_ = qualified
    monkeypatch.setattr(paper_experimental, 'verify_frozen_artifact', lambda *args, **kw: None)
    result = CliRunner().invoke(app, ['paper', 'qualify-experimental', 'ops_s',
        '--actor', actor, '--actor-signature', '/not-read-or-required'])
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)['recorded'] is True
    assert conn.execute('SELECT actor FROM experimental_qualifications').fetchone()[0] == actor
    assert conn.execute('SELECT COUNT(*) FROM actor_challenges').fetchone()[0] == 0


def test_failed_report_cannot_record_even_when_expected_matches(qualified, monkeypatch):
    conn, cal, now, _ = qualified
    monkeypatch.setattr(qualification, 'historical_evidence', lambda *args: None)
    report = qualification.qualification_report(conn, 'ops_s', calendar=cal, now=now)
    with pytest.raises(ValueError, match='changed or failed'):
        qualification.record_qualification(conn, 'ops_s', calendar=cal, now=now,
                                            expected=report, actor=Actor.AGENT)
    result = CliRunner().invoke(app, ['paper', 'qualify-experimental', 'ops_s'])
    assert result.exit_code == 1, result.stdout
    assert json.loads(result.stdout)['recorded'] is False
    assert conn.execute('SELECT COUNT(*) FROM experimental_qualifications').fetchone()[0] == 0


def seed_historical_lineage(conn, *, delistings=False):
    """Explicit synthetic rows model the canonical writer's links; no qualification claim."""
    sid, dep_id = seed_deployment(conn, 'lineage_s', source_kind='frozen')
    t = '2026-08-31T20:00:00+00:00'
    gate_id = conn.execute('SELECT research_gate_id FROM strategy_deployments WHERE id=?',
                           (dep_id,)).fetchone()[0]
    conn.execute('UPDATE gate_evaluations SET created_at=?,decision_json=? WHERE id=?',
                 (t, '{"passed":true}', gate_id))
    burn = conn.execute('INSERT INTO holdout_evaluations '
        '(strategy_id,data_source,snapshot_id,period_start,period_end,holdout_frac,config_hash,'
        'reused,created_at,committed_at,holdout_start,holdout_end) '
        "VALUES (?,'test','snap','2024-01-01','2024-12-31',0.2,'wf-config',0,?,?,"
        "'2024-10-01','2024-12-31')", (sid,t,t)).lastrowid
    series = conn.execute('INSERT INTO holdout_returns '
        '(holdout_evaluation_id,strategy_id,holdout_start,holdout_end,n_bars,returns_blob,'
        'bar_dates_blob,created_at) VALUES (?,?,\'2024-10-01\',\'2024-12-31\',63,?,?,?)',
        (burn,sid,b'SYNTHETIC_FIXTURE',b'SYNTHETIC_FIXTURE',t)).lastrowid
    repo = SqliteStrategyRepository(conn)
    common = {'data_source':'test','snapshot_id':'snap','period_start':'2024-01-01',
              'period_end':'2024-12-31','universe_name':'u'}
    wf = repo.record_run('walk_forward','lineage_s',strategy_id=sid,
                         provenance=common | {'config_hash':'wf-config'})
    repo.record_run('gate','lineage_s',strategy_id=sid,derived_from=[wf],
        provenance=common | {'code_hash':'c'*32,'config_hash':'g'*32,'dependency_hash':'d'*64,
                             'delisting_snapshot':'delisting-pin' if delistings else None},
        gate_id=gate_id,passed=True,series_holdout_id=series,
        metrics={'sharpe_oos':0.4,'n_obs_oos':63})
    # Align the synthetic writer chronology; real writer stamps these in this order itself.
    conn.execute('UPDATE runs SET created_at=?', (t,))
    conn.commit()
    return repo, repo.active_deployment(sid), burn


@pytest.mark.parametrize('delistings', [False, True])
def test_historical_criteria_accept_canonical_burn_without_comparison_metadata(
        tmp_path, delistings):
    conn = connect(tmp_path/'lineage.db')
    migrate(conn)
    repo, dep, _ = seed_historical_lineage(conn, delistings=delistings)
    evidence = qualification.historical_evidence(repo, dep)
    assert evidence is not None and evidence['holdout_sharpe'] == 0.4
    conn.close()


@pytest.mark.parametrize('fault', ['pending','reused','snapshot','count','interval','identity'])
def test_bad_historical_lineage_refuses(tmp_path, fault):
    conn = connect(tmp_path/'lineage.db')
    migrate(conn)
    repo, dep, burn = seed_historical_lineage(conn)
    statements = {
        'pending': 'UPDATE holdout_evaluations SET committed_at=NULL',
        'reused': 'UPDATE holdout_evaluations SET reused=1',
        'snapshot': "UPDATE holdout_evaluations SET snapshot_id='other'",
        'count': 'UPDATE holdout_returns SET n_bars=62',
        'interval': "UPDATE holdout_returns SET holdout_start='2024-09-01'",
        'identity': "UPDATE runs SET config_hash='wrong' WHERE kind='gate'",
    }
    conn.execute(statements[fault])
    conn.commit()
    assert qualification.historical_evidence(repo, dep) is None
    conn.close()
