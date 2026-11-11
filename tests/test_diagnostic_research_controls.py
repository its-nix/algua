"""Controls may broaden construction without changing the traded profile or gate authority."""
from __future__ import annotations

import json
from dataclasses import replace

import pytest
from typer.testing import CliRunner

from algua.cli.main import app
from algua.evaluation import experiment_preflight as preflight
from algua.portfolio.construction import get_construction_policy
from algua.strategies.loader import load_strategy


@pytest.fixture
def experiment(monkeypatch, tmp_path):
    original = load_strategy('cross_sectional_momentum')
    primary = replace(original, config=original.config.model_copy(update={'name': 'primary'}))
    control = replace(original, construct_fn=get_construction_policy('equal_weight_positive'),
        config=original.config.model_copy(update={
        'name': 'control', 'construction': 'equal_weight_positive', 'construction_params': {},
        'params': {**original.config.params, 'evaluation_role': 'benchmark',
                   'benchmark_for': 'primary'}}))
    strategies = {'primary': primary, 'control': control}
    monkeypatch.setattr(preflight, 'load_strategy', lambda name, **_: strategies[name])
    execution = original.config.execution
    profile = {'snapshot_id': 'pinned', 'start': '2024-01-01', 'end': '2025-01-01',
        'windows': 4, 'holdout_frac': 0.2, 'symbols': original.config.universe,
        'execution': {'construction': 'top_k_equal_weight', 'top_k': 3,
            **{k: getattr(execution, k) for k in
               ('decision_lag_bars', 'max_weight_per_symbol', 'fees', 'slippage')}}}
    monkeypatch.setattr(preflight, 'load_research_profile', lambda _: profile)
    monkeypatch.setenv('ALGUA_RESEARCH_PROFILE', '/verified-profile')
    monkeypatch.setenv('ALGUA_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('ALGUA_DB_PATH', str(tmp_path / 'unused.db'))
    common = {'action': 'sweep', 'snapshot': 'pinned', 'start': profile['start'],
              'end': profile['end'], 'param': ['lookback=60'],
              'required_window_metrics': ['total_return']}
    tasks = [dict(common, name='primary'), dict(common, name='control',
             evaluation_role='benchmark', benchmark_for='primary')]
    return tasks, strategies


def test_broad_control_preflights_and_dispatches_bound_role(experiment, monkeypatch, tmp_path):
    from algua.cli import research_batch_cmd as batch

    tasks, _ = experiment
    tasks.insert(0, {k: v for k, v in tasks[0].items()
                     if k not in {'param', 'required_window_metrics'}} | {'action': 'backtest'})
    calls = []
    def numeric(name, **kwargs):
        if name == 'control':
            assert kwargs['evaluation_role'] == 'benchmark' and kwargs['benchmark_for'] == 'primary'
        assert 'required_window_metrics' not in kwargs
        calls.append(name)
        return {'measured': True}
    monkeypatch.setitem(batch._DISPATCH, 'sweep', numeric)
    monkeypatch.setitem(batch._DISPATCH, 'backtest', numeric)
    path = tmp_path / 'tasks.json'
    path.write_text(json.dumps(tasks))
    result = CliRunner().invoke(app, ['research', 'run-all', '--tasks', str(path)])
    assert result.exit_code == 0, result.stdout
    assert calls == ['primary', 'primary', 'control']
    assert json.loads(result.stdout)['results'][2]['evaluation_role'] == 'benchmark'
    assert not (tmp_path / 'unused.db').exists()


@pytest.mark.parametrize('change', [
    {'evaluation_role': 'strategy'}, {'benchmark_for': 'missing'},
    {'windows': 3}, {'snapshot': 'other'}, {'action': 'promote'}, {'action': 'backtest'},
])
def test_invalid_benchmark_stops_before_numerical_work(experiment, monkeypatch, tmp_path, change):
    from algua.cli import research_batch_cmd as batch

    tasks, _ = experiment
    tasks[1].update(change)
    calls = []
    monkeypatch.setitem(batch._DISPATCH, 'sweep', lambda *a, **k: calls.append(1))
    path = tmp_path / 'tasks.json'
    path.write_text(json.dumps(tasks))
    result = CliRunner().invoke(app, ['research', 'run-all', '--tasks', str(path)])
    assert result.exit_code == 1 and json.loads(result.stdout)['ok'] is False
    assert calls == [] and not (tmp_path / 'unused.db').exists()


def test_different_embargo_refuses_unpaired_windows(experiment):
    tasks, strategies = experiment
    control = strategies['control']
    strategies['control'] = replace(control, config=control.config.model_copy(
        update={'feature_lookback': 0}))
    with pytest.raises(ValueError, match='identical research windows'):
        preflight.preflight_experiment(tasks, check_strategies=True)


def test_benchmark_marker_cannot_be_stripped_or_retargeted(experiment):
    tasks, strategies = experiment
    control = strategies['control']
    strategies['control'] = replace(control, config=control.config.model_copy(update={
        'params': {**control.config.params, 'benchmark_for': 'different'}}))
    with pytest.raises(ValueError, match='CONFIG.params'):
        preflight.preflight_experiment(tasks, check_strategies=True)


def test_ordinary_evaluation_cannot_register_or_promote_a_marked_control(experiment, monkeypatch):
    from algua.evaluation import inputs

    _, strategies = experiment
    monkeypatch.setattr(inputs, 'load_strategy', lambda *a, **k: strategies['control'])
    # Backtest registration, walk-forward and promotion share this default resolver.
    with pytest.raises(ValueError, match='no promotion'):
        inputs.resolve_eval_inputs('control', False, 'pinned', '2024-01-01', '2025-01-01')
    from algua.registry.promote_run import promote_task
    with pytest.raises(ValueError, match='no promotion'):
        promote_task('control', snapshot='pinned')


def test_benchmark_role_and_target_survive_trial_archive_inputs(tmp_path, monkeypatch):
    from algua.evaluation import inputs
    from algua.evaluation.sweep_run import sweep_task
    from algua.operator.research_memory_inputs import public_memory_inputs
    from algua.registry.db import registry_conn
    from tests.test_run_provenance import END, NAME, START, snapshot

    store, rec = snapshot(tmp_path, monkeypatch)
    strategy = load_strategy(NAME)
    role = {'evaluation_role': 'benchmark', 'benchmark_for': 'primary'}
    strategy = replace(strategy, construct_fn=get_construction_policy('equal_weight_positive'),
        config=strategy.config.model_copy(update={
        'construction': 'equal_weight_positive', 'construction_params': {},
        'params': {**strategy.config.params, **role}}))
    monkeypatch.setenv('ALGUA_RESEARCH_PROFILE', '/verified-profile-by-batch')
    monkeypatch.setattr(inputs, 'load_strategy', lambda *a, **k: strategy)
    result = sweep_task(NAME, snapshot=rec.snapshot_id, start=START, end=END,
        param=['lookback=60'], windows=2, evaluation_role='benchmark', benchmark_for='primary')
    assert result['n_combos'] == 1
    with registry_conn() as conn:
        config = json.loads(conn.execute(
            "SELECT config_json FROM runs WHERE kind='sweep_trial'").fetchone()[0])
        assert conn.execute('SELECT COUNT(*) FROM strategies').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM holdout_evaluations').fetchone()[0] == 0
    retained = public_memory_inputs('sweep_trial', config)
    assert role.items() <= retained['params'].items()
    assert retained['public_window_record']['params'] == retained['params']
