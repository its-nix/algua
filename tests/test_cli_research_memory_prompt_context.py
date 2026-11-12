"""Real read-only archive context through the public CLI into the existing leap prompt."""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from algua.cli.main import main
from algua.config.settings import Settings
from algua.operator.research_memory_checkpoint import canonical
from algua.registry.db import connect, migrate
from tests.test_campaign_public_memory import _finish
from tests.test_forage_leap_launchers import _run_leap_memory_context
from tests.test_research_memory import _artifact, _explore
from tests.test_research_memory import memory_case as memory_case


def _invoke(capsys):
    with pytest.raises(SystemExit) as stopped:
        main(['research', 'memory', 'prompt-context'])
    raw = capsys.readouterr().out
    return stopped.value.code, raw, json.loads(raw)


def _configure(monkeypatch, database, data, tracking):
    monkeypatch.setitem(Settings.model_config, 'env_file', None)
    for key, value in {'ALGUA_DB_PATH': str(database), 'ALGUA_DATA_DIR': str(data),
                       'ALGUA_MLFLOW_TRACKING_URI': str(tracking),
                       'ALGUA_TRACKING_BACKEND': 'mlflow-sqlite'}.items():
        monkeypatch.setenv(key, value)


def _files(paths):
    return {str(p): (p.stat().st_size, p.stat().st_mtime_ns,
                    hashlib.sha256(p.read_bytes()).hexdigest())
            for base in paths for p in [base, Path(str(base) + '-wal'), Path(str(base) + '-shm')]
            if p.exists()}


def _retained(memory_case, monkeypatch):
    authority, cycle, worker, source, archive, memory = memory_case
    _explore(source)
    receipt = memory.capture(worker, worker_exit=0, source_commit='b' * 40)
    _finish(cycle, worker, receipt)
    data = cycle.directory.parent
    cycle.directory.rename(data / 'research-cycles')
    database = Path(authority.execute('PRAGMA database_list').fetchone()[2])
    _configure(monkeypatch, database, data, archive.tracking_uri)
    return authority, worker, archive, receipt, database


def test_prompt_context_negative_archive_survives_prune_and_reaches_goal_and_digest(
    memory_case, tmp_path, monkeypatch, capsys,
):
    authority, worker, archive, receipt, database = _retained(memory_case, monkeypatch)
    tokens = [row[0] for row in authority.execute('SELECT claim_token FROM idea_attempts')]
    shutil.rmtree(worker)
    before = _files([database, tmp_path / 'tracking.db'])
    logical = list(authority.iterdump())
    code, raw, payload = _invoke(capsys)
    assert code == 0, raw
    snapshot = payload['public_research_memory']
    assert set(payload) == {'ok', 'public_research_memory'}
    assert snapshot['observations'][0]['metrics']['total_return_is'] == -0.3
    assert snapshot['authority'] == 'none' and snapshot['association'] == 'cycle_only'
    assert snapshot['evidence_mode'] == 'UNVERIFIED_WORKER'
    assert snapshot['receipts'][0]['attempt_evidence_ids'] == ['idea_attempts:1']
    assert snapshot['selection_protocol'] == 'recent_completed_comparisons_first/v1'
    assert all(token not in raw for token in tokens if token)
    assert _files([database, tmp_path / 'tracking.db']) == before
    assert list(authority.iterdump()) == logical
    forwarded = _run_leap_memory_context(tmp_path / 'driver', raw)
    assert canonical(snapshot).decode() in forwarded['goal']
    assert 'UNVERIFIED_WORKER' in forwarded['goal'] and 'cycle_only' in forwarded['goal']
    summary = forwarded['digest']['public_research_memory_context']
    assert summary['snapshot_sha256'] == hashlib.sha256(canonical(snapshot)).hexdigest()
    assert summary['receipt_refs'] == [receipt['reference']]
    assert summary['attempt_evidence_ids'] == ['idea_attempts:1']
    assert summary['observation_count'] == 4 and summary['status'] == 'available'
    assert 'observations' not in summary and 'metrics' not in summary


def test_prompt_context_corrupt_archive_is_not_a_valid_empty_result(
    memory_case, monkeypatch, capsys,
):
    _, _, archive, receipt, _ = _retained(memory_case, monkeypatch)
    _artifact(archive, receipt).write_bytes(b'corrupt synthetic evidence')
    code, raw, payload = _invoke(capsys)
    assert code == 1 and payload['ok'] is False
    assert payload['error'] == 'public_memory_context:artifact_integrity_mismatch'
    assert 'public_research_memory' not in payload


def test_prompt_context_empty_history_never_bootstraps_archive(tmp_path, monkeypatch, capsys):
    database = tmp_path / 'existing.db'
    conn = connect(database)
    migrate(conn)
    conn.close()
    tracking = tmp_path / 'absent-tracking.db'
    _configure(monkeypatch, database, tmp_path, tracking)
    before = _files([database])
    code, raw, payload = _invoke(capsys)
    assert code == 0, raw
    snapshot = payload['public_research_memory']
    assert snapshot['status'] == 'unavailable' and snapshot['observations'] == []
    assert not tracking.exists() and not (tmp_path / 'research-cycles').exists()
    assert _files([database]) == before
    forwarded = _run_leap_memory_context(tmp_path / 'unavailable-driver', raw)
    summary = forwarded['digest']['public_research_memory_context']
    assert summary['status'] == 'unavailable'
    assert summary['snapshot_sha256'] == hashlib.sha256(canonical(snapshot)).hexdigest()
    assert canonical(snapshot).decode() in forwarded['goal']


@pytest.mark.parametrize('existing', [False, True])
def test_prompt_context_missing_or_old_registry_never_migrates(
    tmp_path, monkeypatch, existing, capsys,
):
    database = tmp_path / 'authority.db'
    if existing:
        sqlite3.connect(database).close()
    _configure(monkeypatch, database, tmp_path, tmp_path / 'tracking.db')
    before = _files([database])
    code, raw, payload = _invoke(capsys)
    assert code == 1 and payload['ok'] is False
    assert payload['code'] != 'usage_error'
    assert _files([database]) == before
    assert not (tmp_path / 'tracking.db').exists()
