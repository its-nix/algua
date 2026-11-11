"""Narrow bundle-model binding without host model resolution or training."""
from __future__ import annotations

import importlib
import shutil
from dataclasses import replace

import pytest

from algua.contracts.model_types import ModelHandle
from algua.data.store import DataStore
from algua.registry.frozen_model_assets import pack_model, read_bundle_model
from algua.strategies.loader import load_tradable_strategy
from tests.test_trained_model_context import authored
from tests.test_trained_model_context import trained as trained


def test_bundle_model_loads_without_host_registry(trained, tmp_path, monkeypatch):
    from algua.strategies.frozen_model import load_frozen_model_strategy

    data, _, _, _, _, version, raw = trained
    asset, files = pack_model(ModelHandle(version, raw))
    for file in files:
        path = tmp_path / 'bundle' / file.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(file.data)
    model = read_bundle_model(tmp_path / 'bundle', asset)
    shutil.rmtree(data / 'models')

    def forbidden(*args, **kwargs):
        pytest.fail('frozen model loading reached the host registry or training')

    monkeypatch.setattr('algua.models.get_version_with_bytes', forbidden)
    monkeypatch.setattr('algua.training.price_linear.fit_price_linear', forbidden)
    with authored(version, name='tmp_frozen_bundle_model') as name:
        strategy = load_frozen_model_strategy(name, model=model)
        assert strategy.model_handle.artifact_bytes == raw
        assert strategy.config.model_ref == version.as_ref()
        monkeypatch.setattr('algua.strategies.loader._resolve_model_handle',
                            lambda _name, _config: model)
        with pytest.raises(ValueError, match='paper/live/frozen'):
            load_tradable_strategy(name)


def test_loaded_model_still_obeys_bound_pin(trained):
    from algua.strategies.frozen_model import load_frozen_model_strategy

    version, raw = trained[-2:]
    with authored(version, name='tmp_frozen_wrong_pin') as name:
        wrong = ModelHandle(replace(version, version=version.version + 1), raw)
        with pytest.raises((ValueError, LookupError), match='pin|match'):
            load_frozen_model_strategy(name, model=wrong)


def test_future_training_cutoff_refuses_context(trained):
    from algua.strategies.context_inputs import build_context
    from algua.strategies.frozen_model import load_frozen_model_strategy

    data, _, record, dates, _, version, raw = trained
    with authored(version, name='tmp_frozen_future_model') as name:
        strategy = load_frozen_model_strategy(name, model=ModelHandle(version, raw))
        with pytest.raises(ValueError, match='first decision'):
            build_context(strategy, decision_ts=dates[23], first_decision_ts=dates[0],
                universe=['AAA', 'BBB'],
                bars=DataStore(data).read_bars(record.snapshot_id).loc[:dates[23]],
                bars_snapshot_id=record.snapshot_id, fundamentals=None,
                fundamentals_snapshot_id=None, news=None, news_snapshot_id=None)


@pytest.mark.parametrize('field', ['needs_news', 'needs_fundamentals'])
def test_unsupported_sidecars_remain_refused(trained, monkeypatch, field):
    from algua.strategies.frozen_model import load_frozen_model_strategy

    version, raw = trained[-2:]
    with authored(version, name='tmp_frozen_sidecar_model') as name:
        module = importlib.import_module(f'algua.strategies.momentum.{name}')
        monkeypatch.setattr(module, 'CONFIG', module.CONFIG.model_copy(update={field: True}))
        with pytest.raises(ValueError, match='unsupported|bars'):
            load_frozen_model_strategy(name, model=ModelHandle(version, raw))


def test_model_bundle_stamp_binds_portable_asset(trained):
    import json

    from algua.registry.artifact_preparation import _bundle_files
    from tests.test_frozen_model_manifest import model_manifest

    manifest = model_manifest(trained)
    files = _bundle_files((), manifest.resolved_config, model_asset=manifest.model_asset)
    protocol = json.loads(next(file.data for file in files if file.path == '_algua/protocol.json'))
    assert protocol['model_asset'] == manifest.model_asset.to_dict()
    assert protocol['strategy_interface'] == 'context_v1'
    assert protocol['frozen_wire'] == {'name': 'frozen-planner', 'version': 2}
