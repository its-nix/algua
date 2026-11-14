from dataclasses import replace

import pytest

from algua.evaluation import experiment_preflight as preflight
from algua.operator.research_history import window_capacity
from tests.test_diagnostic_research_controls import experiment as experiment


def test_long_formation_has_zero_capacity_but_short_feature_can_be_tested():
    assert window_capacity(504, lookback=253, lag=1, windows=4, holdout_frac=0.2) == [0]*4
    assert all(n > 0 for n in window_capacity(504, lookback=21, lag=1,
                                             windows=4, holdout_frac=0.2))


def test_authored_long_lookback_refuses_before_numerical_batch(experiment):
    tasks, strategies = experiment
    for name, strategy in list(strategies.items()):
        strategies[name] = replace(strategy, config=strategy.config.model_copy(
            update={'feature_lookback': 253}))
    with pytest.raises(ValueError, match='insufficient_post_warmup'):
        preflight.preflight_experiment(tasks, check_strategies=True)
