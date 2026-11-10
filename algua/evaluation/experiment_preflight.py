"""Check declared experiment outputs before spending numerical trials."""
from __future__ import annotations

import os
from typing import Any

from algua.backtest.sweep import validate_sweep_grid
from algua.backtest.sweep_grid import parse_grid
from algua.config.settings import get_settings
from algua.operator.research_profile import load_research_profile
from algua.strategies.loader import load_strategy

WINDOW_OUTPUTS = frozenset({'total_return', 'sharpe', 'n_bars', 'max_drawdown',
                            'ann_volatility', 'cagr', 'sortino', 'calmar', 'hit_rate'})


def preflight_experiment(tasks: list[dict[str, Any]], *, check_strategies: bool) -> dict:
    profile = (load_research_profile(get_settings().data_dir) if check_strategies
               and os.environ.get('ALGUA_RESEARCH_PROFILE') is not None else None)
    for task in tasks:
        action = task['action']
        required = task.get('required_window_metrics', [])
        if required and (action != 'sweep' or not set(required) <= WINDOW_OUTPUTS):
            raise ValueError(f'{task["name"]}: required window metrics are not observable')
        if action == 'sweep':
            if task.get('windows', 4) < 2 or not 0 < task.get('holdout_frac', 0.2) < 1:
                raise ValueError('experiment requires research windows and a reserved holdout')
            grid = parse_grid(task.get('param') or [])
        else:
            grid = {}
        if profile is not None:
            if action == 'promote' or task.get('demo', False) or (
                    task.get('snapshot'), task.get('start'), task.get('end')) != (
                    profile['snapshot_id'], profile['start'], profile['end']):
                raise ValueError('research_profile:experiment_inputs_mismatch')
            if action == 'sweep' and (task.get('windows', 4), task.get('holdout_frac', 0.2)) != (
                    profile['windows'], profile['holdout_frac']):
                raise ValueError('research_profile:experiment_windows_mismatch')
        if not check_strategies:
            continue  # Plan validation precedes authoring; it cannot certify unbuilt source.
        strategy = load_strategy(task['name'], reload=True)
        _, variants = validate_sweep_grid(strategy, grid)
        for variant in variants:
            for lane in ('fundamentals', 'news'):
                if bool(task.get(f'{lane}_snapshot')) != getattr(variant.config, f'needs_{lane}'):
                    raise ValueError(f'{task["name"]}: {lane} snapshot/declaration mismatch')
        if profile is not None:
            for variant in variants:
                config, expected = variant.config, profile['execution']
                execution = config.execution
                if (sorted(config.universe) != sorted(profile['symbols'])
                    or execution.rebalance_frequency != '1d'
                    or config.construction != expected['construction']
                    or config.construction_params.get('top_k') != expected['top_k']
                    or any(getattr(execution, k) != expected[k] for k in (
                        'decision_lag_bars', 'max_weight_per_symbol', 'fees', 'slippage'))):
                    raise ValueError('research_profile:experiment_strategy_mismatch')
    return {'preflight': True, 'strategy_checked': check_strategies,
            'input_profile_checked': profile is not None,
            'tasks_total': len(tasks), 'required_outputs_supported': True,
            'qualification_authority': False}
