"""Non-activating orchestration for recoverable frozen planner artifacts."""
from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from algua.contracts.canonical import FROZEN_WIRE, canonical_json
from algua.contracts.frozen_model import FrozenModelAsset
from algua.contracts.model_types import ModelRef
from algua.contracts.planner import PLANNER_PROTOCOL_VERSION
from algua.registry.approvals import compute_artifact_hashes
from algua.registry.artifact_contract import (
    DESCRIPTOR_VERSION,
    PLANNER_BOUNDARY_VERSION,
    BundleDescriptor,
)
from algua.registry.artifact_errors import (
    FrozenAssetsUnsupported,
    FrozenBundleCorrupt,
    FrozenDescriptorConflict,
    FrozenEnvironmentCorrupt,
    FrozenEnvironmentIncompatible,
    FrozenEnvironmentUnavailable,
    FrozenSourceDrift,
    FrozenSourceInvalid,
)
from algua.registry.artifact_recording import frozen_deployment_manifest
from algua.registry.artifact_store import ArtifactStoreError, publish_bundle
from algua.registry.deployment import DeploymentError
from algua.registry.environment_contract import EnvironmentDescriptor
from algua.registry.environment_store import EnvironmentStoreError, publish_environment
from algua.registry.frozen_manifest_contract import FrozenManifest
from algua.registry.frozen_model_assets import pack_model
from algua.registry.frozen_source import (
    FrozenAssetsUnsupported as SourceAssetsUnsupported,
)
from algua.registry.frozen_source import (
    FrozenFile,
    FrozenSourceError,
    assert_clean_head,
    export_build_inputs,
    export_source,
    require_source_only,
)
from algua.registry.planner_environment import (
    EnvironmentIncompatible,
    EnvironmentUnavailable,
    build_environment_key,
    installer_version,
    provision_environment,
)
from algua.registry.repository import ArtifactIdentity
from algua.registry.store import SqliteStrategyRepository
from algua.strategies.frozen_model import load_frozen_model_strategy
from algua.strategies.loader import load_strategy, load_strategy_config, load_tradable_strategy


@dataclass(frozen=True)
class FrozenPreparationResult:
    strategy: str
    artifact_id: int
    research_gate_id: int
    manifest: FrozenManifest


def _generated(path: str, value: object) -> FrozenFile:
    return FrozenFile(path, "100644", canonical_json(value).encode())


def _bundle_files(
    source: tuple[FrozenFile, ...], resolved_config: dict,
    *, model_asset: FrozenModelAsset | None = None,
) -> tuple[FrozenFile, ...]:
    protocol = {
        "descriptor_version": DESCRIPTOR_VERSION,
        "planner_boundary_version": PLANNER_BOUNDARY_VERSION,
        "planner_protocol_version": PLANNER_PROTOCOL_VERSION,
        "frozen_wire": FROZEN_WIRE,
    }
    if model_asset is not None:
        protocol.update(descriptor_version=2, planner_boundary_version=2,
                        planner_protocol_version=2,
                        frozen_wire={'name': 'frozen-planner', 'version': 2},
                        strategy_interface='context_v1', model_asset=model_asset.to_dict())
    files = source + (
        _generated("_algua/resolved-config.json", resolved_config),
        _generated("_algua/protocol.json", protocol),
    )
    return tuple(sorted(files, key=lambda item: item.path.encode()))


def _require_same_identity(actual: ArtifactIdentity, expected: ArtifactIdentity) -> None:
    if actual != expected:
        raise FrozenSourceDrift()


