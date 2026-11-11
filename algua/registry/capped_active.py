"""Cheap row-bound mid-order liveness; full signature verification precedes each tick."""

from algua.contracts.capped_live import CappedLiveAuthorization
from algua.registry.capped_policy import context_digest, provider_policy
from algua.registry.drawdown_store import account_state


def active(conn, token: CappedLiveAuthorization) -> bool:
    row = conn.execute(
        "SELECT a.*,d.retired_at,s.stage,p.revoked_at AS approval_revoked "
        "FROM capped_live_authorizations a JOIN strategy_deployments d ON d.id=a.deployment_id "
        "JOIN strategies s ON s.id=a.strategy_id JOIN approvals p ON p.id=a.approval_id "
        "WHERE a.id=?",
        (token.authorization_id,),
    ).fetchone()
    state = account_state(conn, "live")
    try:
        return bool(
            row is not None
            and row["revoked_at"] is None
            and row["retired_at"] is None
            and row["stage"] == "live"
            and row["approval_revoked"] is None
            and state is not None
            and state["policy_id"] == token.risk_policy_id
            and state["account_id"] == token.account_id
            and row["deployment_id"] == token.deployment_id
            and row["approval_id"] == token.approval_id
            and row["strategy_id"] == token.strategy_id
            and row["capital"] == token.capital
            and context_digest(provider_policy()) == token.provider_digest
        )
    except (ValueError, TypeError):
        return False
