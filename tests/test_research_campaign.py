"""Functional adoption with trusted fixtures and the real persisted attempt ledger."""
from __future__ import annotations

import json
from copy import deepcopy

import pytest

from algua.operator.research_cycle import CycleLimits, ResearchCycle
from algua.registry.db import connect, migrate
from algua.registry.idea_scorecard import campaign_scorecard
from tests.campaign_fixtures import add_idea


@pytest.fixture
def pool(tmp_path):
    conn = connect(tmp_path / "fixture.db")
    migrate(conn)
    for text, family in [("auction imbalance persistence", "a"),
                         ("weekly dividend seasonality", "a"),
                         ("earnings dispersion reversal", "b"),
                         ("overnight liquidity recovery", "c")]:
        add_idea(conn, text, family=family)
    yield conn
    conn.close()


def request(**kwargs):
    return {"limits": CycleLimits(max_hypotheses=3),
            "context": {"snapshot": "SYNTHETIC_FIXTURE", "seed": 42},
            "ttl_minutes": 180, **kwargs}


def choose(menu, *ids):
    return {"menu": menu, "selection": {"menu_id": menu["menu_id"], "choices": [
        {**c, "reason": "SYNTHETIC_FIXTURE chooser: test this mechanism using cited evidence"}
        for idea_id in ids for c in menu["choices"] if c["hypothesis_id"] == idea_id]}}


def finish(cycle, tmp_path, outcomes):
    report = tmp_path / f"{cycle.cycle_id}.md"
    report.write_text("```json\n" + json.dumps({"hypotheses": [
        {"idea_id": i, "title": "Trusted fixture", "outcome": o,
         "reason": "SYNTHETIC_FIXTURE controlled outcome"} for i, o in outcomes]}) + "\n```\n")
    return cycle.finish(phase="completed", worker_exit=0, report=report,
                        evidence_ref=f"SYNTHETIC_FIXTURE:{cycle.cycle_id}")


def test_two_cycles_use_explicit_non_top_choice_and_causal_feedback(pool, tmp_path):
    first = ResearchCycle(pool, tmp_path / "cycles", "first")
    menu = first.campaign_menu(**request())
    assert [c["hypothesis_id"] for c in menu["choices"]] == [1, 2, 3]
    assert first.campaign_menu(**request()) == menu
    adoption = choose(menu, 2, 1)  # explicit order; no automatic top-pick or unselected work
    claimed, running = first.start(**request(), campaign=adoption)
    assert [i.id for i in claimed] == [2, 1]
    assert running["unfinished_count"] == 2
    assert campaign_scorecard(pool)["totals"]["economic_evaluated"] == 0
    original = first.path.read_bytes()
    adoption["selection"]["choices"][0]["reason"] = "mutated by caller"
    assert first.path.read_bytes() == original
    done = finish(first, tmp_path, [(1, "holdout_negative"), (2, "run_error"),
                                    (4, "candidate_preview_pass")])
    assert done["attempts_total"] == 2 and done["error_count"] == 1
    second = ResearchCycle(pool, tmp_path / "cycles", "second")
    after = second.campaign_menu(**request())
    assert [c["hypothesis_id"] for c in after["choices"]] == [3, 4]
    assert after["scorecard"]["totals"]["economic_rejected"] == 1
    assert after["scorecard"]["totals"]["economic_evaluated"] == 1
    assert set(after["exclusions"]["1"]["prior_evidence_ids"]) == {"ideas:1", "idea_attempts:2"}
    claimed, _ = second.start(**request(), campaign=choose(after, 4))
    assert [i.id for i in claimed] == [4]
    final = finish(second, tmp_path, [(4, "integrity_fail")])
    assert final["attempts_total"] == 1
    assert [a["idea_id"] for a in campaign_scorecard(pool)["attempts"]] == [2, 1, 4]
    assert campaign_scorecard(pool)["totals"]["economic_evaluated"] == 1
    assert second.start(**request(), campaign=choose(after, 4))[0] == []
    assert len(second.rows()) == 1


@pytest.mark.parametrize("change", ["id", "duplicate", "reason", "budget", "bool_budget",
                                    "category", "evidence", "stale", "shape", "menu_shape"])
