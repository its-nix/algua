"""Offline verification of recorded frozen planner content."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from algua.registry.artifact_errors import (
    FrozenBundleCorrupt,
    FrozenDescriptorConflict,
    FrozenEnvironmentCorrupt,
)
from algua.registry.artifact_store import ArtifactStoreError, verify_bundle
from algua.registry.deployment import DeploymentError
from algua.registry.environment_store import EnvironmentStoreError, verify_published_environment
from algua.registry.frozen_manifest_contract import FrozenManifest
from algua.registry.frozen_model_assets import read_bundle_model
from algua.registry.store import SqliteStrategyRepository


@dataclass(frozen=True)
class FrozenVerificationResult:
    strategy: str
    artifact_id: int
    manifest: FrozenManifest


def verify_frozen_artifact(
    repo: SqliteStrategyRepository, manifest_digest: str, *, store_root: Path,
) -> FrozenVerificationResult:
    """Verify from the ledger and trusted store only; never repair or rebuild content."""
    record = repo.deployment_artifact_by_digest(manifest_digest)
    try:
        manifest = record.frozen_manifest()
    except DeploymentError as exc:
        raise FrozenDescriptorConflict() from exc
    strategy = manifest.resolved_config.get("name")
    if not isinstance(strategy, str) or not strategy:
        raise FrozenDescriptorConflict()
    try:
        bundle_root = verify_bundle(store_root, manifest.bundle)
        if manifest.model_asset is not None:
            read_bundle_model(bundle_root, manifest.model_asset)
    except (ArtifactStoreError, OSError, ValueError) as exc:
        raise FrozenBundleCorrupt() from exc
    try:
        verify_published_environment(store_root, manifest.environment)
    except (EnvironmentStoreError, OSError, ValueError) as exc:
        raise FrozenEnvironmentCorrupt() from exc
    return FrozenVerificationResult(strategy, record.id, manifest)
