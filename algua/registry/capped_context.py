"""Rebuilt immutable authority context and current experimental envelope checks."""

from __future__ import annotations

from algua.calendar.factory import get_calendar
from algua.config.settings import get_settings
from algua.registry.capped_policy import provider_policy
from algua.registry.capped_qualification import verified_qualification
from algua.registry.drawdown_store import account_state, policy_for
from algua.registry.frozen_runtime import FrozenContentVerifier, FrozenTenant, recorded_descriptor
from algua.registry.frozen_view import overlay_gate_universe
from algua.registry.store import SqliteStrategyRepository
from algua.registry.universe_binding import resolve_operational_universe
from algua.risk.layered import decimal


def frozen_tenant(conn, name: str, *, verifier=None) -> FrozenTenant:
    repo = SqliteStrategyRepository(conn)
    rec = repo.get(name)
    deployment = repo.active_deployment(rec.id)
    if deployment is None or deployment.source_kind != "frozen":
        raise ValueError("experimental live requires an active frozen deployment")
    manifest, config = recorded_descriptor(deployment, name)
    settings = get_settings()
    universe, _ = resolve_operational_universe(
        conn,
        settings.data_dir,
        name,
        list(config.universe),
        research_gate_id=deployment.research_gate_id,
    )
    view = overlay_gate_universe(config, universe)
    verifier = verifier or FrozenContentVerifier(settings.data_dir)
    return FrozenTenant(
        rec,
        deployment,
        manifest,
        verifier.bundle(manifest.bundle, deployment_id=deployment.id),
        verifier.environment(manifest.environment, deployment_id=deployment.id),
        view,
    )


def envelope(conn, account_id: str, strategy) -> dict:
    state = account_state(conn, "live")
    if state is None or state["account_id"] != account_id:
        raise ValueError("a signed risk policy for the exact live account is required")
    policy = policy_for(conn, state)
    if not policy.permitted_symbols:
        raise ValueError("the live policy needs explicit owner-approved instruments")
    if (
        strategy.execution.allow_short
        or strategy.execution.max_gross_exposure > 1
        or not set(strategy.universe) <= set(policy.permitted_symbols)
    ):
        raise ValueError("deployment violates the long-only unleveraged instrument envelope")
    return {"risk_policy_id": state["policy_id"], "policy": policy.to_dict()}


def build_context(
    conn,
    name: str,
    *,
    qid: int,
    capital: str,
    account_id: str,
    at,
    require_fresh: bool,
    verifier=None,
    prior_authorization_id: int | None = None,
) -> tuple[dict, FrozenTenant]:
    tenant = frozen_tenant(conn, name, verifier=verifier)
    qualification = verified_qualification(
        conn, tenant.deployment, qid, calendar=get_calendar(), at=at, require_fresh=require_fresh
    )
    risk = envelope(conn, account_id, tenant.view)
    amount = decimal(capital)
    if amount <= 0 or amount > decimal(risk["policy"]["normal_capital"]):
        raise ValueError("capital must be positive and within the signed account ceiling")
    d, m = tenant.deployment, tenant.manifest
    context = {
        "profile": "capped-frozen-live/v1",
        "strategy": name,
        "strategy_id": tenant.rec.id,
        "deployment_id": d.id,
        "manifest_digest": d.manifest_digest,
        "bundle_digest": m.bundle.digest,
        "environment_digest": m.environment.digest,
        "code_hash": d.code_hash,
        "config_hash": d.config_hash,
        "dependency_hash": d.dependency_hash,
        "research_gate_id": d.research_gate_id,
        "qualification": qualification,
        "live_account_id": account_id,
        "provider": provider_policy(),
        "envelope": risk,
        "capital": str(amount),
        "gate_universe": list(tenant.view.universe),
        "universe_name": d.universe_name,
        "prior_authorization_id": prior_authorization_id,
    }
    return context, tenant
