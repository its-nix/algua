# algua/registry/idea_scorecard.py
"""The feedback edge (spec §7): attempt outcomes + downstream stage, grouped four ways."""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from algua.contracts.idea import AttemptOutcome
from algua.registry.ideas import IdeaRepository
from algua.registry.negative_results import list_negative_results

_MIN_N = 5
_PAST_INTEGRITY = frozenset(a.value for a in AttemptOutcome) - {
    AttemptOutcome.INTEGRITY_FAIL.value, AttemptOutcome.ABANDONED.value,
    AttemptOutcome.RUN_ERROR.value}
_PAST_WALKFORWARD = _PAST_INTEGRITY - {AttemptOutcome.HOLDOUT_NEGATIVE.value,
                                       AttemptOutcome.WALKFORWARD_REFUTED.value,
                                       AttemptOutcome.SWEEP_UNSTABLE.value}


def _bucket() -> dict:
    return {"n": 0, "outcomes": defaultdict(int), "stages": defaultdict(int), "survivals": 0}


def _derived_stage(stage: str | None) -> str | None:
    if stage is None:
        return None
    if stage in ("forward_tested", "live"):
        return "forward_survivor"
    return stage  # paper | retired | dormant | candidate | backtested


def _finalize(b: dict) -> dict:
    n = b["n"]
    past_i = sum(v for k, v in b["outcomes"].items() if k in _PAST_INTEGRITY)
    past_w = sum(v for k, v in b["outcomes"].items() if k in _PAST_WALKFORWARD)

    def rate(x: int) -> float | None:
        return (x / n) if n >= _MIN_N else None

    return {"n": n, "outcomes": dict(b["outcomes"]), "stages": dict(b["stages"]),
            "survivals": b["survivals"], "integrity_yield": rate(past_i),
            "walkforward_yield": rate(past_w), "survival_yield": rate(b["survivals"])}


def scorecard(conn: sqlite3.Connection, *, days: int) -> dict:
    since = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT a.id AS attempt_id, a.idea_id, a.outcome, i.category, s.stage AS stage,"
        " ins.inspiration_id, ins.venue, ins.obscurity FROM idea_attempts a"
        " JOIN ideas i ON i.id = a.idea_id"
        " LEFT JOIN strategies s ON s.id = i.authored_strategy_id"
        " LEFT JOIN idea_inspirations ins ON ins.idea_id = a.idea_id"
        " WHERE a.claimed_at >= ? AND a.outcome IS NOT NULL", (since,)).fetchall()
    groups: dict[str, dict[str, dict]] = {k: defaultdict(_bucket) for k in
                                          ("by_venue", "by_category", "by_obscurity",
                                           "by_inspiration")}
    seen_attempt_per_key: set[tuple] = set()
    for r in rows:
        stage = _derived_stage(r["stage"])
        # A single attempt survives if it was directly promoted OR its idea later reached
        # forward_tested/live — a UNION counted once per attempt, never both, so an idea that
        # was promoted and LATER also reached forward_tested cannot count twice.
        survives = r["outcome"] == AttemptOutcome.PROMOTED_CANDIDATE.value \
            or stage == "forward_survivor"
        keys = [("by_category", r["category"] or "legacy")]
        if r["venue"] is not None:
            keys += [("by_venue", r["venue"]), ("by_obscurity", r["obscurity"]),
                     ("by_inspiration", r["inspiration_id"])]
        for group, key in keys:
            # one attempt (identified by its OWN idea_attempts.id, not idea_id+outcome — two
            # attempts on the same idea can share an outcome) counts once per (group,key) even
            # with several inspiration rows fanning it out.
            marker = (group, key, r["attempt_id"])
            if marker in seen_attempt_per_key:
                continue
            seen_attempt_per_key.add(marker)
            b = groups[group][key]
            b["n"] += 1
            b["outcomes"][r["outcome"]] += 1
            if stage:
                b["stages"][stage] += 1
            if survives:
                b["survivals"] += 1
    return {"days": days, "min_n_for_rates": _MIN_N,
            **{g: {k: _finalize(b) for k, b in d.items()} for g, d in groups.items()}}