def test_invalid_selection_never_claims(pool, tmp_path, change):
    cycle = ResearchCycle(pool, tmp_path / "cycles", "invalid")
    menu = cycle.campaign_menu(**request())
    campaign = choose(menu, 1)
    c = campaign["selection"]["choices"][0]
    if change == "id":
        c["hypothesis_id"] = 4
    elif change == "duplicate":
        campaign["selection"]["choices"].append(deepcopy(c))
    elif change == "reason":
        c["reason"] = "   "
    elif change == "budget":
        c["budget"] = 2
    elif change == "bool_budget":
        c["budget"] = True
    elif change == "category":
        c["category"] = "elsewhere"
    elif change == "evidence":
        c["prior_evidence_ids"] = ["idea_attempts:999"]
    elif change == "stale":
        campaign["selection"]["menu_id"] = "stale"
    elif change == "shape":
        campaign["selection"]["choices"] = None
    else:
        campaign["menu"] = {"menu_id": menu["menu_id"]}
    with pytest.raises(ValueError):
        cycle.start(**request(), campaign=campaign)
    assert cycle.rows() == []
    assert campaign_scorecard(pool)["totals"]["economic_evaluated"] == 0


@pytest.mark.parametrize("change", ["context", "budget", "ttl", "category", "feedback", "menu"])
def test_context_and_feedback_drift_refuse(pool, tmp_path, change):
    cycle = ResearchCycle(pool, tmp_path / "cycles", "drift")
    menu = cycle.campaign_menu(**request())
    args = request()
    if change == "context":
        args["context"] = {"snapshot": "other"}
    elif change == "budget":
        args["limits"] = CycleLimits(max_hypotheses=2)
    elif change == "ttl":
        args["ttl_minutes"] = 181
    elif change == "category":
        args["category"] = "b"
    elif change == "feedback":
        add_idea(pool, "intraday closing dispersion", family="new")
    else:
        menu["choices"][0]["reason"] = "edited policy recommendation"
    with pytest.raises(ValueError):
        cycle.start(**args, campaign=choose(menu, 1))
    assert cycle.rows() == []


def test_race_between_menu_and_claim_aborts_without_fallback(pool, tmp_path, monkeypatch):
    from algua.registry.idea_attempts import IdeaAttemptsRepository

    cycle = ResearchCycle(pool, tmp_path / "cycles", "raced")
    campaign = choose(cycle.campaign_menu(**request()), 1, 2)
    original = IdeaAttemptsRepository.claim

    def raced(self, **kwargs):
        other = connect(tmp_path / "fixture.db")
        try:
            original(IdeaAttemptsRepository(other), run_stamp="competing", limit=1, ttl_minutes=180)
        finally:
            other.close()
        return original(self, **kwargs)

    monkeypatch.setattr(IdeaAttemptsRepository, "claim", raced)
    with pytest.raises(ValueError, match="stale"):
        cycle.start(**request(), campaign=campaign)
    assert cycle.rows() == []
    assert [a["idea_id"] for a in campaign_scorecard(pool)["attempts"]] == [1]


def test_selected_claim_cas_failure_rolls_back_entire_batch(pool, tmp_path):
    from algua.registry.idea_attempts import ClaimTokenMismatch

    cycle = ResearchCycle(pool, tmp_path / "cycles", "cas")
    campaign = choose(cycle.campaign_menu(**request()), 1, 2)
    # Trusted fault fixture: make the second UPDATE affect zero rows inside BEGIN IMMEDIATE.
    pool.execute("CREATE TRIGGER fixture_race BEFORE UPDATE OF claimed_by ON ideas "
                 "WHEN NEW.id=2 BEGIN SELECT RAISE(IGNORE); END")
    pool.commit()
    with pytest.raises(ClaimTokenMismatch):
        cycle.start(**request(), campaign=campaign)
    assert cycle.rows() == []
    held = pool.execute("SELECT COUNT(*) FROM ideas WHERE claimed_by IS NOT NULL").fetchone()[0]
    assert held == 0


