"""Distinct capped-live human ceremony and trade-time signature verification from frozen records."""

from __future__ import annotations

import base64
from datetime import UTC, datetime

from algua.contracts.canonical import canonical_json
from algua.contracts.capped_live import CappedLiveAuthorization
from algua.contracts.lifecycle import Actor, Stage
from algua.execution.broker_factory import BrokerKind, build_broker
from algua.registry import live_gate
from algua.registry.capped_context import build_context
from algua.registry.capped_policy import context_digest
from algua.registry.capped_state import commit_activation, readiness
from algua.registry.challenges import ChallengeSpec, build_payload, find_pending, issue
from algua.registry.store import SqliteStrategyRepository

_SPEC = ChallengeSpec(
    table="capped_live_challenges",
    namespace="algua-go-live",
    payload_fields=("strategy_id", "context_json"),
    column_fields=("strategy_id", "context_json"),
)


def live_account():
    return build_broker(BrokerKind.ALPACA_LIVE_READONLY).account()


def authorize(
    conn, name: str, *, capital: str, actor: Actor, signature: bytes | None, anchor=None
) -> dict:
    actor = Actor(actor)
    if actor not in (Actor.AGENT, Actor.HUMAN):
        raise ValueError("experimental activation accepts agent preview or authenticated human")
    repo = SqliteStrategyRepository(conn)
    rec = repo.get(name)
    deployment = repo.active_deployment(rec.id)
    if deployment is None:
        raise ValueError("no active frozen deployment")
    row = conn.execute(
        "SELECT id FROM experimental_qualifications WHERE deployment_id=? ORDER BY id DESC LIMIT 1",
        (deployment.id,),
    ).fetchone()
    if row is None:
        raise ValueError("record a signed five-session experimental qualification first")
    previous = None
    if rec.stage is Stage.LIVE:
        previous = verify(conn, repo, name, anchor or live_gate.ALLOWED_SIGNERS_PATH)
    account = live_account()

    def current():
        return build_context(
            conn,
            name,
            qid=row["id"],
            capital=capital,
            account_id=account.account_id,
            at=datetime.now(UTC),
            require_fresh=previous is None,
            prior_authorization_id=previous.authorization_id if previous else None,
        )

    context, tenant = current()
    readiness(conn, tenant, context, account)
    guard = None
    if tenant.rec.stage is not Stage.LIVE:
        from algua.execution.live_ledger import LedgerKind, owned_open_order_ids

        paper = build_broker(BrokerKind.ALPACA_PAPER)
        if paper.account().account_id != context["qualification"]["paper_account_id"]:
            raise ValueError("paper account changed since qualification")
        repo._assert_flat_for_bench(name, tenant.rec.stage)
        if owned_open_order_ids(conn, paper, name, kind=LedgerKind.PAPER):
            raise ValueError("paper orders remain open; finish paper handoff")
    values = {"strategy_id": rec.id, "context_json": canonical_json(context)}
    if actor is Actor.AGENT:
        if signature is not None:
            raise ValueError("an agent preview cannot submit a live signature")
        return {"ok": True, "preview": True, "live_authority": False, "context": context}
    if signature is None:
        return {
            "ok": True,
            "action": "capped_live_challenge",
            "context": context,
            "namespace": _SPEC.namespace,
            **issue(conn, _SPEC, values),
        }
    pending = find_pending(conn, _SPEC, values)
    if pending is None:
        raise ValueError("no fresh matching capped-live challenge")
    payload = build_payload(_SPEC, values, pending["nonce"], pending["expires_at"])
    principal = live_gate.verify_signature(
        anchor or live_gate.ALLOWED_SIGNERS_PATH, payload, signature, namespace=_SPEC.namespace
    )
    if principal is None:
        raise ValueError("capped-live signature verification failed")
    # The handoff command already settled/cancelled paper orders; re-list before the atomic write.
    from algua.execution.lane_exit import select_exit_guard

    if tenant.rec.stage is not Stage.LIVE:
        guard = select_exit_guard(repo, name, Stage.FORWARD_TESTED, Stage.LIVE)
        guard.cancel_and_ingest()
        if guard.owned_open_order_ids():
            raise ValueError("paper orders remain open; finish paper handoff")
    rid = commit_activation(
        conn,
        tenant,
        context,
        pending=pending,
        principal=principal,
        signature_b64=base64.b64encode(signature).decode(),
        account=account,
        actor=actor,
        recheck=current,
        exit_guard=guard,
        prior_authorization=previous,
    )
    return {
        "ok": True,
        "activated": True,
        "strategy": name,
        "authorization_id": rid,
        "capital": context["capital"],
        "profile": context["profile"],
    }


