"""Human account-policy ceremony; no allocation, funding or strategy live authority is minted."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta

from algua.contracts.canonical import canonical_json
from algua.execution.drawdown_flows import fingerprints, previous_close
from algua.registry import live_gate
from algua.registry.challenges import ChallengeSpec, build_payload, find_pending, issue
from algua.registry.drawdown_store import account_state, write_state
from algua.risk.layered import DrawdownPolicy, decimal

_SPEC = ChallengeSpec(
    table="drawdown_challenges",
    namespace="algua-go-live",
    payload_fields=("purpose", "lane", "account_id", "options_json", "request_json"),
    column_fields=("purpose", "lane", "account_id", "options_json", "request_json"),
)


def activity_start(stamp: str) -> str:
    now = datetime.fromisoformat(stamp)
    return (min(now, previous_close(now)) - timedelta(days=1)).isoformat()


def flat_snapshot(broker) -> dict:
    account = broker.account()
    if (
        not re.fullmatch(r"[A-Za-z0-9_-]+", account.account_id)
        or decimal(account.equity) <= 0
        or decimal(account.cash) < 0
        or any(decimal(q) != 0 for q in broker.get_positions().values)
        or broker.list_open_orders()
    ):
        raise ValueError("policy configuration/restoration requires a flat settled account")
    return {"account_id": account.account_id, "equity": str(decimal(account.equity))}


def signed_change(
    conn, broker, lane: str, *, purpose: str, policy: DrawdownPolicy | None, signature: bytes | None
) -> dict:
    if lane not in ("paper", "live") or purpose not in ("configure", "restore"):
        raise ValueError("invalid drawdown ceremony")
    snapshot = flat_snapshot(broker)
    state = account_state(conn, lane)
    if state is not None and state["account_id"] != snapshot["account_id"]:
        raise ValueError("configured risk account mismatch")
    if conn.execute(
        "SELECT 1 FROM drawdown_reductions WHERE lane=? AND phase='submitting' "
        "AND broker_order_id IS NULL LIMIT 1",
        (lane,),
    ).fetchone():
        raise ValueError("unresolved reduction acceptance prevents policy change or restoration")
    if purpose == "restore" and state is None:
        raise ValueError("no configured account to restore")
    if policy is not None and decimal(policy.normal_capital) > decimal(snapshot["equity"]):
        raise ValueError("normal exposure budget exceeds non-borrowed account equity")
    options = canonical_json(policy.to_dict() if policy is not None else {})
    if signature is None:
        request = canonical_json(
            {
                "snapshot": snapshot,
                "prior_state": state,
                "effect": "restore rebases future risk; history retained"
                if purpose == "restore"
                else "configure preserves severity",
            }
        )
        values = {
            "purpose": purpose,
            "lane": lane,
            "account_id": snapshot["account_id"],
            "options_json": options,
            "request_json": request,
        }
        challenge = issue(conn, _SPEC, values)
        return {
            "ok": True,
            "action": "drawdown_challenge",
            "namespace": _SPEC.namespace,
            "request": json.loads(request),
            **challenge,
        }
    row = conn.execute(
        "SELECT * FROM drawdown_challenges WHERE purpose=? AND lane=? "
        "AND account_id=? AND options_json=? AND consumed_at IS NULL AND expires_at>? "
        "ORDER BY issued_at DESC LIMIT 1",
        (purpose, lane, snapshot["account_id"], options, datetime.now(UTC).isoformat()),
    ).fetchone()
    if row is None:
        raise ValueError("no fresh matching drawdown challenge")
    values = {key: row[key] for key in _SPEC.column_fields}
    pending = find_pending(conn, _SPEC, values)
    payload = build_payload(_SPEC, values, row["nonce"], row["expires_at"])
    principal = live_gate.verify_signature(
        live_gate.ALLOWED_SIGNERS_PATH, payload, signature, namespace=_SPEC.namespace
    )
    if pending is None or principal is None:
        raise ValueError("drawdown signature verification failed")
    request = json.loads(row["request_json"])
    if request != {
        "snapshot": snapshot,
        "prior_state": state,
        "effect": "restore rebases future risk; history retained"
        if purpose == "restore"
        else "configure preserves severity",
    }:
        raise ValueError("drawdown state/account changed; request a new challenge")
    # Settle and reconcile before accepting a new baseline; never use broker flatness alone.
    from algua.execution.drawdown_actions import synchronize

    synchronize(conn, broker, lane)
    if flat_snapshot(broker) != snapshot:
        raise ValueError("account changed during drawdown ceremony")
    stamp = broker.clock()
    when = datetime.fromisoformat(stamp)
    if when.tzinfo is None or abs((datetime.now(UTC) - when).total_seconds()) > 60:
        raise ValueError("a current broker clock is required")
    seen = fingerprints(broker.account_activities_window(activity_start(stamp), stamp))
    if flat_snapshot(broker) != snapshot:
        raise ValueError("account changed during baseline activity capture")
    conn.execute("BEGIN IMMEDIATE")
    try:
        if account_state(conn, lane) != state:
            raise ValueError("drawdown state changed under lock")
        consumed = conn.execute(
            "UPDATE drawdown_challenges SET consumed_at=? WHERE nonce=? "
            "AND consumed_at IS NULL AND expires_at>?",
            (stamp, row["nonce"], datetime.now(UTC).isoformat()),
        ).rowcount
        if consumed != 1:
            raise ValueError("drawdown challenge expired or already consumed")
        if purpose == "configure":
            assert policy is not None
            pid = conn.execute(
                "INSERT INTO drawdown_policies "
                "(lane,account_id,policy_json,principal,created_at) VALUES (?,?,?,?,?)",
                (lane, snapshot["account_id"], options, principal, stamp),
            ).lastrowid
        else:
            assert state is not None
            pid = state["policy_id"]
            policy = DrawdownPolicy(
                **json.loads(
                    conn.execute(
                        "SELECT policy_json FROM drawdown_policies WHERE id=?", (pid,)
                    ).fetchone()[0]
                )
            )
        initial = {
            "lane": lane,
            "account_id": snapshot["account_id"],
            "policy_id": pid,
            "baseline_equity": snapshot["equity"],
            "baseline_nav": policy.normal_capital,
            "baseline_at": stamp,
            "baseline_seen": seen,
            "activity_fingerprints": seen,
            "peak_nav": policy.normal_capital,
            "last_nav": policy.normal_capital,
            "last_equity": snapshot["equity"],
            "severity": 0,
            "blocked_reason": None,
            "flow_total": "0",
            "drawdown": "0",
            "observed_at": stamp,
            "revision": 0,
        }
        action = {"principal": principal, "purpose": purpose, "nonce": row["nonce"], "at": stamp}
        initial["last_human_action"] = action
        if state is None:
            conn.execute(
                "INSERT INTO drawdown_accounts VALUES (?,?,?,?,?)",
                (lane, snapshot["account_id"], pid, 0, canonical_json(initial)),
            )
            state = write_state(conn, initial, initial, "configured")
        else:
            updated = (
                initial
                if purpose == "restore"
                else state | {"policy_id": pid, "last_human_action": action}
            )
            state = write_state(conn, state, updated, purpose)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return {
        "ok": True,
        "action": purpose,
        "principal": principal,
        "state": state,
        "live_authority": False,
    }
