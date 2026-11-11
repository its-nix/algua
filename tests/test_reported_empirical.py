"""Worker-reported falsification is advisory, distinct from DB qualification outcomes."""
from __future__ import annotations

import json
from copy import deepcopy

import pytest

from algua.contracts.idea import AttemptOutcome
from algua.operator.research_memory_index import list_retained_research
from algua.registry.db import connect, migrate
from algua.registry.idea_attempts import IdeaAttemptsRepository
from algua.registry.idea_scorecard import campaign_scorecard
from tests.campaign_fixtures import add_idea
from tests.test_research_memory_index import REFERENCE, fingerprint


@pytest.fixture
def history(tmp_path, monkeypatch):
    monkeypatch.setenv('ALGUA_DATA_DIR', str(tmp_path))
    database = tmp_path / 'authority.db'
    conn = connect(database)
    migrate(conn)
    idea = add_idea(conn, 'SYNTHETIC_FIXTURE empirical comparison', family='fixture')
    repo = IdeaAttemptsRepository(conn)
    (claimed,) = repo.claim(run_stamp='cycle-fixture', limit=1, ttl_minutes=60)
    repo.record_outcome(idea.id, token=claimed.claim_token, outcome=AttemptOutcome.DATA_BLOCKED,
                        reason='proxy cannot qualify', evidence_ref=REFERENCE)
    record = dict(research_cycle_id='cycle-fixture', stamp='cycle-fixture', outcome='completed',
        exit_code=0, worker_exit_code=0, timed_out=False, rate_limited=False,
        trailer_parse_error=False, idea_ids=[idea.id],
        controller=dict(research_cycle_id='cycle-fixture', phase='completed', attempts_total=1,
            terminal_count=1, unfinished_count=0, write_error_count=0, invalid_count=0,
            error_count=0, ok_count=0, idea_ids=[idea.id], outcome_counts={'data_blocked': 1}),
        hypotheses=[dict(idea_id=idea.id, outcome='data_blocked',
                         falsification_assessment='refuted')])
    path = tmp_path / 'research-runs.jsonl'
    try:
        yield conn, database, path, record
    finally:
        conn.close()


def test_data_blocked_keeps_its_reported_refutation_without_authority_or_writes(history):
    conn, database, path, record = history
    path.write_text(json.dumps(record) + '\n')
    before = fingerprint(database), path.read_bytes(), path.stat().st_mtime_ns
    sc = campaign_scorecard(conn)
    assert sc['attempts'][0]['reported_falsification_assessment'] == 'refuted'
    assert sc['totals']['data_blocked'] == 1 and sc['totals']['economic_rejected'] == 0
    assert sc['reported_empirical']['counts'] == dict(refuted=1, survived=0, untested=0, unknown=0)
    assert sc['reported_empirical']['authority'] == 'none'
    assert sc['by_family']['family:fixture']['reported_empirical']['refuted'] == 1
    row = list_retained_research(database)['attempts'][0]
    assert row['reported_falsification_assessment'] == 'refuted'
    assert row['outcome'] == 'data_blocked'
    assert (fingerprint(database), path.read_bytes(), path.stat().st_mtime_ns) == before


@pytest.mark.parametrize('mutation', [
    lambda r: r.update(worker_exit_code=1),
    lambda r: r.update(timed_out=True),
    lambda r: r.update(trailer_parse_error=True),
    lambda r: r.update(idea_ids=[99]),
    lambda r: r['controller'].update(unfinished_count=1),
    lambda r: r['controller'].update(outcome_counts={'integrity_fail': 1}),
    lambda r: r['hypotheses'][0].update(idea_id=99),
    lambda r: r['hypotheses'][0].update(outcome='run_error'),
    lambda r: r['hypotheses'][0].update(falsification_assessment='profitable'),
    lambda r: r['hypotheses'].append(deepcopy(r['hypotheses'][0])),
])
def test_mismatched_or_failed_reports_stay_unknown(history, mutation):
    conn, _, path, record = history
    mutation(record)
    path.write_text(json.dumps(record) + '\n')
    assert campaign_scorecard(conn)['attempts'][0]['reported_falsification_assessment'] == 'unknown'