@pytest.mark.parametrize("cost", [None, 0.0])
def test_explicit_noop_and_unknown_cost_never_claim_other_work(pool, tmp_path, cost):
    cycle = ResearchCycle(pool, tmp_path / "cycles", "noop")
    args = request(limits=CycleLimits(max_hypotheses=3, max_cost=cost))
    campaign = choose(cycle.campaign_menu(**args), *([1] if cost is not None else []))
    claimed, result = cycle.start(**args, campaign=campaign)
    assert claimed == [] and result["attempts_total"] == result["ok_count"] == 0
    assert result["phase"] == ("cost_unknown" if cost is not None else "pool_empty")
    assert campaign_scorecard(pool)["totals"]["attempted"] == 0


def test_cli_menu_choice_claim_boundary_and_json_refusals(pool, tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from algua.cli.main import app

    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "fixture.db"))
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path / "data"))
    runner = CliRunner()
    args = ["research", "idea", "cycle-start", "--run", "cli", "--limit", "3"]
    preview = runner.invoke(app, [*args, "--menu-only"])
    assert preview.exit_code == 0, preview.stdout
    menu = json.loads(preview.stdout)["menu"]
    assert pool.execute("SELECT COUNT(*) FROM idea_attempts").fetchone()[0] == 0
    assert not (tmp_path / "data/research-cycles/cli.json").exists()
    path = tmp_path / "choice.json"
    path.write_text(json.dumps(choose(menu, 2)))
    started = runner.invoke(app, [*args, "--campaign", str(path)])
    assert started.exit_code == 0, started.stdout
    payload = json.loads(started.stdout)
    assert [i["id"] for i in payload["claimed"]] == [2]
    assert payload["campaign"]["selection"]["choices"][0]["reason"].startswith("SYNTHETIC")
    path.write_text('{"menu":{}}')
    refused = runner.invoke(app, [*args, "--campaign", str(path)])
    assert refused.exit_code == 1, refused.stdout
    assert json.loads(refused.stdout)["ok"] is False
    assert pool.execute("SELECT COUNT(*) FROM idea_attempts").fetchone()[0] == 1