def verify(conn, repo, name: str, anchor) -> CappedLiveAuthorization:
    rec = repo.get(name)
    if rec.stage is not Stage.LIVE:
        raise live_gate.LiveAuthorizationError("experimental strategy is not live")
    row = conn.execute(
        "SELECT * FROM capped_live_authorizations WHERE strategy_id=? ORDER BY id DESC LIMIT 1",
        (rec.id,),
    ).fetchone()
    if row is None or row["revoked_at"] is not None:
        raise live_gate.LiveAuthorizationError("no current unrevoked capped-live authorization")
    try:
        account = live_account()
        context, tenant = build_context(
            conn,
            name,
            qid=row["qualification_id"],
            capital=row["capital"],
            account_id=account.account_id,
            at=datetime.fromisoformat(row["authorized_at"]),
            require_fresh=row["prior_authorization_id"] is None,
            prior_authorization_id=row["prior_authorization_id"],
        )
        if (
            tenant.deployment_id != row["deployment_id"]
            or context["envelope"]["risk_policy_id"] != row["risk_policy_id"]
            or context["live_account_id"] != row["live_account_id"]
            or canonical_json(context["provider"]) != row["provider_json"]
        ):
            raise ValueError("capped live binding changed")
        approval = conn.execute(
            "SELECT * FROM approvals WHERE id=?", (row["approval_id"],)
        ).fetchone()
        if (
            approval is None
            or approval["revoked_at"] is not None
            or approval["strategy_id"] != rec.id
            or approval["approved_by"] != row["principal"]
            or any(
                approval[k] != context[k] for k in ("code_hash", "config_hash", "dependency_hash")
            )
        ):
            raise ValueError("frozen approval is absent, revoked or mismatched")
        values = {"strategy_id": rec.id, "context_json": canonical_json(context)}
        challenge = conn.execute(
            "SELECT * FROM capped_live_challenges WHERE nonce=?", (row["nonce"],)
        ).fetchone()
        if (
            challenge is None
            or challenge["consumed_at"] is None
            or challenge["strategy_id"] != rec.id
            or challenge["context_json"] != values["context_json"]
            or challenge["expires_at"] != row["expires_at"]
            or challenge["consumed_at"] != row["authorized_at"]
        ):
            raise ValueError("capped-live challenge binding is invalid")
        issued, accepted, expires = (
            datetime.fromisoformat(value)
            for value in (challenge["issued_at"], row["authorized_at"], row["expires_at"])
        )
        if any(t.tzinfo is None for t in (issued, accepted, expires)) or not (
            issued <= accepted < expires
        ):
            raise ValueError("capped-live acceptance was outside its signed time window")
        if row["prior_authorization_id"] is not None:
            prior = conn.execute(
                "SELECT * FROM capped_live_authorizations WHERE id=? AND strategy_id=? "
                "AND deployment_id=? AND id<? AND revoked_at IS NOT NULL",
                (row["prior_authorization_id"], rec.id, tenant.deployment_id, row["id"]),
            ).fetchone()
            if prior is None:
                raise ValueError("capped-live resize has no matching prior authority")
        payload = build_payload(_SPEC, values, row["nonce"], row["expires_at"])
        principal = live_gate.verify_signature(
            anchor,
            payload,
            base64.b64decode(row["signature"], validate=True),
            namespace=_SPEC.namespace,
        )
        if principal != row["principal"]:
            raise ValueError("capped-live signature no longer verifies")
    except Exception as exc:
        raise live_gate.LiveAuthorizationError(f"capped live refused: {exc}") from exc
    return CappedLiveAuthorization(
        rec.id,
        tenant.identity.code_hash,
        tenant.identity.config_hash,
        tenant.identity.dependency_hash,
        row["principal"],
        row["authorized_at"],
        row["id"],
        tenant.deployment_id,
        row["approval_id"],
        row["qualification_id"],
        row["risk_policy_id"],
        row["live_account_id"],
        row["capital"],
        context_digest(context["provider"]),
    )
