"""Independently recheck the fixed qualified paper window and canonical historical source rows."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime

from algua.contracts.canonical import canonical_json
from algua.contracts.lifecycle import Actor
from algua.operator.schedule import target_session
from algua.registry.experimental_qualification import historical_evidence
from algua.registry.experimental_sessions import PROFILE_DIGEST, PROFILE_JSON, session_status
from algua.registry.store import SqliteStrategyRepository


def verified_qualification(
    conn, deployment, qid: int, *, calendar, at: datetime, require_fresh: bool
) -> dict:
    row = conn.execute(
        "SELECT * FROM experimental_qualifications WHERE id=? AND deployment_id=?",
        (qid, deployment.id),
    ).fetchone()
    if (row is None or row["actor"] not in {actor.value for actor in Actor}
            or row["profile_digest"] != PROFILE_DIGEST):
        raise ValueError("matching experimental qualification is required")
    report = json.loads(row["evidence_json"])
    digest = report.pop("evidence_digest", None)
    if (
        digest != row["evidence_digest"]
        or hashlib.sha256(canonical_json(report).encode()).hexdigest() != digest
        or report["profile"] != json.loads(PROFILE_JSON)
        or report["profile_digest"] != PROFILE_DIGEST
        or report["passed"] is not True
        or report["live_authority"] is not False
        or report["deployment_id"] != deployment.id
        or report["strategy_id"] != deployment.strategy_id
        or any(
            report[k] != getattr(deployment, k)
            for k in ("manifest_digest", "code_hash", "config_hash", "dependency_hash")
        )
    ):
        raise ValueError("experimental qualification context is corrupt or changed")
    last = date.fromisoformat(report["operational"]["expected_sessions"][-1])
    current = session_status(conn, deployment.id, last_completed=last, calendar=calendar)
    historical = historical_evidence(SqliteStrategyRepository(conn), deployment)
    if (
        not current["passed"]
        or current != report["operational"]
        or historical != report["historical"]
    ):
        raise ValueError("qualified paper or historical source evidence changed")
    latest = target_session(at, calendar)
    if latest is None or last > latest:
        raise ValueError("qualification is from an uncompleted session")
    if require_fresh and calendar.sessions_between(last, latest) > 5:
        raise ValueError("experimental qualification is more than five sessions stale")
    return {
        "id": qid,
        "profile_digest": PROFILE_DIGEST,
        "evidence_digest": digest,
        "last_paper_session": last.isoformat(),
        "paper_account_id": current["account_id"],
    }
