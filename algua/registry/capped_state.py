"""Atomic experimental authority/capital/stage writes after a verified human signature."""

from __future__ import annotations

from datetime import UTC, datetime

from algua.contracts.lifecycle import Actor, Stage, validate_transition
from algua.registry.allocations import active_allocation, revoke_active_locked
from algua.registry.capped_active import active
from algua.registry.drawdown_store import account_state
from algua.registry.store import SqliteStrategyRepository
from algua.risk import global_halt, kill_switch
from algua.risk.layered import decimal


def revoke(conn, strategy_id: int, reason: str, *, at: str | None = None) -> None:
    at = at or datetime.now(UTC).isoformat()
    ids = [
        r["approval_id"]
        for r in conn.execute(
            "SELECT approval_id FROM capped_live_authorizations "
            "WHERE strategy_id=? AND revoked_at IS NULL",
            (strategy_id,),
        )
    ]
    conn.execute(
        "UPDATE capped_live_authorizations SET revoked_at=?,revocation_reason=? "
        "WHERE strategy_id=? AND revoked_at IS NULL",
        (at, reason, strategy_id),
    )
    for approval in ids:
        conn.execute(
            "UPDATE approvals SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (at, approval)
        )


def readiness(conn, tenant, context: dict, account) -> None:
    rec = tenant.rec
    if rec.stage not in (Stage.PAPER, Stage.FORWARD_TESTED, Stage.LIVE):
        raise ValueError("experimental activation requires paper, forward_tested or current live")
    state = account_state(conn, "live")
    if (
        state is None
        or state["severity"] != 0
        or state["blocked_reason"]
        or global_halt.is_engaged(conn)
        or kill_switch.is_tripped(conn, rec.name)
        or decimal(account.cash) < 0
        or decimal(account.equity) <= 0
    ):
        raise ValueError("account or strategy risk state is not ready for experimental activation")
    prior = active_allocation(conn, rec.id)
    if rec.stage is not Stage.LIVE and prior is not None:
        raise ValueError("paper allocation must be handed off before activation")
    capital = decimal(context["capital"])
    others = conn.execute(
        "SELECT coalesce(sum(a.capital),0) FROM strategy_allocations a "
        "JOIN strategies s ON s.id=a.strategy_id WHERE a.revoked_ts IS NULL AND s.stage='live' "
        "AND s.id<>?",
        (rec.id,),
    ).fetchone()[0]
    if decimal(others) + capital > min(
        decimal(account.equity), decimal(context["envelope"]["policy"]["normal_capital"])
    ):
        raise ValueError("total live allocation exceeds the signed account ceiling or equity")


def commit_activation(
    conn,
    tenant,
    context: dict,
    *,
    pending,
    principal: str,
    signature_b64: str,
    account,
    actor: Actor,
    recheck,
    exit_guard=None,
    prior_authorization=None,
) -> int:
    if actor is not Actor.HUMAN:
        raise ValueError("experimental activation requires an authenticated human")
    if conn.in_transaction:
        raise ValueError("activation requires its own transaction")
    repo = SqliteStrategyRepository(conn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        actual, new_tenant = recheck()
        if actual != context or new_tenant.rec != tenant.rec:
            raise ValueError("activation context or lifecycle changed before commit")
        readiness(conn, new_tenant, actual, account)
        if tenant.rec.stage is Stage.LIVE:
            latest = conn.execute(
                "SELECT id FROM capped_live_authorizations WHERE strategy_id=? "
                "ORDER BY id DESC LIMIT 1", (tenant.rec.id,),
            ).fetchone()
            if (
                prior_authorization is None
                or latest is None
                or prior_authorization.authorization_id != context["prior_authorization_id"]
                or latest["id"] != prior_authorization.authorization_id
                or not active(conn, prior_authorization)
            ):
                raise ValueError("prior live authority changed or was revoked before resize")
        now = datetime.now(UTC).isoformat()
        changed = conn.execute(
            "UPDATE capped_live_challenges SET consumed_at=? "
            "WHERE nonce=? AND strategy_id=? AND context_json=? AND consumed_at IS NULL "
            "AND expires_at>?",
            (now, pending["nonce"], tenant.rec.id, pending["context_json"], now),
        ).rowcount
        if changed != 1:
            raise ValueError("experimental challenge expired, changed or already consumed")
        # The matching approval binds the verified frozen identity and human principal.
        approval_id = conn.execute(
            "INSERT INTO approvals "
            "(strategy_id,code_hash,config_hash,dependency_hash,approved_by,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                tenant.rec.id,
                tenant.identity.code_hash,
                tenant.identity.config_hash,
                tenant.identity.dependency_hash,
                principal,
                now,
            ),
        ).lastrowid
        if not repo.has_valid_approval(tenant.rec.id, *tenant.identity):
            raise ValueError("matching unrevoked frozen approval is required")
        revoke(conn, tenant.rec.id, "superseded", at=now)
        # The new approval was not attached to an old authority and remains unrevoked.
        rec = repo.get(tenant.name)
        if rec.stage is Stage.PAPER:
            validate_transition(rec.stage, Stage.FORWARD_TESTED)
            rec = repo._apply_transition_locked(
                rec=rec,
                to=Stage.FORWARD_TESTED,
                actor=Actor.HUMAN,
                reason="experimental historical + five-session qualification (not strict forward)",
                code_hash=tenant.identity.code_hash,
                config_hash=tenant.identity.config_hash,
                dependency_hash=tenant.identity.dependency_hash,
                consume_gate_id=None,
                consume_forward_gate_id=None,
                now=now,
            )
        if rec.stage is not Stage.LIVE:
            validate_transition(rec.stage, Stage.LIVE)
            repo._assert_flat_for_bench(rec.name, rec.stage, exit_guard)
            repo._apply_transition_locked(
                rec=rec,
                to=Stage.LIVE,
                actor=Actor.HUMAN,
                reason="human-signed capped-frozen-live/v1",
                code_hash=tenant.identity.code_hash,
                config_hash=tenant.identity.config_hash,
                dependency_hash=tenant.identity.dependency_hash,
                consume_gate_id=None,
                consume_forward_gate_id=None,
                now=now,
                revoke_allocation=True,
            )
        from algua.contracts.canonical import canonical_json

        rid = conn.execute(
            "INSERT INTO capped_live_authorizations "
            "(strategy_id,deployment_id,qualification_id,approval_id,risk_policy_id,capital,"
            "live_account_id,provider_json,nonce,expires_at,signature,principal,authorized_at,"
            "prior_authorization_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                rec.id,
                tenant.deployment_id,
                context["qualification"]["id"],
                approval_id,
                context["envelope"]["risk_policy_id"],
                context["capital"],
                context["live_account_id"],
                canonical_json(context["provider"]),
                pending["nonce"],
                pending["expires_at"],
                signature_b64,
                principal,
                now,
                context["prior_authorization_id"],
            ),
        ).lastrowid
        revoke_active_locked(conn, rec.id)
        conn.execute(
            "INSERT INTO strategy_allocations(strategy_id,capital,effective_ts,actor) "
            "VALUES (?,?,?,?)",
            (rec.id, float(decimal(context["capital"])), now, "human"),
        )
        conn.commit()
        assert rid is not None
        return int(rid)
    except BaseException:
        conn.rollback()
        raise
