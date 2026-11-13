"""Real cold child parity against the canonical research scorer and construction."""
from __future__ import annotations

import shutil

import pandas as pd
import pytest

from algua.features.price_linear_context import score_price_linear
from algua.live.frozen_dispatch import FrozenPlanner, FrozenTarget, FrozenTenantFailure
from algua.live.model_context import build_model_decision_context
from algua.live.planner_contract import Decision, SnapshotRequired
from algua.live.planner_decision import build_intents, canonical_weights
from algua.research.multimodal_context import build_as_of_context
from tests._frozen_harness import frozen_store
from tests.test_frozen_model_wire import identity, model_early, model_late
from tests.test_trained_model_context import authored
from tests.test_trained_model_context import trained as trained

pytestmark = pytest.mark.serial  # writes into the real algua/ source tree


def test_model_scores_weights_and_intents_match_research(trained, tmp_path):
    strategy, early = model_early(trained)
    view = early.raw_bars
    decision_ts = view.index.max().to_pydatetime()
    expected_context = build_as_of_context(decision_ts=decision_ts,
        first_decision_ts=decision_ts, universe=strategy.universe, bars=view,
        bars_snapshot_id=early.bars_snapshot_id, required_features={'bars'},
        model_refs={strategy.config.model_ref.name: strategy.config.model_ref},
        model_registry_root=trained[0] / 'models')
    actual_context = build_model_decision_context(strategy, early, view, decision_ts)
    pd.testing.assert_series_equal(score_price_linear(actual_context, model_key='context-model'),
        score_price_linear(expected_context, model_key='context-model'), rtol=1e-12, atol=1e-12)
    expected = canonical_weights(strategy.target_weights_context(expected_context), strategy.name)
    with authored(trained[-2], name=strategy.name) as name:
        # Use the exact CONFIG of the comparison subject; the source's scorer stays real.
        from pathlib import Path

        import algua.strategies.momentum as family
        source = (Path(family.__path__[0]) / f'{name}.py').read_text()
        config = strategy.config.model_dump(mode='json')
        execution = config.pop('execution')
        config.pop('model_ref')
        source += (f"\nCONFIG = StrategyConfig(**{config!r}, model_ref=REF, "
                   f"execution=ExecutionContract(**{execution!r}))\n")
        with frozen_store(tmp_path / 'store') as store:
            bundle = store.model_bundle(strategy, source)
            shutil.rmtree(trained[0] / 'models')
            target = FrozenTarget(identity(early), bundle, store.environment, store.python,
                                  strategy.execution, tuple(strategy.universe))
            rows = []
            planner = FrozenPlanner(target, invocations_root=tmp_path / 'calls',
                record=lambda attempt: rows.append(attempt) or len(rows),
                snapshot_id=early.bars_snapshot_id, bars_start=None, bars_end=None)
            assert isinstance(planner.phase_a(early), SnapshotRequired)
            result = planner.phase_b(model_late(strategy, early))
    assert isinstance(result, Decision)
    actual = pd.Series(dict(result.state.target_weights), dtype='float64')
    pd.testing.assert_series_equal(actual, expected, check_names=False, rtol=1e-12, atol=1e-12)
    assert result.state.decision_ts == decision_ts
    assert result.ordered_intents == tuple(build_intents(expected, {}, decision_ts))
    assert strategy.execution.decision_lag_bars == 1
    assert len(rows) == 2


def test_cross_version_child_refuses(trained, tmp_path):
    strategy, early = model_early(trained)
    with frozen_store(tmp_path / 'store') as store:
        target = FrozenTarget(identity(early, key='good'), store.bundle('good'),
            store.environment, store.python, strategy.execution, tuple(strategy.universe))
        planner = FrozenPlanner(target, invocations_root=tmp_path / 'calls',
            record=lambda attempt: 1, snapshot_id=early.bars_snapshot_id,
            bars_start=None, bars_end=None)
        with pytest.raises(FrozenTenantFailure):
            planner.phase_a(early)