def test_actual_driver_passes_opt_in_selection_to_real_cli(pool, tmp_path):
    import os
    import shlex
    import subprocess
    import sys
    from pathlib import Path

    driver = Path('.opencode/scripts/run-research-loop.sh').read_text()
    # Execute argument parsing and the real claim block only: no worktree/runtime/operations.
    parser = driver[driver.index('while [[ $#'):driver.index('\nREPO_ROOT=')]
    source = driver[driver.index('  CLAIM_ARGS=('):driver.index('  N_CLAIMED=')]
    env = {**os.environ, "ALGUA_DB_PATH": str(tmp_path / "fixture.db"),
           "ALGUA_DATA_DIR": str(tmp_path / "data")}
    entry = 'from algua.cli.main import main; main()'
    preview = subprocess.run([sys.executable, '-c', entry, 'research', 'idea', 'cycle-start',
                              '--run', 'driver', '--limit', '3', '--menu-only'],
                             env=env, text=True, capture_output=True)
    assert preview.returncode == 0, preview.stderr
    path = tmp_path / 'choice.json'
    path.write_text(json.dumps(choose(json.loads(preview.stdout)['menu'], 2)))
    values = {"AUTH_DB": env["ALGUA_DB_PATH"], "AUTH_DATA_DIR": env["ALGUA_DATA_DIR"],
              "STAMP": "driver", "N_HYPOTHESES": "3", "TIMEOUT": "45m", "WORKER_LIMIT": "1",
              "CPU_SECONDS": "2700", "MEMORY_MB": "16384", "FILE_MB": "512", "MAX_COST": "",
              "CATEGORY": "", "CAMPAIGN": ""}
    preamble = 'set -euo pipefail\n' + '\n'.join(
        f'{k}={shlex.quote(v)}' for k, v in values.items())
    preamble += f'\nAUTH_CLI=({shlex.quote(sys.executable)} -c {shlex.quote(entry)})\n'
    preamble += 'set -- --campaign ' + shlex.quote(str(path)) + '\n'
    # Keep the prepared interpreter for the existing JSON extraction in this bounded fixture.
    source = source.replace('python3 -c', shlex.quote(sys.executable) + ' -c')
    command = preamble + parser + source + '\nprintf "%s" "$CLAIMED_JSON"'
    run = subprocess.run(['bash', '-c', command],
                         env=env, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert [r['id'] for r in json.loads(run.stdout)] == [2]
    assert pool.execute("SELECT COUNT(*) FROM idea_attempts").fetchone()[0] == 1
    # A malformed reply must fail the same driver block without falling back to legacy work.
    path.write_text('{}')
    refused = subprocess.run(['bash', '-c', preamble + parser + source], env=env,
                             capture_output=True, text=True)
    assert refused.returncode != 0
    assert pool.execute("SELECT COUNT(*) FROM idea_attempts").fetchone()[0] == 1


def test_persisted_controller_example_is_repeatable(tmp_path):
    import subprocess
    import sys

    results = []
    for name in ("first", "replay"):
        directory = tmp_path / name
        run = subprocess.run([sys.executable, 'scripts/examples/campaign_cycles.py',
                              '--output-dir', str(directory)], capture_output=True, text=True)
        assert run.returncode == 0, run.stderr
        result = json.loads(run.stdout)
        results.append(result['deterministic_projection'])
        assert (directory / 'SYNTHETIC_FIXTURE.db').exists()
        assert (directory / 'research-cycles/fixture-two.json').exists()
        assert result['deterministic_projection']['menus'] == [[1, 2, 3], [5, 4, 2]]
        assert result['deterministic_projection']['claims'] == [[1, 3], [4, 2]]
        assert result['deterministic_projection']['totals']['economic_evaluated'] == 1
        assert result['deterministic_projection']['totals']['invalid'] == 1
        assert result['deterministic_projection']['totals']['run_error'] == 2
    assert results[0] == results[1]


def test_category_restriction_keeps_policy_dedup_and_can_admit_later_family(pool, tmp_path):
    cycle = ResearchCycle(pool, tmp_path / "cycles", "category")
    args = request(limits=CycleLimits(max_hypotheses=1), category="c")
    menu = cycle.campaign_menu(**args)
    assert [c["hypothesis_id"] for c in menu["choices"]] == [4]
    claimed, _ = cycle.start(**args, campaign=choose(menu, 4))
    assert [i.id for i in claimed] == [4]


def test_new_evidence_duplicate_is_admitted_and_bare_duplicate_is_not(pool, tmp_path):
    first = ResearchCycle(pool, tmp_path / "cycles", "prior")
    before = first.campaign_menu(**request())
    first.start(**request(), campaign=choose(before, 1))
    finish(first, tmp_path, [(1, "holdout_negative")])
    bare = add_idea(pool, "auction imbalance persistence", family="a")
    changed = add_idea(pool, "auction imbalance persistence", family="a",
        duplicate_of_idea_id=1, source_ref="SYNTHETIC_FIXTURE-archived-auction-v2",
        override_reason="changed_fields=source_ref; ideas:1 idea_attempts:1; "
                        "Archived auction timestamps replace daily close sampling")
    next_cycle = ResearchCycle(pool, tmp_path / "cycles", "changed-inputs")
    args = request(limits=CycleLimits(max_hypotheses=6))
    after = next_cycle.campaign_menu(**args)
    assert str(bare.id) in after["exclusions"]
    option = next(c for c in after["choices"] if c["hypothesis_id"] == changed.id)
    assert "idea_attempts:1" in option["prior_evidence_ids"]
    assert "new justification" in option["reason"]
    claimed, _ = next_cycle.start(**args, campaign=choose(after, changed.id))
    assert [i.id for i in claimed] == [changed.id]


def test_novelty_reservation_stays_unspent_when_only_familiar_work_is_eligible(pool, tmp_path):
    from algua.contracts.idea import AttemptOutcome
    from tests.campaign_fixtures import attempt

    attempt(pool, pool_idea(pool, 1), AttemptOutcome.RUN_ERROR)
    cycle = ResearchCycle(pool, tmp_path / "cycles", "reserve")
    args = request(limits=CycleLimits(max_hypotheses=1), category="a")
    menu = cycle.campaign_menu(**args)
    assert menu["choices"] == []
    claimed, result = cycle.start(**args, campaign=choose(menu))
    assert claimed == [] and result["attempts_total"] == 0
    assert campaign_scorecard(pool)["totals"]["economic_evaluated"] == 0


def pool_idea(conn, idea_id):
    from algua.registry.ideas import IdeaRepository

    return IdeaRepository(conn).get(idea_id)


def test_campaign_reaps_expired_legacy_claim_without_retrying_attempted_idea(pool, tmp_path):
    from datetime import UTC, datetime, timedelta

    from algua.registry.idea_attempts import IdeaAttemptsRepository

    repo = IdeaAttemptsRepository(pool)
    held = repo.claim(run_stamp="old-legacy", limit=1, ttl_minutes=180,
                     now=datetime.now(UTC) - timedelta(hours=4))
    assert [i.id for i in held] == [1]
    cycle = ResearchCycle(pool, tmp_path / "cycles", "after-ttl")
    menu = cycle.campaign_menu(**request())
    assert not any("claim_token" in h for h in menu["scorecard"]["hypotheses"])
    assert "1" in menu["exclusions"]
    claimed, _ = cycle.start(**request(), campaign=choose(menu, 3))
    assert [i.id for i in claimed] == [3]
    assert repo.attempts_of(1)[0]["outcome"] == "abandoned"
    assert campaign_scorecard(pool)["totals"]["economic_evaluated"] == 0



def test_malformed_bundle_and_edited_menu_refuse_before_publishing_context(pool, tmp_path):
    cycle = ResearchCycle(pool, tmp_path / "cycles", "shape")
    for malformed in ({}, [], "not a bundle", {"menu": {}}):
        with pytest.raises(ValueError):
            cycle.start(**request(), campaign=malformed)
        assert not cycle.path.exists()
    args = request(limits=CycleLimits(max_hypotheses=3, max_cost=0))
    menu = cycle.campaign_menu(**args)
    menu["choices"][0]["reason"] = "edited policy"
    with pytest.raises(ValueError):
        cycle.start(**args, campaign=choose(menu))
    assert not cycle.path.exists()


def test_duplicate_choice_is_rejected_before_any_claim_call(pool, tmp_path, monkeypatch):
    cycle = ResearchCycle(pool, tmp_path / "cycles", "duplicate")
    campaign = choose(cycle.campaign_menu(**request()), 1)
    campaign["selection"]["choices"] *= 2
    calls = []
    monkeypatch.setattr(cycle.attempts, "claim", lambda **kwargs: calls.append(kwargs))
    with pytest.raises(ValueError):
        cycle.start(**request(), campaign=campaign)
    assert calls == [] and not cycle.path.exists()


def test_direct_campaign_claim_obeys_explicit_lower_slot_budget(pool, tmp_path):
    from algua.registry.idea_attempts import IdeaAttemptsRepository

    cycle = ResearchCycle(pool, tmp_path / "cycles", "budget")
    campaign = choose(cycle.campaign_menu(**request()), 1, 2)
    with pytest.raises(ValueError, match="budget"):
        IdeaAttemptsRepository(pool).claim(run_stamp="budget", limit=1, ttl_minutes=180,
                                           campaign=campaign)
    assert cycle.rows() == []


@pytest.mark.parametrize(("field", "value"), [
    ("run_stamp", "other"), ("category", "b"), ("ttl_minutes", 1),
    ("preview_hold_hours", 1), ("max_cost", 0.0), ("max_cost", 1.0),
])
def test_direct_campaign_claim_rejects_resource_conflicts_before_reaping(
        pool, tmp_path, monkeypatch, field, value):
    from datetime import UTC, datetime, timedelta

    from algua.registry.idea_attempts import IdeaAttemptsRepository

    repo = IdeaAttemptsRepository(pool)
    repo.claim(run_stamp="old-legacy", limit=1, ttl_minutes=180, category="b",
               now=datetime.now(UTC) - timedelta(hours=4))
    cycle = ResearchCycle(pool, tmp_path / "cycles", "bound")
    limits = CycleLimits(max_cost=value) if field == "max_cost" else CycleLimits()
    campaign = choose(cycle.campaign_menu(**request(limits=limits, category="a")), 1)
    args = {"run_stamp": "bound", "limit": 3, "ttl_minutes": 180,
            "category": "a", "preview_hold_hours": 72}
    if field != "max_cost":
        args[field] = value
    before = list(pool.iterdump())
    reaped = []
    original = repo._reap

    def reap(**kwargs):
        reaped.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(repo, "_reap", reap)
    message = "cost.*unknown" if field == "max_cost" else "context"
    with pytest.raises(ValueError, match=message):
        repo.claim(**args, campaign=campaign)
    assert reaped == []
    assert list(pool.iterdump()) == before
    assert not pool.in_transaction


@pytest.mark.parametrize("field", ["research_cycle_id", "claim_ttl_minutes",
                                  "preview_hold_hours", "max_cost"])
def test_direct_campaign_claim_rejects_incomplete_resource_context(pool, tmp_path, field):
    from algua.registry.campaign_selection import menu_from_history
    from algua.registry.idea_attempts import IdeaAttemptsRepository

    cycle = ResearchCycle(pool, tmp_path / "cycles", "shape")
    menu = cycle.campaign_menu(**request())
    context = menu["request"]
    del (context["limits"] if field == "max_cost" else context)[field]
    campaign = choose(menu_from_history(menu["scorecard"], context), 1)
    before = list(pool.iterdump())
    with pytest.raises(ValueError, match="context"):
        IdeaAttemptsRepository(pool).claim(run_stamp="shape", limit=3, ttl_minutes=180,
                                           campaign=campaign)
    assert list(pool.iterdump()) == before
    assert not pool.in_transaction


def test_direct_campaign_claim_detaches_context_before_feedback_read(pool, tmp_path, monkeypatch):
    from algua.registry import campaign_selection
    from algua.registry.idea_attempts import IdeaAttemptsRepository

    cycle = ResearchCycle(pool, tmp_path / "cycles", "detached")
    campaign = choose(cycle.campaign_menu(**request(category="a")), 1)
    original = campaign_selection.campaign_scorecard

    def read_history(conn):
        campaign["menu"]["request"]["category"] = "b"
        campaign["selection"]["choices"].clear()
        return original(conn)

    monkeypatch.setattr(campaign_selection, "campaign_scorecard", read_history)
    claimed = IdeaAttemptsRepository(pool).claim(run_stamp="detached", limit=3, ttl_minutes=180,
                                               category="a", campaign=campaign)
    assert [(idea.id, idea.claimed_by) for idea in claimed] == [(1, "detached")]
    assert campaign["menu"]["request"]["category"] == "b"
    assert campaign["selection"]["choices"] == []


def test_direct_campaign_claim_validates_shape_before_json_detachment(pool, tmp_path):
    from algua.registry.idea_attempts import IdeaAttemptsRepository

    cycle = ResearchCycle(pool, tmp_path / "cycles", "tuple")
    campaign = choose(cycle.campaign_menu(**request()), 1)
    campaign["selection"]["choices"] = tuple(campaign["selection"]["choices"])
    before = list(pool.iterdump())
    with pytest.raises(ValueError, match="malformed"):
        IdeaAttemptsRepository(pool).claim(run_stamp="tuple", limit=3, ttl_minutes=180,
                                           campaign=campaign)
    assert list(pool.iterdump()) == before
    assert not pool.in_transaction


def test_explicit_null_campaign_cannot_downgrade_to_legacy_claims(pool, tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from algua.cli.main import app

    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "fixture.db"))
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path / "data"))
    path = tmp_path / "null-choice.json"
    path.write_text("null")
    result = CliRunner().invoke(app, ["research", "idea", "cycle-start", "--run", "null",
                                     "--limit", "3", "--campaign", str(path)])
    assert result.exit_code == 1, result.stdout
    assert json.loads(result.stdout)["ok"] is False
    assert pool.execute("SELECT COUNT(*) FROM idea_attempts").fetchone()[0] == 0
    assert not (tmp_path / "data/research-cycles/null.json").exists()


