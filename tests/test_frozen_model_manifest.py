"""Model descriptors are explicit v2 content; existing v1 goldens remain authoritative."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from algua.contracts.canonical import canonical_json
from algua.contracts.model_types import ModelHandle
from algua.contracts.types import ExecutionContract
from algua.features.price_linear_context import score_price_linear
from algua.portfolio.construction import get_construction_policy
from algua.registry.artifact_manifest import parse_frozen_manifest
from algua.registry.artifact_recording import (
    frozen_deployment_manifest,
    parse_frozen_deployment_manifest,
)
from algua.registry.frozen_model_assets import pack_model
from algua.registry.frozen_view import decode_frozen_config
from algua.strategies.base import LoadedStrategy, StrategyConfig, config_hash, strategy_config_hash
from tests.test_frozen_artifact_contract import _manifest
from tests.test_trained_model_context import trained as trained


def model_strategy(trained) -> LoadedStrategy:
    version, raw = trained[-2:]
    config = StrategyConfig(
        name='frozen_context_model', universe=['AAA', 'BBB'],
        execution=ExecutionContract(rebalance_frequency='1d', warmup_bars=5),
        construction='top_k_equal_weight', construction_params={'top_k': 1},
        needs_model=True, model_ref=version.as_ref(), feature_lookback=5)
    return LoadedStrategy(
        config, get_construction_policy(config.construction), strategy_interface='context_v1',
        score_fn=lambda ctx: score_price_linear(ctx, model_key=version.name),
        model_handle=ModelHandle(version, raw))


def model_manifest(trained):
    strategy = model_strategy(trained)
    asset, _ = pack_model(strategy.model_handle)
    return replace(_manifest(), config_hash=config_hash(strategy),
                   resolved_config=strategy.config.model_dump(mode='json'),
                   strategy_interface='context_v1', model_asset=asset)


def test_v2_model_manifest_roundtrip(trained):
    manifest = model_manifest(trained)
    assert manifest.to_dict()['descriptor_version'] == 2
    assert manifest.to_dict()['planner_boundary_version'] == 2
    assert manifest.to_dict()['planner_protocol_version'] == 2
    assert manifest.to_dict()['frozen_wire'] == {'name': 'frozen-planner', 'version': 2}
    assert parse_frozen_manifest(manifest.json) == manifest
    assert parse_frozen_deployment_manifest(frozen_deployment_manifest(manifest)) == manifest
    assert decode_frozen_config(manifest).model_ref == manifest.model_asset.ref


def test_ledger_asset_projection_cannot_disagree(trained):
    manifest = model_manifest(trained)
    record = frozen_deployment_manifest(manifest)
    assert record.asset_digests_json == canonical_json(manifest.to_dict()['assets'])
    with pytest.raises(ValueError, match='disagree'):
        parse_frozen_deployment_manifest(replace(record, asset_digests_json='[]'))


def test_context_interface_is_required_for_config_hash(trained):
    strategy = model_strategy(trained)
    assert strategy_config_hash(strategy.config, strategy_interface='context_v1') == config_hash(
        strategy)
    manifest = model_manifest(trained)
    with pytest.raises(ValueError, match='hash'):
        decode_frozen_config(replace(manifest, config_hash=strategy_config_hash(strategy.config)))


@pytest.mark.parametrize('field,value', [('descriptor_version', 1), ('planner_protocol_version', 1),
    ('planner_boundary_version', 1), ('strategy_interface', 'legacy'), ('assets', []),
    ('frozen_wire', {'name': 'frozen-planner', 'version': 1})])
def test_unknown_mixed_or_downgraded_profile_refuses(trained, field, value):
    raw = model_manifest(trained).to_dict()
    raw[field] = value
    with pytest.raises(ValueError):
        parse_frozen_manifest(canonical_json(raw))


def test_verification_does_not_accept_a_descriptor_without_its_model(
    trained, tmp_path, monkeypatch,
):
    from algua.registry.artifact_errors import FrozenBundleCorrupt
    from algua.registry.artifact_verification import verify_frozen_artifact

    manifest = model_manifest(trained)
    record = SimpleNamespace(id=1, frozen_manifest=lambda: manifest)
    repo = SimpleNamespace(deployment_artifact_by_digest=lambda digest: record)
    monkeypatch.setattr('algua.registry.artifact_verification.verify_bundle',
                        lambda root, descriptor: tmp_path)
    monkeypatch.setattr('algua.registry.artifact_verification.verify_published_environment',
                        lambda root, descriptor: None)
    with pytest.raises(FrozenBundleCorrupt):
        verify_frozen_artifact(repo, manifest.digest, store_root=tmp_path)
