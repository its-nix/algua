"""Construct one frozen paper planner from a verified tenant and the captured bars identity."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from algua.live.frozen_attempt import Record
from algua.live.frozen_dispatch import FrozenPlanner, FrozenTarget
from algua.live.frozen_wire import WireIdentity
from algua.registry.frozen_runtime import FrozenTenant, PaperTenant


def build_frozen_planner(
    tenant: PaperTenant,
    snapshot_id: str | None,
    bounds: tuple[datetime, datetime],
    *,
    data_dir: Path,
    record: Record,
) -> FrozenPlanner | None:
    if not isinstance(tenant, FrozenTenant):
        return None
    if not snapshot_id:
        raise ValueError(f"{tenant.name}: a frozen tick needs a bars snapshot id")
    manifest, view = tenant.manifest, tenant.view
    version = manifest.to_dict()["planner_protocol_version"]
    identity = WireIdentity(
        tenant.name,
        tenant.deployment_id,
        tenant.artifact_id,
        tenant.deployment.manifest_digest,
        manifest.bundle.digest,
        manifest.environment.digest,
        protocol_version=version,
    )
    target = FrozenTarget(
        identity,
        tenant.bundle_root,
        tenant.environment_root,
        tenant.interpreter,
        view.execution,
        tuple(view.universe),
    )
    return FrozenPlanner(
        target,
        invocations_root=data_dir / "frozen/invocations",
        record=record,
        snapshot_id=snapshot_id,
        bars_start=bounds[0].isoformat(),
        bars_end=bounds[1].isoformat(),
    )
