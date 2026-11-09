"""Qualification provenance widens honestly while immutable evidence and references survive."""
import sqlite3

import pytest

from algua.registry.db import SCHEMA_VERSION, connect, migrate
from algua.registry.db.experimental import SCHEMA
from tests._frozen_evidence_helpers import seed_deployment


@pytest.mark.parametrize('version', [52, 53])
def test_old_qualification_table_preserves_rows_references_triggers_and_sequence(tmp_path, version):
    conn = connect(tmp_path / 'migration.db')
    migrate(conn)
    sid, dep = seed_deployment(conn, 'ops_s', source_kind='frozen')
    # Start with the exact previous CHECK, even on an already stamped partial schema.
    conn.execute('DROP TABLE experimental_qualifications')
    conn.executescript(SCHEMA.replace(
        "CHECK(actor IN ('human','agent','system'))", "CHECK(actor='human')"))
    conn.execute("INSERT INTO experimental_qualifications "
        "(id,deployment_id,profile_digest,evidence_digest,evidence_json,actor,created_at) "
        "VALUES (17,?,'profile','evidence','{\"fixture\":true}','human','2026-11-08')", (dep,))
    # Synthetic signed-authority storage tests actual capped-live FK preservation, not authority.
    approval = conn.execute('INSERT INTO approvals '
        '(strategy_id,code_hash,config_hash,dependency_hash,approved_by,created_at) '
        "VALUES (?,'code','config','dep','owner','t')", (sid,)).lastrowid
    policy = conn.execute('INSERT INTO drawdown_policies '
        '(lane,account_id,policy_json,principal,created_at) '
        "VALUES ('live','acct','{}','owner','t')").lastrowid
    conn.execute('INSERT INTO capped_live_challenges '
        '(nonce,strategy_id,context_json,issued_at,expires_at,consumed_at) '
        "VALUES ('nonce',?,'{}','t','t','t')", (sid,))
    conn.execute('INSERT INTO capped_live_authorizations '
        '(strategy_id,deployment_id,qualification_id,approval_id,risk_policy_id,capital,'
        'live_account_id,provider_json,nonce,expires_at,signature,principal,authorized_at) '
        "VALUES (?,?,17,?,?,'100','acct','{}','nonce','t','SYNTHETIC','owner','t')",
        (sid, dep, approval, policy))
    authority = tuple(conn.execute('SELECT * FROM capped_live_authorizations').fetchone())
    conn.execute("UPDATE sqlite_sequence SET seq=23 WHERE name='experimental_qualifications'")
    before = tuple(conn.execute('SELECT * FROM experimental_qualifications').fetchone())
    conn.execute(f'PRAGMA user_version={version}')
    conn.commit()
    migrate(conn)
    migrate(conn)
    assert SCHEMA_VERSION == 53
    assert conn.execute('PRAGMA user_version').fetchone()[0] == 53
    assert conn.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
    assert tuple(conn.execute('SELECT * FROM experimental_qualifications').fetchone()) == before
    assert tuple(conn.execute('SELECT * FROM capped_live_authorizations').fetchone()) == authority
    for actor in ('agent', 'system'):
        rid = conn.execute('INSERT INTO experimental_qualifications '
            '(deployment_id,profile_digest,evidence_digest,evidence_json,actor) '
            'VALUES (?, ?, ?, ?, ?)', (dep, 'profile', actor, '{}', actor)).lastrowid
        assert rid > 23
    conn.commit()
    for statement in ('UPDATE experimental_qualifications SET actor=\'agent\'',
                      'DELETE FROM experimental_qualifications',
                      'INSERT OR REPLACE INTO experimental_qualifications '
                      'SELECT * FROM experimental_qualifications'):
        with pytest.raises(sqlite3.IntegrityError, match='immutable'):
            conn.execute(statement)
        conn.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute('INSERT INTO experimental_qualifications '
            '(deployment_id,profile_digest,evidence_digest,evidence_json,actor) '
            "VALUES (999, 'profile', 'invalid-deployment', '{}', 'agent')")
    conn.rollback()
    conn.close()


def test_fresh_schema_admits_only_real_actor_vocabulary_and_refuses_future_marker(tmp_path):
    conn = connect(tmp_path / 'fresh.db')
    migrate(conn)
    _, dep = seed_deployment(conn, 'ops_s', source_kind='frozen')
    for actor in ('human', 'agent', 'system'):
        conn.execute('INSERT INTO experimental_qualifications '
            '(deployment_id,profile_digest,evidence_digest,evidence_json,actor) '
            'VALUES (?, ?, ?, ?, ?)', (dep, 'profile', actor, '{}', actor))
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute('INSERT INTO experimental_qualifications '
            '(deployment_id,profile_digest,evidence_digest,evidence_json,actor) '
            "VALUES (?, 'profile', 'other', '{}', 'forged')", (dep,))
    conn.rollback()
    conn.execute('PRAGMA user_version=54')
    conn.commit()
    before = list(conn.iterdump())
    with pytest.raises(ValueError, match='newer'):
        migrate(conn)
    assert list(conn.iterdump()) == before
    conn.close()
