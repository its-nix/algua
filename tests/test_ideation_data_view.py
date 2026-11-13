"""Actual scratch CLI/data view over a verified profile, with no authority writes."""
from __future__ import annotations

import os
import subprocess
import sys

from algua.data.store import DataStore
from algua.operator import research_profile as profile
from tests.test_research_profile import configured as configured


def test_verified_profile_seeds_actual_scratch_lookup_without_registry_or_payload_copy(
        configured, tmp_path, monkeypatch):
    store, record, _, _ = configured
    scratch = tmp_path / 'scratch/data'
    before = {str(p): p.read_bytes() for p in store.data_dir.rglob('*') if p.is_file()}
    profile.seed_ideation_data(store.data_dir, scratch)
    monkeypatch.delenv('ALGUA_RESEARCH_PROFILE')
    env = {**os.environ, 'ALGUA_DATA_DIR': str(scratch),
           'ALGUA_DB_PATH': str(scratch / 'scratch.db')}
    result = subprocess.run([sys.executable, '-c', 'from algua.cli.main import main; main()',
                              'data', 'inspect',
                              '--snapshot-id', record.snapshot_id], env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert record.snapshot_id in result.stdout
    assert DataStore(scratch).read_bars(record.snapshot_id).equals(
        store.read_bars(record.snapshot_id))
    assert (scratch / record.data_path).is_symlink()
    assert not (scratch / 'scratch.db').exists()
    assert before == {str(p): p.read_bytes() for p in store.data_dir.rglob('*') if p.is_file()}


def test_profile_exposes_observed_coverage_instead_of_calendar_estimates(configured):
    store, _, _, _ = configured
    receipt = profile.load_research_profile(store.data_dir)
    coverage = receipt['coverage']
    assert coverage['grid_sessions'] == 2
    assert coverage['complete_symbols'] == 300
    assert len(coverage['symbol_sessions']) == 300
    assert coverage['observed_start'] == '2024-11-01'
    assert coverage['observed_end'] == '2026-11-06'