def prepare_frozen_artifact(
    repo: SqliteStrategyRepository,
    name: str,
    *,
    repo_root: Path,
    store_root: Path,
) -> FrozenPreparationResult:
    """Publish and record one exact qualified artifact, without activating it."""
    root = repo_root.resolve()
    model_asset = None
    model_files: tuple[FrozenFile, ...] = ()
    try:
        source_ref = assert_clean_head(root)
        declared_config = load_strategy_config(name)
        has_model = declared_config.needs_model or declared_config.model_ref is not None
        if has_model and not isinstance(declared_config.model_ref, ModelRef):
            raise SourceAssetsUnsupported(
                "frozen planner assets are unsupported in this cycle")
        identity = compute_artifact_hashes(name)
        if identity.dependency_hash is None:
            raise FrozenSourceDrift()
        if has_model:
            captured = load_strategy(name)
            if captured.model_handle is None:
                raise SourceAssetsUnsupported('missing pinned model')
            strategy = load_frozen_model_strategy(name, model=captured.model_handle)
            model_asset, model_files = pack_model(captured.model_handle)
        else:
            strategy = load_tradable_strategy(name)
            require_source_only(strategy.model_handle)
        qualification = repo.qualify_frozen_candidate(
            name, code_hash=identity.code_hash, config_hash=identity.config_hash,
            dependency_hash=identity.dependency_hash,
        )
    except SourceAssetsUnsupported as exc:
        raise FrozenAssetsUnsupported() from exc
    except FrozenSourceDrift:
        raise
    except (FrozenSourceError, DeploymentError, LookupError, ValueError) as exc:
        raise FrozenSourceDrift() from exc
    try:
        dumped = strategy.config.model_dump(mode="json")
        resolved_config = json.loads(canonical_json(dumped))
    except (TypeError, ValueError) as exc:
        raise FrozenSourceInvalid() from exc
    if resolved_config != dumped:
        # Canonical JSON NFC-normalises text but config_hash hashes it raw: a decomposed string
        # would record a config that never re-hashes to identity.config_hash (Story 1.3c §2), so
        # it would be admitted and then refused at every tick. Refuse it before publishing.
        raise FrozenSourceInvalid()
    try:
        source = export_source(root, source_ref)
        build_inputs = export_build_inputs(root, source_ref)
    except (FrozenSourceError, OSError, ValueError) as exc:
        raise FrozenSourceInvalid() from exc
    try:
        bundle_files = _bundle_files(source + model_files, resolved_config, model_asset=model_asset)
        bundle = BundleDescriptor.from_files(
            tuple(item.contract_entry for item in bundle_files))
        publish_bundle(store_root, bundle_files, bundle)
    except (ArtifactStoreError, OSError, ValueError) as exc:
        raise FrozenBundleCorrupt() from exc

    try:
        key = build_environment_key(
            build_inputs, identity.dependency_hash, uv_version=installer_version())
    except EnvironmentUnavailable as exc:
        raise FrozenEnvironmentUnavailable() from exc
    except (EnvironmentIncompatible, OSError, ValueError) as exc:
        raise FrozenEnvironmentIncompatible() from exc
    try:
        staging_parent = store_root.resolve() / "frozen/.staging"
        staging_parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        work = Path(tempfile.mkdtemp(prefix="prepare-", dir=staging_parent))
    except OSError as exc:
        raise FrozenEnvironmentIncompatible() from exc
    try:
        try:
            inventory = provision_environment(
                work / "inputs", work / "environment", build_inputs, key)
        except EnvironmentUnavailable as exc:
            raise FrozenEnvironmentUnavailable() from exc
        except (EnvironmentIncompatible, OSError, ValueError) as exc:
            raise FrozenEnvironmentIncompatible() from exc
        try:
            environment = EnvironmentDescriptor(key, inventory.digest, key.interpreter)
            publish_environment(store_root, work / "environment", environment)
        except (EnvironmentStoreError, OSError, ValueError) as exc:
            raise FrozenEnvironmentCorrupt() from exc
    finally:
        shutil.rmtree(work, ignore_errors=True)

    frozen = FrozenManifest(
        source_ref=source_ref, code_hash=identity.code_hash, config_hash=identity.config_hash,
        dependency_hash=identity.dependency_hash, resolved_config=resolved_config,
        universe_name=qualification.universe_name, bundle=bundle, environment=environment,
        strategy_interface=getattr(strategy, 'strategy_interface', 'legacy'),
        model_asset=model_asset,
    )
    try:
        def final_revalidation() -> None:
            _require_same_identity(compute_artifact_hashes(name), identity)
            if assert_clean_head(root) != source_ref:
                raise FrozenSourceDrift()
            if model_asset is not None:
                fresh = load_strategy(name).model_handle
                if fresh is None or pack_model(fresh) != (model_asset, model_files):
                    raise FrozenSourceDrift()

        artifact_id = repo.record_frozen_artifact(
            name, frozen_deployment_manifest(frozen),
            research_gate_id=qualification.research_gate_id,
            pre_begin_check=final_revalidation,
        )
    except FrozenDescriptorConflict:
        raise
    except FrozenSourceDrift:
        raise
    except (FrozenSourceError, DeploymentError, LookupError, ValueError) as exc:
        raise FrozenSourceDrift() from exc
    return FrozenPreparationResult(
        strategy=name, artifact_id=artifact_id,
        research_gate_id=qualification.research_gate_id, manifest=frozen,
    )
