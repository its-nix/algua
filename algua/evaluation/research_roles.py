"""Diagnostic task roles are public inputs, never qualification authority."""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

TASK_METADATA = frozenset({'required_window_metrics', 'evaluation_role', 'benchmark_for'})


def task_role(task: dict[str, Any]) -> str:
    role = task.get('evaluation_role', 'strategy')
    if role not in {'strategy', 'benchmark'}:
        raise ValueError('evaluation_role must be strategy or benchmark')
    if role == 'benchmark':
        if (task['action'] != 'sweep' or not task.get('benchmark_for')
                or task['benchmark_for'] == task['name']):
            raise ValueError('benchmark requires a sweep and a distinct benchmark_for strategy')
    elif 'benchmark_for' in task:
        raise ValueError('benchmark_for requires evaluation_role=benchmark')
    return role


def construction_matches(config: Any, task: dict, expected: dict) -> bool:
    primary = (config.construction == expected['construction']
               and config.construction_params.get('top_k') == expected['top_k'])
    return primary or (task_role(task) == 'benchmark'
                       and config.construction == 'equal_weight_positive'
                       and config.construction_params == {})


def validate_task_roles(tasks: list[dict]) -> None:
    for task in tasks:
        if task_role(task) != 'benchmark':
            continue
        targets = [t for t in tasks if t['name'] == task['benchmark_for']
                   and t['action'] == 'sweep' and task_role(t) == 'strategy']
        if not targets:
            raise ValueError('benchmark requires its strategy sweep in the same experiment')


def retain_benchmark_grid(grid: dict, role: str, target: str | None) -> dict:
    """Sweep records store searched coordinates; retain fixed diagnostic inputs there too."""
    if role != 'benchmark':
        return grid
    result = dict(grid)
    for key, value in {'evaluation_role': role, 'benchmark_for': target}.items():
        if key in result and result[key] != [value]:
            raise ValueError('benchmark grid cannot change its diagnostic identity')
        result[key] = [value]
    return result


def _windows(task: dict, variants: list) -> set[tuple]:
    result = set()
    for variant in variants:
        config = variant.config
        if config.feature_lookback is None:
            raise ValueError('paired benchmarks require a declared common feature_lookback')
        result.add((task.get('snapshot'), task.get('start'), task.get('end'),
                    task.get('universe'), task.get('windows', 4), task.get('holdout_frac', 0.2),
                    task.get('delistings'), task.get('assume_terminal_last_close', False),
                    json.dumps(asdict(config.execution), sort_keys=True),
                    max(config.feature_lookback, config.execution.decision_lag_bars)))
    return result


def validate_comparisons(tasks: list[dict], variants: list[list], *, configured: bool) -> None:
    for task, configurations in zip(tasks, variants, strict=True):
        role = task_role(task)
        for variant in configurations:
            params = variant.config.params
            if (params.get('evaluation_role', 'strategy') != role
                    or (role == 'benchmark'
                        and params.get('benchmark_for') != task['benchmark_for'])):
                raise ValueError('benchmark role/target must match the recorded CONFIG.params')
        if role != 'benchmark':
            continue
        if not configured:
            raise ValueError('diagnostic benchmarks require a configured exploration profile')
        targets = [(t, v) for t, v in zip(tasks, variants, strict=True)
                   if t['name'] == task['benchmark_for'] and t['action'] == 'sweep'
                   and task_role(t) == 'strategy']
        if not targets or any(_windows(task, configurations) != _windows(t, v) for t, v in targets):
            raise ValueError('benchmark requires a strategy sweep with identical research windows')
