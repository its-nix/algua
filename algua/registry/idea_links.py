"""Which ideas each inspiration became, and the owner-facing journey of an Inbox item
(spec 2026-11-14 §7.3). Pure reads: the journey is joined live from `idea_inspirations`,
`ideas` and `idea_attempts`, never stored."""
from __future__ import annotations

import sqlite3
from typing import Any

from algua.contracts.idea import REFUTING_OUTCOMES, AttemptOutcome, IdeaStatus

_REASON_CHARS = 300


def _idea_rows(conn: sqlite3.Connection) -> dict[str, dict[str, str]]:
    latest: dict[int, tuple[str, str]] = {}
    for r in conn.execute("SELECT idea_id, outcome, reason FROM idea_attempts "
                          "WHERE outcome IS NOT NULL ORDER BY outcome_at, id"):
        latest[int(r[0])] = (str(r[1] or ""), str(r[2] or ""))
    rows = {}
    for r in conn.execute("SELECT id, status, duplicate_of_idea_id FROM ideas ORDER BY id"):
        idea_id = int(r[0])
        outcome, reason = latest.get(idea_id, ("", ""))
        rows[str(idea_id)] = {
            "id": str(idea_id), "status": str(r[1] or ""),
            "duplicate_of": "" if r[2] is None else str(r[2]),
            "latest_outcome": outcome, "latest_reason": reason[:_REASON_CHARS],
        }
    return rows


def ideas_by_inspiration(conn: sqlite3.Connection) -> dict[str, list[dict[str, str]]]:
    by_id = _idea_rows(conn)
    out: dict[str, list[dict[str, str]]] = {}
    for r in conn.execute("SELECT inspiration_id, idea_id FROM idea_inspirations "
                          "ORDER BY idea_id"):
        row = by_id.get(str(r[1]))
        if row is not None:
            out.setdefault(str(r[0]), []).append(row)
    return out


def _outcome(idea: dict[str, str]) -> tuple[str, str] | None:
    """(label, tone) for what happened to the idea, or None while nothing has."""
    outcome, status = idea["latest_outcome"], idea["status"]
    if outcome == AttemptOutcome.PROMOTED_CANDIDATE:
        return "Candidate", "progressed"
    if outcome in REFUTING_OUTCOMES or status == IdeaStatus.REFUTED:
        return f"Refuted: {idea['latest_reason'] or outcome or 'refuted'}", "refuted"
    if outcome == AttemptOutcome.CANDIDATE_PREVIEW_PASS:
        return "Backtested", "neutral"
    if idea["duplicate_of"]:  # a deliberate --allow-duplicate idea not yet attempted
        return f"Duplicate of idea #{idea['duplicate_of']}", "neutral"
    if outcome:  # data_blocked / abandoned / run_error: no clean label, show the raw outcome
        return f"Outcome: {outcome}", "neutral"
    if status == IdeaStatus.DISCARDED:
        return "Discarded", "neutral"
    return None


def journey(item: dict[str, Any],
            ideas: dict[str, list[dict[str, str]]]) -> list[dict[str, str]]:
    if item["status"] == "queued":
        return [{"label": "Queued for the next leap", "tone": "pending"}]
    steps: list[tuple[str, str]] = [("Inspiration", "neutral")]
    for idea in ideas.get(str(item.get("inspiration_id") or ""), []):
        outcome = _outcome(idea)
        steps.append((f"Idea #{idea['id']}", "neutral" if outcome else "pending"))
        if outcome:
            steps.append(outcome)
    last = len(steps) - 1
    return [{"label": label, "tone": tone if i == last else "neutral"}
            for i, (label, tone) in enumerate(steps)]
