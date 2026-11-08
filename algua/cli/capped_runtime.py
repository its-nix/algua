"""CLI data composition seam for frozen human authority; lower lanes never read market data."""

from algua.registry import live_gate
from algua.registry.capped_auth import verify
from algua.registry.capped_context import frozen_tenant
from algua.registry.store import SqliteStrategyRepository


def verify_live_authorization(conn, repo, name, allowed_signers_path):
    return live_gate.verify_live_authorization(
        conn, repo, name, allowed_signers_path, frozen_verifier=verify
    )


def live_resume_view(conn, name, loader):
    repo = SqliteStrategyRepository(conn)
    deployment = repo.active_deployment(repo.get(name).id)
    if deployment is not None and deployment.source_kind == "frozen":
        return frozen_tenant(conn, name).view
    return loader(name)
