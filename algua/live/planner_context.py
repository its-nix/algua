"""Supervisor-verified identity copied into an authority-free planner request."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PlannerContext:
    """Supervisor-verified identity values copied into one planner request."""

    deployment_id: int | None
    artifact_id: int | None
    manifest_digest: str | None
    config_hash: str
    resolved_config_json: str
    calendar_code: str
    protocol_version: int = 1
    bars_snapshot_id: str | None = None


def planner_context_for_deployment(
    deployment: Any, calendar_code: str, *, bars_snapshot_id: str | None = None,
) -> PlannerContext | None:
    """Copy an already-verified deployment record into the authority-free planner envelope."""
    if deployment is None:
        return None
    return PlannerContext(
        deployment.id,
        deployment.artifact_id,
        deployment.manifest_digest,
        deployment.config_hash,
        deployment.resolved_config_json,
        calendar_code,
        getattr(deployment, "planner_protocol_version", 1),
        bars_snapshot_id,
    )


