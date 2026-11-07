"""Authoritative model-paper execution stays closed pending reviewed strategy isolation."""
from __future__ import annotations

from algua.registry.frozen_manifest_contract import FrozenManifest
from algua.registry.frozen_tenant_errors import FrozenTenantUnsupported


def require_execution_isolation(manifest: FrozenManifest) -> None:
    """There is currently no reviewed authority-denying launch boundary for model strategies.

    Process containment bounds time and output; it grants no execution-isolation capability.
    Artifact preparation/verification remains available for review. No config or CLI switch can
    turn a prepared model bundle into permission for authoritative paper execution.
    """
    if manifest.model_asset is not None:
        raise FrozenTenantUnsupported("model paper requires reviewed execution isolation")
