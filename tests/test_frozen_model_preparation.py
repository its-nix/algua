"""Model preparation publishes portable content and revalidates the captured pin before record."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from algua.contracts.frozen_model import MODEL_ARTIFACT
from algua.registry import artifact_preparation as preparation
from algua.registry.artifact_errors import FrozenSourceDrift
from algua.registry.artifact_store import verify_bundle
from algua.registry.db import connect, migrate
from algua.registry.frozen_model_assets import read_bundle_model
from algua.registry.frozen_source import FrozenFile
from algua.registry.repository import ArtifactIdentity
from algua.registry.store import SqliteStrategyRepository
from algua.strategies.base import config_hash
from tests.test_frozen_artifact_ledger import _candidate, _frozen_manifest
from tests.test_frozen_model_manifest import model_strategy
from tests.test_trained_model_context import trained as trained


@pytest.mark.parametrize('drift', [False, True])
def test_prepare_model_content_and_pin_revalidation(trained, tmp_path, monkeypatch, drift):
    strategy = model_strategy(trained)
    strategy = replace(strategy, config=strategy.config.model_copy(update={'name': 's'}))
    expected = replace(_frozen_manifest(), config_hash=config_hash(strategy))
    conn = connect(tmp_path / 'prepare.db')
    migrate(conn)
    repo = SqliteStrategyRepository(conn)
    _candidate(repo, expected)
    identity = ArtifactIdentity(expected.code_hash, expected.config_hash, expected.dependency_hash)
    calls = []

    def load(name):
        calls.append(name)
        if drift and len(calls) > 1:
            raise ValueError('captured model pin changed')
        return strategy

    monkeypatch.setattr(preparation, 'assert_clean_head', lambda root: expected.source_ref)
    monkeypatch.setattr(preparation, 'load_strategy_config', lambda name: strategy.config)
    monkeypatch.setattr(preparation, 'load_strategy', load)
    monkeypatch.setattr(preparation, 'load_frozen_model_strategy', lambda name, model: strategy)
    monkeypatch.setattr(preparation, 'compute_artifact_hashes', lambda name: identity)
    monkeypatch.setattr(preparation, 'export_source', lambda *args: (
        FrozenFile('algua/__init__.py', '100644', b''),))
    monkeypatch.setattr(preparation, 'export_build_inputs', lambda *args: ())
    monkeypatch.setattr(preparation, 'installer_version', lambda: 'uv fixture')
    monkeypatch.setattr(preparation, 'build_environment_key', lambda *args, **kw:
                        expected.environment.key)
    monkeypatch.setattr(preparation, 'provision_environment', lambda *args:
                        SimpleNamespace(digest=expected.environment.inventory_digest))
    monkeypatch.setattr(preparation, 'publish_environment', lambda *args: tmp_path)
    try:
        if drift:
            with pytest.raises(FrozenSourceDrift):
                preparation.prepare_frozen_artifact(repo, 's', repo_root=tmp_path,
                                                    store_root=tmp_path / 'published')
            assert conn.execute('SELECT COUNT(*) FROM deployment_artifacts').fetchone()[0] == 0
        else:
            result = preparation.prepare_frozen_artifact(repo, 's', repo_root=tmp_path,
                                                         store_root=tmp_path / 'published')
            root = verify_bundle(tmp_path / 'published', result.manifest.bundle)
            assert (root / MODEL_ARTIFACT).read_bytes() == trained[-1]
            assert read_bundle_model(root, result.manifest.model_asset).version.as_ref() == (
                strategy.config.model_ref)
            assert result.manifest.to_dict()['planner_protocol_version'] == 2
        assert calls == ['s', 's']
        assert conn.execute('SELECT COUNT(*) FROM strategy_deployments').fetchone()[0] == 0
    finally:
        conn.close()
