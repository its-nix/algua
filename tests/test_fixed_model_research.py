"""A fixed pre-period model may be evaluated chronologically, without fitting or reloading."""
from __future__ import annotations

import shutil
from dataclasses import replace

import pandas as pd
import pytest

from algua.backtest.errors import BacktestError
from algua.backtest.sweep import sweep
from algua.backtest.walkforward import holdout_window, walk_forward
from algua.data.serve import StoreBackedProvider
from algua.data.store import DataStore
from algua.features.price_linear_context import score_price_linear
from tests.test_frozen_model_manifest import model_strategy
from tests.test_trained_model_context import trained as trained


def _score_model(context):
    return score_price_linear(context, model_key='context-model')


def test_fixed_model_walkforward_and_sweep_retain_pin_without_fit_or_store(trained, monkeypatch):
    import algua.models.registry as registry
    import algua.training.price_linear as training

    strategy = replace(model_strategy(trained), score_fn=_score_model)
    data, _, record, dates, *_ = trained
    provider = StoreBackedProvider(DataStore(data), record.snapshot_id)
    pin = strategy.config.model_ref
    shutil.rmtree(data / 'models')

    def forbidden(*args, **kwargs):
        pytest.fail('fixed-model evaluation must neither fit nor reload a model')

    monkeypatch.setattr(training, 'fit_price_linear', forbidden)
    monkeypatch.setattr(registry, 'get_version_with_bytes', forbidden)
    start = dates[16].to_pydatetime()
    end = (dates[-1] + pd.Timedelta(days=1)).to_pydatetime()
    burned = []
    result = walk_forward(strategy, provider, start, end, windows=2, embargo=0,
                          on_peek=burned.append)
    assert len(burned) == 1
    assert result.holdout_metrics['n_bars'] > 0
    ranked = sweep(strategy, provider, start, end, windows=2,
                   grid={'construction.top_k': [1, 2]})
    assert ranked.n_combos == 2
    assert all('holdout' not in row for row in ranked.to_dict()['ranked'])
    assert strategy.config.model_ref == pin
    assert result.to_dict()['model_ref'] == pin.as_dict()
    assert ranked.to_dict()['model_ref'] == pin.as_dict()
    import json

    from algua.registry.db import connect, migrate
    from algua.registry.runs import record_sweep_run, record_walk_forward_run
    from algua.registry.store import SqliteStrategyRepository
    conn = connect(data / 'lineage.db')
    migrate(conn)
    repo = SqliteStrategyRepository(conn)
    wf_id = record_walk_forward_run(repo, strategy.name, result)
    sweep_id = record_sweep_run(repo, strategy.name, ranked)['run_id']
    for rid in (wf_id, sweep_id):
        assert json.loads(repo.get_run(rid)['components']) == [pin.as_dict()]
        raw = conn.execute('SELECT components FROM runs WHERE id=?', (rid,)).fetchone()
        assert json.loads(raw['components']) == [pin.as_dict()]
    conn.close()


@pytest.mark.parametrize('method', ['walk', 'sweep', 'reserve'])
@pytest.mark.parametrize('fault', ['future', 'unsupported_modality'])
def test_ineligible_fixed_model_refuses_before_data_or_holdout(trained, method, fault):
    strategy = model_strategy(trained)
    start = trained[3][16].to_pydatetime()
    if fault == 'future':
        start = trained[3][1].to_pydatetime()
    else:
        strategy = replace(strategy, config=strategy.config.model_copy(update={'needs_news': True}))

    class ForbiddenProvider:
        def get_bars(self, *args, **kwargs):
            pytest.fail('model profile must refuse before data or holdout use')

    with pytest.raises(BacktestError):
        if method == 'walk':
            walk_forward(strategy, ForbiddenProvider(), start, trained[3][-1].to_pydatetime(),
                         windows=2, on_peek=lambda _: pytest.fail('must not burn'))
        elif method == 'reserve':
            holdout_window(strategy, ForbiddenProvider(), start,
                           trained[3][-1].to_pydatetime(), holdout_frac=0.2)
        else:
            sweep(strategy, ForbiddenProvider(), start, trained[3][-1].to_pydatetime(),
                  windows=2, grid={'construction.top_k': [1]})


@pytest.mark.parametrize('fault', ['extra','bool_version','bad_digest','many'])
def test_public_model_lineage_refuses_noncanonical_or_extra_payload(fault):
    from algua.provenance.research_disclosure import public_model_components
    pin = {'name':'fixed','version':1,'digest':'a'*16,'training_as_of':'2020-01-01',
           'provenance_digest':'b'*16}
    assert public_model_components([pin]) == [pin]
    if fault == 'extra':
        pin['holdout_returns'] = [0.2]
    elif fault == 'bool_version':
        pin['version'] = True
    elif fault == 'bad_digest':
        pin['digest'] = 'invalid'
    value = [pin,pin] if fault == 'many' else [pin]
    assert public_model_components(value) == []