@pytest.mark.parametrize('content', [None, '{bad}\n', '[]\n', 'x' * (2 * 1024 * 1024 + 1)])
def test_missing_corrupt_or_excessive_digest_is_honest_unknown(history, content):
    conn, _, path, _ = history
    if content is not None:
        path.write_text(content)
    sc = campaign_scorecard(conn)
    assert sc['reported_empirical']['counts']['unknown'] == 1
    assert sc['reported_empirical']['status'] == 'unavailable'


def test_duplicate_digest_cycle_is_unknown_even_when_both_rows_agree(history):
    conn, _, path, record = history
    path.write_text((json.dumps(record) + '\n') * 2)
    assert campaign_scorecard(conn)['attempts'][0]['reported_falsification_assessment'] == 'unknown'


def test_legacy_missing_assessment_does_not_mean_untested(history):
    conn, _, path, record = history
    record['hypotheses'][0].pop('falsification_assessment')
    path.write_text(json.dumps(record) + '\n')
    assert campaign_scorecard(conn)['reported_empirical']['counts']['unknown'] == 1


def test_chooser_and_experience_keep_both_axes_and_no_admission_rules_change(history):
    from algua.knowledge.experience import render_campaign_experience
    from algua.operator.campaign_choice import _prompt_menu
    from algua.research.campaign_policy import campaign_menu

    conn, _, path, record = history
    add_idea(conn, 'SYNTHETIC_FIXTURE unrelated novel direction', family='new')
    before = campaign_menu(campaign_scorecard(conn), budget=1)
    path.write_text(json.dumps(record) + '\n')
    sc = campaign_scorecard(conn)
    assert campaign_menu(sc, budget=1) == before  # Reported alpha cannot grant eligibility.
    prompt = _prompt_menu({'scorecard': sc, 'choices': [], 'request': {}})
    assert prompt['scorecard']['attempts'][0]['reported_falsification_assessment'] == 'refuted'
    assert prompt['scorecard']['reported_empirical']['authority'] == 'none'
    note = render_campaign_experience(sc)
    assert 'reported_empirical=refuted (worker-reported)' in note
    assert 'data_blocked' in note


def test_malformed_json_duplicate_fields_and_symlinks_stay_unknown(history, tmp_path):
    conn, _, path, record = history
    raw = json.dumps(record)
    path.write_text(raw.replace('"completed"', '"completed", "outcome": "completed"', 1))
    assert campaign_scorecard(conn)['reported_empirical']['status'] == 'unavailable'
    path.unlink()
    target = tmp_path / 'external.jsonl'
    target.write_text(raw + '\n')
    path.symlink_to(target)
    assert campaign_scorecard(conn)['reported_empirical']['status'] == 'unavailable'


@pytest.mark.parametrize('mismatch', [False, True])
def test_mixed_cycle_counts_and_one_mismatch_refuses_whole_cycle(history, mismatch):
    conn, _, path, record = history
    repo = IdeaAttemptsRepository(conn)
    for outcome, assessment in [(AttemptOutcome.WALKFORWARD_REFUTED, 'refuted'),
                                 (AttemptOutcome.RUN_ERROR, 'untested')]:
        idea = add_idea(conn, f'SYNTHETIC_FIXTURE {outcome.value}', family=outcome.value)
        (claimed,) = repo.claim(run_stamp='cycle-fixture', limit=1, ttl_minutes=60)
        repo.record_outcome(idea.id, token=claimed.claim_token, outcome=outcome,
                            reason='fixture terminal', evidence_ref=REFERENCE)
        record['idea_ids'].append(idea.id)
        record['hypotheses'].append(dict(idea_id=idea.id, outcome=outcome.value,
                                        falsification_assessment=assessment))
    record['exit_code'] = 1
    record['controller'].update(attempts_total=3, terminal_count=3, error_count=1, ok_count=1,
        idea_ids=record['idea_ids'],
        outcome_counts={'data_blocked': 1, 'walkforward_refuted': 1, 'run_error': 1})
    if mismatch:
        record['hypotheses'][1]['outcome'] = 'data_blocked'
    path.write_text(json.dumps(record) + '\n')
    sc = campaign_scorecard(conn)
    assert sc['totals']['economic_rejected'] == 1
    assert sc['reported_empirical']['counts'] == (dict(refuted=0, survived=0, untested=0, unknown=3)
        if mismatch else dict(refuted=2, survived=0, untested=1, unknown=0))
