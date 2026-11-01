#!/usr/bin/env python3
"""Executable SYNTHETIC_FIXTURE feedback demonstration. Requires a NEW disposable directory."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from algua.config.settings import Settings
from algua.contracts.idea import (
    AttemptOutcome,
    DataCapability,
    Horizon,
    IdeaStatus,
    Market,
    SourceType,
)
from algua.knowledge.experience import render_campaign_experience, write_experience_note
from algua.registry.campaign_read import read_campaign_scorecard
from algua.registry.db import connect, migrate
from algua.registry.idea_attempts import IdeaAttemptsRepository
from algua.registry.ideas import IdeaRepository
from algua.registry.negative_results import record_negative_result


def menu(path: Path, destination: Path) -> dict:
    env = {**os.environ, "ALGUA_DB_PATH": str(path),
           "ALGUA_KNOWLEDGE_DIR": str(path.parent / "kb")}
    command = [sys.executable, "-c", "from algua.cli.main import main; main()",
               "research", "campaign-menu", "--budget", "4", "--novelty-min", "1",
               "--novelty-max", "4"]
    result = subprocess.run(command, env=env, capture_output=True, text=True, check=True)
    payload = json.loads(result.stdout)
    destination.write_text(result.stdout)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="new directory; refuses reuse, never uses ALGUA_DB_PATH")
    directory = parser.parse_args().output_dir.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    path = directory / "SYNTHETIC_FIXTURE.db"
    conn = connect(path)
    try:
        migrate(conn)  # Only this newly created disposable fixture DB is bootstrapped.
        ideas = IdeaRepository(conn)

        def add(text: str, family: str, *, duplicate_of_idea_id: int | None = None,
                source_ref: str = "SYNTHETIC_FIXTURE", source_date: str | None = None,
                falsification: str = "SYNTHETIC_FIXTURE: no economic assertion",
                override_reason: str | None = None):
            return ideas.add(title=text, hypothesis=text, family=family, category=family,
                tags=["SYNTHETIC_FIXTURE"], source_type=SourceType.MANUAL,
                source_ref=source_ref, source_date=source_date, source_note=None,
                required_data=[DataCapability.OHLCV], status=IdeaStatus.OPEN,
                market=Market.US_EQUITIES, horizon=Horizon.DAILY,
                falsification=falsification, duplicate_of_idea_id=duplicate_of_idea_id,
                override_reason=override_reason)

        rejected = add("opening auction pressure persistence", "a")
        add("quarterly dividend seasonal drift", "a")
        error = add("overnight earnings dispersion reversal", "b")
        add("analyst forecast disagreement turnover", "b")
        invalid = add("filing timestamp mismatch sensitivity", "c")
        unfinished = add("weekly liquidity squeeze unwind", "d")
        preview = add("closing inventory imbalance correction", "e")
        abandoned = add("sector rebalance calendar pressure", "f")
        add("index constituent migration lag", "g")
        add(rejected.title, "a")  # This duplicate must never receive an unreasoned slot.
    finally:
        conn.close()
    before = menu(path, directory / "menu-before.json")
    fixture_outcomes = [
        (rejected, AttemptOutcome.HOLDOUT_NEGATIVE, "fixture economic rejection"),
        (error, AttemptOutcome.RUN_ERROR, "fixture unavailable input file"),
        (invalid, AttemptOutcome.INTEGRITY_FAIL, "fixture non-PIT input"),
        (unfinished, None, "fixture intentionally unfinished"),
        (preview, AttemptOutcome.CANDIDATE_PREVIEW_PASS, "fixture preview only; no promotion"),
        (abandoned, AttemptOutcome.ABANDONED, "fixture abandoned before conclusion"),
    ]
    outcomes_file = directory / "SYNTHETIC_FIXTURE-outcomes.json"
    outcomes_file.write_text(json.dumps([
        {"idea_id": i.id, "outcome": o, "reason": reason}
        for i, o, reason in fixture_outcomes], indent=2) + "\n")
    conn = connect(path)
    try:
        ideas = IdeaRepository(conn)
        attempts = IdeaAttemptsRepository(conn)
        for idea, outcome, reason in fixture_outcomes:
            (claimed,) = attempts.claim(run_stamp="SYNTHETIC_FIXTURE", limit=1, ttl_minutes=180,
                                       category=idea.category)
            assert claimed.id == idea.id
            if outcome is not None:
                assert claimed.claim_token is not None
                attempts.record_outcome(idea.id, token=claimed.claim_token, outcome=outcome,
                    reason="SYNTHETIC_FIXTURE: " + reason, evidence_ref=str(outcomes_file))
        record = {"kind": "dead_end", "verdict": "UNTESTED", "actor": "system",
                  "source": "manual", "reason": "SYNTHETIC_FIXTURE: unavailable input file",
                  "hypothesis": error.hypothesis, "created_at": "2026-01-01T00:00:00+00:00"}
        record_id = record_negative_result(conn, **record)
        # A justification must be created AFTER the evidence it responds to.
        rejection_id = attempts.attempts_of(rejected.id)[-1]["id"]
        add(rejected.title, "a", duplicate_of_idea_id=rejected.id,
            source_ref="SYNTHETIC_FIXTURE-auction-timestamps-v2", source_date="2026-01-02",
            falsification="SYNTHETIC_FIXTURE: reject if auction-only net next-session return <= 0",
            override_reason=("changed_fields=source_ref,source_date,falsification; "
                f"ideas:{rejected.id} idea_attempts:{rejection_id}; "
                "Archived auction-only timestamps replace daily close; "
                "test net next-session drift"))
    finally:
        conn.close()
    after = menu(path, directory / "menu-after.json")
    history = read_campaign_scorecard(path)
    # Only the KB path is consumed by the note writer. Do not load operator env/.env secrets.
    settings = Settings.model_construct(knowledge_dir=directory / "kb", db_path=path)
    # Exercise the existing per-result experience surface and a derived consolidated family note.
    write_experience_note(settings, record, record_id=record_id)
    note = directory / "kb" / "experience" / "SYNTHETIC_FIXTURE-campaign.md"
    note.write_text(render_campaign_experience(history))
    result = {
        "provenance": "SYNTHETIC_FIXTURE; no autonomous cycles or market qualification",
        "registry": str(path), "registry_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "example_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "outcomes_sha256": hashlib.sha256(outcomes_file.read_bytes()).hexdigest(),
        "outcomes_source": str(outcomes_file), "family_note": str(note),
        "before": {k: before[k] for k in ("choices", "exclusions", "unallocated_budget")},
        "after": {k: after[k] for k in ("choices", "exclusions", "unallocated_budget")},
        "denominators_before": before["scorecard"]["totals"],
        "denominators_after": after["scorecard"]["totals"],
        "negative_results_count": after["scorecard"]["negative_results_count"],
        "limits": "Attempt slots and declared novelty only; no independent trial or alpha estimate",
    }
    for label, snapshot in (("before", before), ("after", after)):
        by_id = {h["id"]: h for h in snapshot["scorecard"]["hypotheses"]}
        result[label]["summary"] = {
            "selected_slots": sum(c["budget"] for c in snapshot["choices"]),
            "novel_slots": sum(by_id[c["hypothesis_id"]]["history_key"]
                               not in snapshot["scorecard"]["by_family"]
                               for c in snapshot["choices"]),
            "duplicate_exclusions": sum("duplicate" in r["reason"]
                                        for r in snapshot["exclusions"].values()),
            "observed_attempts": snapshot["scorecard"]["totals"]["attempted"],
            "completed_attempts": snapshot["scorecard"]["totals"]["completed"],
            "unfinished_attempts": snapshot["scorecard"]["totals"]["unfinished"],
        }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