def test_menu_only_cannot_ignore_an_explicit_campaign_file(pool, tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from algua.cli.main import app

    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "fixture.db"))
    path = tmp_path / "choice.json"
    path.write_text("{}")
    result = CliRunner().invoke(app, ["research", "idea", "cycle-start", "--run", "mixed",
                                     "--limit", "3", "--menu-only", "--campaign", str(path)])
    assert result.exit_code == 1 and json.loads(result.stdout)["ok"] is False
    assert pool.execute("SELECT COUNT(*) FROM idea_attempts").fetchone()[0] == 0


def test_campaign_menu_refuses_nested_transaction_without_committing_it(pool, tmp_path):
    cycle = ResearchCycle(pool, tmp_path / "cycles", "nested")
    pool.execute("BEGIN")
    with pytest.raises(RuntimeError, match="top-level"):
        cycle.campaign_menu(**request())
    assert pool.in_transaction
    pool.rollback()


def test_legacy_select_monkeypatch_seam_still_controls_legacy_claims(pool, tmp_path, monkeypatch):
    cycle = ResearchCycle(pool, tmp_path / "cycles", "legacy-seam")
    calls = []

    def pick(**kwargs):
        calls.append(kwargs)
        return [4]

    monkeypatch.setattr(cycle.attempts, "_select", pick)
    claimed, _ = cycle.start(**request())
    assert [i.id for i in claimed] == [4]
    assert calls[0]["limit"] == 3 and calls[0]["category"] is None


