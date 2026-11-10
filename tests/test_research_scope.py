"""Development smoke must not expose the reserved tail."""
from __future__ import annotations

import pytest

from algua.backtest.walkforward import holdout_window
from algua.data.serve import StoreBackedProvider
from algua.evaluation.backtest_run import run_backtest_task
from algua.primitives.timeparse import utc
from algua.strategies.loader import load_strategy
from tests.test_run_provenance import END, NAME, START, SYMBOLS, snapshot


def test_development_backtest_stops_before_holdout_and_records_actual_period(tmp_path, monkeypatch):
    store, rec = snapshot(tmp_path, monkeypatch)
    boundary, _ = holdout_window(load_strategy(NAME), StoreBackedProvider(store, rec.snapshot_id),
                                  utc(START), utc(END), holdout_frac=0.2)
    result = run_backtest_task(NAME, snapshot=rec.snapshot_id, start=START, end=END,
                               research_only=True)
    assert result['period']['end'] == boundary
    assert result['snapshot_id'] == rec.snapshot_id
    assert result['research_scope']['reserved_holdout_start'] == boundary
    from algua.registry.db import registry_conn
    with registry_conn() as conn:
        count = conn.execute('SELECT n_obs_is FROM runs ORDER BY id DESC LIMIT 1').fetchone()[0]
    assert count < len(store.read_bars(rec.snapshot_id).index.unique())


def test_configured_pilot_enforces_development_scope_without_optional_flag(tmp_path, monkeypatch):
    from algua.evaluation import research_scope

    store, rec = snapshot(tmp_path, monkeypatch)
    monkeypatch.setenv('ALGUA_RESEARCH_PROFILE', '/verified-by-profile-loader')
    monkeypatch.setattr(research_scope, 'load_research_profile', lambda *a: {
        'snapshot_id': rec.snapshot_id, 'start': START, 'end': END, 'holdout_frac': 0.2})
    result = run_backtest_task(NAME, snapshot=rec.snapshot_id, start=START, end=END)
    assert result['period']['end'] < END
    assert result['research_scope']['mode'] == 'development_only'


def test_changing_only_reserved_tail_cannot_change_smoke_metrics(tmp_path, monkeypatch):
    store, rec = snapshot(tmp_path, monkeypatch)
    first = run_backtest_task(NAME, snapshot=rec.snapshot_id, start=START, end=END,
                              research_only=True)
    frame = store.read_bars(rec.snapshot_id).reset_index().rename(columns={'timestamp': 'ts'})
    tail = frame['ts'] >= utc(first['research_scope']['reserved_holdout_start'])
    for column in ['open', 'high', 'low', 'close', 'adj_close']:
        frame.loc[tail, column] *= 100
    changed = store.ingest_bars(provider='fixture-tail-change', symbols=SYMBOLS, start=START,
        end=END, as_of='2025-01-02T00:00:00+00:00', source='engineering-fixture', frame=frame)
    second = run_backtest_task(NAME, snapshot=changed.snapshot_id, start=START, end=END,
                               research_only=True)
    assert first['metrics'] == second['metrics']
    assert first['period'] == second['period']


def test_development_scope_refuses_demo_without_immutable_snapshot():
    with pytest.raises(ValueError, match='immutable bars snapshot'):
        run_backtest_task(NAME, demo=True, start=START, end=END, research_only=True)
