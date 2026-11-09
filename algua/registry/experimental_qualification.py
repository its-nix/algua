"""Experimental historical + five-session evidence; never a strict live certificate."""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from datetime import datetime
from typing import Any

from algua.contracts.canonical import canonical_json
from algua.contracts.lifecycle import Actor, Stage
from algua.operator.schedule import target_session
from algua.provenance.json_record import decode_json
from algua.registry.experimental_sessions import PROFILE_DIGEST, PROFILE_JSON, session_status
from algua.registry.store import SqliteStrategyRepository


def historical_evidence(repo: SqliteStrategyRepository, deployment: Any) -> dict[str, Any] | None:
    """Bind the exact epoch's current research criteria to a committed non-reused OOS vector."""
    conn = repo.connection
    gate = conn.execute('SELECT * FROM gate_evaluations WHERE id=? AND strategy_id=?',
                        (deployment.research_gate_id, deployment.strategy_id)).fetchone()
    if (gate is None or gate['passed'] != 1 or gate['pit_ok'] != 1 or gate['pit_override'] != 0
            or gate['holdout_n_bars'] is None or gate['holdout_n_bars'] < 63
            or any(gate[key] != getattr(deployment, key) for key in
                   ('code_hash','config_hash','dependency_hash'))):
        return None
    run = conn.execute("SELECT * FROM runs WHERE kind='gate' AND gate_id=? ORDER BY id DESC",
                       (deployment.research_gate_id,)).fetchone()
    if run is None:
        return None
    try:
        parents = decode_json(run['derived_from'])
        if not isinstance(parents, list) or len(parents) != 1 or type(parents[0]) is not int:
            return None
        sibling = repo.get_run(parents[0])
        series = conn.execute('SELECT * FROM holdout_returns WHERE id=?',
                              (run['series_holdout_id'],)).fetchone()
        if series is None or sibling is None or sibling['kind'] != 'walk_forward':
            return None
        burn = conn.execute('SELECT * FROM holdout_evaluations WHERE id=?',
                            (series['holdout_evaluation_id'],)).fetchone()
        if (burn is None or burn['reused'] != 0 or run['passed'] != 1
                or any(row['strategy_id'] != deployment.strategy_id
                       for row in (run, sibling, series, burn))
                or any(run[key] != gate[key] for key in
                       ('code_hash','config_hash','dependency_hash','data_source','snapshot_id',
                        'period_start','period_end','universe_name'))
                or any(burn[key] != sibling[key] or burn[key] != run[key] for key in
                       ('data_source','snapshot_id','period_start','period_end'))
                or burn['config_hash'] != sibling['config_hash']
                or burn['holdout_frac'] != gate['holdout_frac']
                or (series['holdout_start'],series['holdout_end']) !=
                   (burn['holdout_start'],burn['holdout_end'])
                or not (gate['period_start'] <= series['holdout_start'] <=
                        series['holdout_end'] <= gate['period_end'])
                or not (series['n_bars'] == gate['holdout_n_bars'] == run['n_obs_oos'])):
            return None
        instants = [datetime.fromisoformat(row[key]) for row, key in (
            (burn,'created_at'), (burn,'committed_at'), (series,'created_at'),
            (sibling,'created_at'), (gate,'created_at'), (run,'created_at'))]
        if any(t.tzinfo is None for t in instants) or instants != sorted(instants):
            return None
        sharpe = float(run['sharpe_oos'])
        decision = json.loads(gate['decision_json'])
        if not math.isfinite(sharpe) or sharpe <= 0 or decision.get('passed') is not True:
            return None
        return {'research_gate_id': deployment.research_gate_id, 'gate_run_id': run['id'],
                'holdout_evaluation_id': burn['id'], 'series_holdout_id': series['id'],
                'snapshot_id': gate['snapshot_id'], 'holdout_bars': gate['holdout_n_bars'],
                'holdout_sharpe': sharpe, 'decision': decision}
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, RecursionError):
        return None


def qualification_report(conn: sqlite3.Connection, name: str, *, calendar: Any,
                         now: datetime) -> dict[str, Any]:
    repo = SqliteStrategyRepository(conn)
    rec = repo.get(name)
    if rec.stage not in (Stage.PAPER, Stage.FORWARD_TESTED):
        raise ValueError('experimental qualification requires an active paper strategy')
    deployment = repo.active_deployment(rec.id)
    if deployment is None or deployment.source_kind != 'frozen':
        raise ValueError('experimental qualification requires a frozen deployment')
    from algua.registry.frozen_runtime import recorded_descriptor

    recorded_descriptor(deployment, name)
    last = target_session(now, calendar)
    if last is None:
        raise ValueError('no completed exchange session')
    historical = historical_evidence(repo, deployment)
    sessions = session_status(conn, deployment.id, last_completed=last, calendar=calendar)
    report = {'profile': json.loads(PROFILE_JSON), 'profile_digest': PROFILE_DIGEST,
              'strategy': name, 'strategy_id': rec.id, 'deployment_id': deployment.id,
              'manifest_digest': deployment.manifest_digest,
              'code_hash': deployment.code_hash, 'config_hash': deployment.config_hash,
              'dependency_hash': deployment.dependency_hash,
              'provider': 'alpaca-paper', 'historical': historical, 'operational': sessions,
              'passed': historical is not None and sessions['passed'],
              'live_authority': False,
              'acceptance_scope': 'historical eligibility and scheduled normal paper ticks; '
                                  'failure-path acceptance and capped live authorization '
                                  'remain separate'}
    report['evidence_digest'] = hashlib.sha256(canonical_json(report).encode()).hexdigest()
    return report


def record_qualification(conn: sqlite3.Connection, name: str, *, calendar: Any, now: datetime,
                         expected: dict, actor: Actor) -> int:
    """Record actual authorship, rechecking evidence under the lock; grants no live authority."""
    actor = Actor(actor)
    if conn.in_transaction:
        raise ValueError('qualification requires its own transaction')
    conn.execute('BEGIN IMMEDIATE')
    try:
        actual = qualification_report(conn, name, calendar=calendar, now=now)
        if not actual['passed'] or actual != expected:
            raise ValueError('experimental qualification evidence changed or failed')
        conn.execute('INSERT OR IGNORE INTO experimental_qualifications '
            '(deployment_id,profile_digest,evidence_digest,evidence_json,actor) VALUES (?,?,?,?,?)',
            (actual['deployment_id'], PROFILE_DIGEST, actual['evidence_digest'],
             canonical_json(actual), actor.value))
        row = conn.execute('SELECT id FROM experimental_qualifications WHERE deployment_id=? '
                           'AND profile_digest=? AND evidence_digest=?',
                           (actual['deployment_id'], PROFILE_DIGEST,
                            actual['evidence_digest'])).fetchone()
        assert row is not None
        conn.commit()
        return int(row['id'])
    except BaseException:
        conn.rollback()
        raise