@pytest.mark.parametrize("case", ["unselected", "cross_bound", "outcome_mismatch",
                                  "missing_result", "bool_bound", "result_context", "claim_context",
                                  "runerror_candidacy", "mixed_unselected", "valid"])
def test_campaign_publication_requires_selected_claim_and_matching_ledger_outcome(
        pool, tmp_path, case):
    import subprocess
    import sys
    from pathlib import Path

    from tests.test_research_run_digest import _APPEND_DIGEST_SRC, _ec

    cycle = ResearchCycle(pool, tmp_path / "cycles", "publication")
    campaign = choose(cycle.campaign_menu(**request()), 1)
    cycle.start(**request(), campaign=campaign)
    outcome = ("run_error" if case in {"outcome_mismatch", "runerror_candidacy"}
               else "candidate_preview_pass")
    result = finish(cycle, tmp_path, [(1, outcome)])
    if case == "result_context":
        result["research_cycle_id"] = "other-cycle"
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps(result))
    idea_id = 4 if case == "unselected" else 1
    mb_id = True if case == "bool_bound" else (4 if case == "cross_bound" else idea_id)
    report = tmp_path / "trailer.md"
    report.write_text('```json\n' + json.dumps({"hypotheses": [{
        "idea_id": idea_id, "title": "Trusted fixture",
        "outcome": "run_error" if case == "runerror_candidacy" else "candidate_preview_pass",
        "reason": "SYNTHETIC_FIXTURE", "verdict": "candidate-preview-pass",
        "merge_back": {"idea_id": mb_id, "strategy": "fixture_strategy", "universe": "fixture",
                       "start": "2024-01-01", "end": "2024-06-01", "eval_context": _ec()}}]
    }) + '\n```\n')
    if case == "mixed_unselected":
        trailer = json.loads(report.read_text().split('```json\n')[1].split('\n```')[0])
        extra = deepcopy(trailer["hypotheses"][0])
        extra["idea_id"] = extra["merge_back"]["idea_id"] = 4
        extra["merge_back"]["strategy"] = "unselected_fixture"
        trailer["hypotheses"].append(extra)
        report.write_text('```json\n' + json.dumps(trailer) + '\n```\n')
    digest, queue = tmp_path / 'digest.jsonl', tmp_path / 'queue.json'
    claimed = [{"id": r["idea_id"], "claim_token": r["claim_token"]} for r in cycle.rows()]
    if case == "claim_context":
        claimed.append({"id": 4, "claim_token": "SYNTHETIC_FIXTURE-extra"})
    args = [str(digest), 'completed', 'publication', 'research-run/fixture', '', '0', '0', '1',
            '1', '0', str(report), 'fixture_strategy', str(Path.cwd()), str(queue),
            str(tmp_path / 'queue.lock'), '', json.dumps(claimed),
            str(result_path) if case != "missing_result" else '', 'explicit-campaign.json']
    run = subprocess.run([sys.executable, '-', *args], input=_APPEND_DIGEST_SRC,
                         capture_output=True, text=True, cwd=Path.cwd())
    assert run.returncode == 0, run.stderr
    items = json.loads(queue.read_text())["items"] if queue.exists() else {}
    assert len(items) == int(case in {"valid", "mixed_unselected"}), (run.stdout, items)
    if case in {"valid", "mixed_unselected"}:
        item = next(iter(items.values()))
        assert item['idea_id'] == 1 and item['claim_token'] == claimed[0]['claim_token']
    if case == "unselected":
        assert json.loads(digest.read_text())["hypotheses"] == []
