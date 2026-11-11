"""Account risk persistence, independent of legacy global halts and peak rebasing."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from algua.contracts.canonical import canonical_json
from algua.risk.layered import DrawdownPolicy


def account_state(conn, lane: str) -> dict[str, Any] | None:
    if lane not in ("paper", "live"):
        raise ValueError("unknown trading lane")
    row = conn.execute("SELECT * FROM drawdown_accounts WHERE lane=?", (lane,)).fetchone()
    if row is None:
        return None
    state = json.loads(row["state_json"])
    if not isinstance(state, dict) or state["account_id"] != row["account_id"]:
        raise ValueError("corrupt drawdown state")
    return state | {"revision": row["revision"], "policy_id": row["policy_id"]}


def policy_for(conn, state: dict) -> DrawdownPolicy:
    row = conn.execute(
        "SELECT * FROM drawdown_policies WHERE id=?", (state["policy_id"],)
    ).fetchone()
    if row is None or row["lane"] != state["lane"] or row["account_id"] != state["account_id"]:
        raise ValueError("drawdown policy/account mismatch")
    return DrawdownPolicy(**json.loads(row["policy_json"]))


def write_state(conn, prior: dict, state: dict, kind: str) -> dict:
    """Compare-and-swap one observation and its immutable event in the caller's transaction."""
    state = state | {"revision": prior["revision"] + 1}
    payload = canonical_json(state)
    changed = conn.execute(
        "UPDATE drawdown_accounts SET revision=?,policy_id=?,state_json=? "
        "WHERE lane=? AND revision=?",
        (state["revision"], state["policy_id"], payload, state["lane"], prior["revision"]),
    ).rowcount
    if changed != 1:
        raise ValueError("drawdown state changed; retry the cycle")
    conn.execute(
        "INSERT INTO drawdown_events "
        "(lane,account_id,policy_id,kind,state_json,created_at) VALUES (?,?,?,?,?,?)",
        (
            state["lane"],
            state["account_id"],
            state["policy_id"],
            kind,
            payload,
            datetime.now(UTC).isoformat(),
        ),
    )
    return state


def block(conn, lane: str, reason: str, *, halt: bool = False) -> dict:
    prior = account_state(conn, lane)
    if prior is None:
        raise ValueError("no configured drawdown account")
    with conn:
        return write_state(
            conn,
            prior,
            prior
            | {"blocked_reason": reason, "severity": max(prior["severity"], 2 if halt else 0)},
            "blocked",
        )


def status(conn) -> list[dict]:
    return [
        state | {"policy": policy_for(conn, state).to_dict()}
        for lane in ("paper", "live")
        if (state := account_state(conn, lane)) is not None
    ]


def is_blocked(conn, lane: str) -> bool:
    state = account_state(conn, lane)
    return state is not None and (state["severity"] >= 2 or bool(state["blocked_reason"]))