def campaign_scorecard(conn: sqlite3.Connection) -> dict:
    """Lifetime advisory view; no stage-derived success, time window or inspiration fan-out.

    Attempt slots are NOT independent statistical trials or sweep-combination counts. Negative
    log rows are contextual references only: a gate failure is not necessarily negative alpha.
    The existing rolling scorecard keeps its historical meaning unchanged.
    """
    # These optional legacy Idea fields are mandatory for this particular feedback view.
    conn.execute("SELECT category, claimed_by, claim_token, claimed_at FROM ideas LIMIT 0")
    ideas = [asdict(i) for i in IdeaRepository(conn).list()]
    for idea in ideas:
        idea["history_key"] = (f"family:{idea['family']}" if idea["family"] not in (None, "unknown")
                               else f"category:{idea['category'] or 'legacy'}")
    by_id = {i["id"]: i for i in ideas}
    attempts = [dict(r) for r in conn.execute(
        "SELECT id, idea_id, run_stamp, claimed_at, outcome, reason, evidence_ref,"
        " strategy_name, outcome_at FROM idea_attempts ORDER BY id")]
    for a in attempts:
        a["evidence_id"] = f"idea_attempts:{a['id']}"
        if a["idea_id"] not in by_id:
            raise ValueError("campaign history contains an orphan attempt")
        if a["outcome"] is not None and a["outcome"] not in AttemptOutcome:
            raise ValueError("campaign history contains an unknown outcome")
    count = conn.execute("SELECT COUNT(*) FROM negative_results").fetchone()[0]
    negatives = list_negative_results(conn, limit=max(1, count))
    strategy_names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM strategies")}
    for n in negatives:
        n["evidence_id"] = f"negative_results:{n['id']}"
        # Automatic gate-fail captures often have NO hypothesis text. Recover their provenance
        # through the existing idea -> strategy FK rather than silently dropping those notes.
        n["idea_ids"] = [i["id"] for i in ideas if i["authored_strategy_id"] is not None
                         and strategy_names.get(i["authored_strategy_id"]) == n["strategy_name"]]

    def aggregate(rows: list[dict]) -> dict:
        counts = _campaign_counts(rows)
        return {**counts, "evidence_ids": sorted(a["evidence_id"] for a in rows)}

    family_rows: dict[str, list[dict]] = defaultdict(list)
    category_rows: dict[str, list[dict]] = defaultdict(list)
    for a in attempts:
        idea = by_id[a["idea_id"]]
        family_rows[idea["history_key"]].append(a)
        category_rows[idea["category"] or "legacy"].append(a)
    return {"scope": "lifetime", "hypotheses": ideas, "attempts": attempts,
            "totals": _campaign_counts(attempts),
            "by_family": {k: aggregate(v) for k, v in sorted(family_rows.items())},
            "by_category": {k: aggregate(v) for k, v in sorted(category_rows.items())},
            "negative_results": sorted(negatives, key=lambda n: n["id"]),
            "negative_results_count": count,
            "trial_count_note": "Claims are attempt slots, not independent statistical trials."}


def _campaign_counts(rows: list[dict]) -> dict[str, int]:
    outcomes = [r["outcome"] for r in rows]
    rejected = sum(outcomes.count(o.value) for o in (
        AttemptOutcome.HOLDOUT_NEGATIVE, AttemptOutcome.WALKFORWARD_REFUTED,
        AttemptOutcome.SWEEP_UNSTABLE))
    preview = outcomes.count(AttemptOutcome.CANDIDATE_PREVIEW_PASS.value)
    promoted = outcomes.count(AttemptOutcome.PROMOTED_CANDIDATE.value)
    unfinished = outcomes.count(None)
    return {"attempted": len(rows), "completed": len(rows) - unfinished,
            "unfinished": unfinished,
            "invalid": outcomes.count(AttemptOutcome.INTEGRITY_FAIL.value),
            "run_error": outcomes.count(AttemptOutcome.RUN_ERROR.value),
            "abandoned": outcomes.count(AttemptOutcome.ABANDONED.value),
            "economic_rejected": rejected, "economic_evaluated": rejected + preview + promoted,
            "preview_pass": preview, "promoted_candidate": promoted}
