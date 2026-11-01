"""Pure policy selection from aggregate lifetime evidence."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from algua.contracts.idea import AttemptOutcome, DataCapability, Horizon
from algua.registry.db import connect, migrate
from algua.registry.idea_scorecard import campaign_scorecard
from algua.registry.negative_results import record_negative_result
from algua.research.campaign_policy import campaign_exclusions, campaign_menu
from tests.campaign_fixtures import add_idea, attempt


def test_rejected_family_changes_future_menu_with_exact_evidence(tmp_path):
    conn = connect(tmp_path / "r.db")
    try:
        migrate(conn)
        old = add_idea(conn, "old gap continuation mechanism", family="a")
        a = add_idea(conn, "dividend drift seasonal lag", family="a")
        b = add_idea(conn, "earnings dispersion earnings surprises", family="b")
        before = campaign_menu(campaign_scorecard(conn), budget=1, novelty_min=0)
        assert before[0].hypothesis_id == old.id
        attempt(conn, old, AttemptOutcome.HOLDOUT_NEGATIVE)
        after = campaign_menu(campaign_scorecard(conn), budget=1, novelty_min=0)
        assert after[0].hypothesis_id == b.id
        # With two slots, the rejected family can still be explored, with truthful causality.
        menu = campaign_menu(campaign_scorecard(conn), budget=2, novelty_min=0)
        choice = next(c for c in menu if c.hypothesis_id == a.id)
        assert "economic_rejected=1/1" in choice.reason
        assert "idea_attempts:1" in choice.prior_evidence_ids
    finally:
        conn.close()


@pytest.fixture
def history_db(tmp_path, monkeypatch):
    class Clock(datetime):
        tick = datetime(2026, 1, 1, tzinfo=UTC)

        @classmethod
        def now(cls, tz=None):
            cls.tick += timedelta(seconds=1)
            return cls.tick

    monkeypatch.setattr("algua.registry.ideas.datetime", Clock)
    monkeypatch.setattr("algua.registry.idea_attempts.datetime", Clock)
    conn = connect(tmp_path / "r.db")
    migrate(conn)
    yield conn
    conn.close()


@pytest.mark.parametrize("outcome", [AttemptOutcome.RUN_ERROR, AttemptOutcome.INTEGRITY_FAIL,
                                     AttemptOutcome.ABANDONED, None])
def test_non_alpha_failures_and_unfinished_are_not_economic_rejections(history_db, outcome):
    conn = history_db
    old = add_idea(conn, "opening imbalance persistence", family="a")
    attempt(conn, old, outcome)
    candidate = add_idea(conn, "weekly dividend seasonality", family="a")
    sc = campaign_scorecard(conn)
    (choice,) = campaign_menu(sc, budget=1, novelty_min=0)
    assert choice.hypothesis_id == candidate.id
    assert "economic_rejected=0/0" in choice.reason
    assert choice.prior_evidence_ids == ("idea_attempts:1", f"ideas:{candidate.id}")
    assert sc["totals"]["attempted"] == 1
    assert sc["totals"]["economic_evaluated"] == 0


@pytest.mark.parametrize("declaration", ["source_ref", "source_ref,source_date"])
def test_duplicate_requires_new_anchored_explanation_and_cannot_reuse_it(history_db, declaration):
    conn = history_db
    old = add_idea(conn, "opening imbalance persistence", family="a")
    attempt(conn, old, AttemptOutcome.HOLDOUT_NEGATIVE)
    bare = add_idea(conn, old.title, family="a")
    generic = add_idea(conn, old.title, family="a", duplicate_of_idea_id=old.id,
                       override_reason="try again")
    new = add_idea(conn, old.title, family="a", duplicate_of_idea_id=old.id,
                   source_ref="SYNTHETIC_FIXTURE-auction-v2",
                   override_reason=("changed_fields=source_ref; ideas:1 idea_attempts:1; "
                                    "Changed sampling to archived auction timestamps"))
    repeated = add_idea(conn, old.title, family="a", duplicate_of_idea_id=old.id,
                        source_ref="SYNTHETIC_FIXTURE-auction-v3",
                        source_date="2026-01-02",
                        override_reason=(
                            f"changed_fields={declaration}; ideas:1 idea_attempts:1; "
                            "CHANGED sampling to archived auction timestamps!"))
    sc = campaign_scorecard(conn)
    menu = campaign_menu(sc, budget=4, novelty_min=0)
    assert [c.hypothesis_id for c in menu] == [new.id]
    assert {old.id, bare.id, generic.id, repeated.id} <= set(campaign_exclusions(sc))
    assert f"ideas:{old.id}" in menu[0].prior_evidence_ids
    assert "idea_attempts:1" in menu[0].prior_evidence_ids
    assert new.override_reason in menu[0].reason


@pytest.mark.parametrize("explanation", ["", "retry", "try again", "rerun"])
def test_changed_metadata_still_requires_a_nonboilerplate_explanation(history_db, explanation):
    old = add_idea(history_db, "opening imbalance persistence", family="a")
    attempt(history_db, old, AttemptOutcome.HOLDOUT_NEGATIVE)
    candidate = add_idea(history_db, old.title, family="a", duplicate_of_idea_id=old.id,
                         source_ref="SYNTHETIC_FIXTURE-auction-v2",
                         override_reason=f"changed_fields=source_ref; ideas:1 idea_attempts:1; "
                                         f"{explanation}")
    sc = campaign_scorecard(history_db)
    assert candidate.id in campaign_exclusions(sc)


@pytest.mark.parametrize("reason", ["banana", "changed_fields=source_ref; ideas:1 "
                                  "idea_attempts:1; changed sampling"])
def test_unchanged_persisted_inputs_cannot_be_unlocked_by_free_text(history_db, reason):
    old = add_idea(history_db, "opening imbalance persistence", family="a")
    attempt(history_db, old, AttemptOutcome.HOLDOUT_NEGATIVE)
    duplicate = add_idea(history_db, old.title, family="a", duplicate_of_idea_id=old.id,
                         override_reason=reason)
    sc = campaign_scorecard(history_db)
    assert campaign_menu(sc, budget=1, novelty_min=0) == ()
    assert duplicate.id in campaign_exclusions(sc)


def test_newer_outcome_invalidates_preexisting_duplicate_even_with_its_exact_id(history_db):
    from algua.registry.idea_attempts import IdeaAttemptsRepository

    old = add_idea(history_db, "opening imbalance persistence", family="a")
    attempt(history_db, old, AttemptOutcome.RUN_ERROR)
    claimed = attempt(history_db, old)
    duplicate = add_idea(history_db, old.title, family="a", duplicate_of_idea_id=old.id,
                         source_ref="SYNTHETIC_FIXTURE-auction-v2",
                         override_reason="changed_fields=source_ref; ideas:1 idea_attempts:1 "
                                         "idea_attempts:2; archived auction sampling")
    IdeaAttemptsRepository(history_db).record_outcome(old.id, token=claimed.claim_token,
        outcome=AttemptOutcome.HOLDOUT_NEGATIVE, reason="SYNTHETIC_FIXTURE newer rejection")
    sc = campaign_scorecard(history_db)
    assert campaign_menu(sc, budget=1, novelty_min=0) == ()
    assert duplicate.id in campaign_exclusions(sc)


@pytest.mark.parametrize(("field", "old_fields", "new_fields", "eligible"), [
    ("source_date", {"source_date": "2025-01-01"}, {"source_date": "2026-01-01"}, True),
    ("falsification", {}, {"falsification": "Reject nonpositive net auction drift"}, True),
    ("horizon", {}, {"horizon": Horizon.WEEKLY}, True),
    ("required_data", {}, {"required_data": [DataCapability.FUNDAMENTALS]}, True),
    ("required_data", {"required_data": [DataCapability.OHLCV, DataCapability.FUNDAMENTALS]},
     {"required_data": [DataCapability.FUNDAMENTALS, DataCapability.OHLCV]}, False),
    ("falsification", {}, {"falsification": "FIXTURE only!!!"}, False),
    ("source_ref", {}, {"source_ref": "  "}, False),
    ("source_note", {}, {"source_note": "banana"}, False),
])
def test_declared_changes_are_checked_against_persisted_idea_fields(history_db, field,
                                                                 old_fields, new_fields, eligible):
    old = add_idea(history_db, "opening imbalance persistence", family="a", **old_fields)
    attempt(history_db, old, AttemptOutcome.HOLDOUT_NEGATIVE)
    candidate = add_idea(history_db, old.title, family="a", duplicate_of_idea_id=old.id,
                         override_reason=f"changed_fields={field}; ideas:1 idea_attempts:1; "
                                         "Measure archived auction-only next-session drift",
                         **new_fields)
    sc = campaign_scorecard(history_db)
    assert (candidate.id not in campaign_exclusions(sc)) is eligible
    assert bool(campaign_menu(sc, budget=1, novelty_min=0)) is eligible


def test_newer_negative_log_invalidates_preexisting_justification(history_db):
    old = add_idea(history_db, "opening imbalance persistence", family="a")
    record_negative_result(history_db, kind="gate_fail", verdict="FAIL", actor="system",
        reason="SYNTHETIC_FIXTURE prior non-PIT", source="manual", hypothesis=old.title,
        created_at="2025-12-31T00:00:00+00:00")
    candidate = add_idea(history_db, old.title, family="a", duplicate_of_idea_id=old.id,
                         source_ref="SYNTHETIC_FIXTURE-auction-v2",
                         override_reason="changed_fields=source_ref; ideas:1 negative_results:1 "
                                         "negative_results:2; archived auction inputs")
    record_negative_result(history_db, kind="gate_fail", verdict="FAIL", actor="system",
        reason="SYNTHETIC_FIXTURE newer data rejection", source="manual", hypothesis=old.title,
        created_at="2026-01-02T00:00:00+00:00")
    sc = campaign_scorecard(history_db)
    exclusion = campaign_exclusions(sc)[candidate.id]
    assert "predates" in exclusion["reason"]
    assert set(exclusion["prior_evidence_ids"]) == {
        "ideas:1", "ideas:2", "negative_results:1", "negative_results:2"}
    assert campaign_menu(sc, budget=2) == ()


@pytest.mark.parametrize("stamp", [None, "invalid", "2025-01-01T00:00:00", "equal"])
def test_duplicate_freshness_fails_closed_on_unverifiable_or_equal_outcome_time(history_db, stamp):
    old = add_idea(history_db, "opening imbalance persistence", family="a")
    attempt(history_db, old, AttemptOutcome.HOLDOUT_NEGATIVE)
    candidate = add_idea(history_db, old.title, family="a", duplicate_of_idea_id=old.id,
                         source_ref="SYNTHETIC_FIXTURE-auction-v2",
                         override_reason="changed_fields=source_ref; ideas:1 idea_attempts:1; "
                                         "archived auction timestamps")
    sc = campaign_scorecard(history_db)
    assert campaign_menu(sc, budget=1, novelty_min=0)[0].hypothesis_id == candidate.id
    sc["attempts"][0]["outcome_at"] = candidate.created_at if stamp == "equal" else stamp
    assert campaign_menu(sc, budget=1, novelty_min=0) == ()
    assert candidate.id in campaign_exclusions(sc)


def test_unfinished_duplicate_cannot_be_restarted_even_with_explanation(history_db):
    old = add_idea(history_db, "opening imbalance persistence", family="a")
    attempt(history_db, old)
    duplicate = add_idea(history_db, old.title, family="a", duplicate_of_idea_id=old.id,
                         override_reason="Changed sampling to auction-only timestamps")
    sc = campaign_scorecard(history_db)
    assert campaign_menu(sc, budget=2) == ()
    exclusion = campaign_exclusions(sc)[duplicate.id]
    assert "unfinished" in exclusion["reason"]
    assert set(exclusion["prior_evidence_ids"]) == {"ideas:1", "ideas:2", "idea_attempts:1"}


def test_attempted_and_duplicate_exclusions_include_every_blocking_attempt(history_db):
    old = add_idea(history_db, "opening imbalance persistence", family="a")
    attempt(history_db, old, AttemptOutcome.RUN_ERROR)
    attempt(history_db, old, AttemptOutcome.HOLDOUT_NEGATIVE)
    duplicate = add_idea(history_db, old.title, family="a")
    exclusions = campaign_exclusions(campaign_scorecard(history_db))
    assert "attempted" in exclusions[old.id]["reason"]
    assert set(exclusions[old.id]["prior_evidence_ids"]) == {
        "ideas:1", "idea_attempts:1", "idea_attempts:2"}
    assert "duplicate" in exclusions[duplicate.id]["reason"]
    assert set(exclusions[duplicate.id]["prior_evidence_ids"]) == {
        "ideas:1", "ideas:2", "idea_attempts:1", "idea_attempts:2"}


def test_negative_log_exclusion_carries_the_exact_log_id(history_db):
    record_negative_result(history_db, kind="gate_fail", verdict="FAIL", actor="system",
        reason="SYNTHETIC_FIXTURE non-PIT", source="manual",
        hypothesis="opening imbalance persistence", created_at="2025-12-31T00:00:00+00:00")
    duplicate = add_idea(history_db, "opening imbalance persistence", family="a")
    (exclusion,) = campaign_exclusions(campaign_scorecard(history_db)).values()
    assert "duplicate" in exclusion["reason"]
    assert set(exclusion["prior_evidence_ids"]) == {f"ideas:{duplicate.id}", "negative_results:1"}


def test_novelty_reserve_and_ceiling_do_not_spend_on_familiar_work(history_db):
    conn = history_db
    old = add_idea(conn, "opening imbalance persistence", family="a")
    attempt(conn, old, AttemptOutcome.CANDIDATE_PREVIEW_PASS)
    known = add_idea(conn, "weekly dividend seasonality", family="a")
    sc = campaign_scorecard(conn)
    assert campaign_menu(sc, budget=1) == ()  # reserve stays unused when no novel direction exists
    novel = add_idea(conn, "analyst dispersion reversal", family="b")
    more = add_idea(conn, "overnight earnings surprise", family="c")
    sc = campaign_scorecard(conn)
    menu = campaign_menu(sc, budget=3, novelty_min=1, novelty_max=1)
    assert [c.hypothesis_id for c in menu] == [novel.id, known.id]
    assert more.id not in {c.hypothesis_id for c in menu}
    assert menu[0].reason.startswith("novelty reserve")
    assert sum(c.budget for c in menu) == 2


def test_empty_history_zero_budget_and_determinism(history_db):
    conn = history_db
    assert campaign_menu(campaign_scorecard(conn), budget=3) == ()
    a = add_idea(conn, "weekly dividend seasonality", family="a")
    add_idea(conn, "overnight earnings surprise", family="b")
    sc = campaign_scorecard(conn)
    original = deepcopy(sc)
    assert campaign_menu(sc, budget=0) == ()
    expected = campaign_menu(sc, budget=1)
    assert expected[0].hypothesis_id == a.id
    assert campaign_menu(sc, budget=1) == expected
    sc["hypotheses"].reverse()
    assert campaign_menu(sc, budget=1) == expected
    sc["hypotheses"].reverse()
    assert sc == original


@pytest.mark.parametrize("kwargs", [
    {"budget": -1}, {"budget": True}, {"budget": 1.5},
    {"budget": 2, "novelty_min": -1}, {"budget": 2, "novelty_max": 0},
    {"budget": 2, "novelty_min": 2, "novelty_max": 1},
])
def test_invalid_resource_bounds_refuse(history_db, kwargs):
    with pytest.raises(ValueError):
        campaign_menu(campaign_scorecard(history_db), **kwargs)


def test_negative_log_is_context_and_dedup_sentinel_never_negative_alpha(history_db):
    conn = history_db
    record_id = record_negative_result(conn, kind="gate_fail", verdict="FAIL", actor="system",
        reason="SYNTHETIC_FIXTURE: missing point-in-time data", source="auto:research_promote",
        hypothesis="opening imbalance persistence", created_at="2025-12-31T00:00:00+00:00")
    duplicate = add_idea(conn, "opening imbalance persistence", family="a")
    changed = add_idea(conn, duplicate.title, family="a", duplicate_of_idea_id=duplicate.id,
                       source_ref="SYNTHETIC_FIXTURE-archived-PIT-v2",
                       override_reason=f"changed_fields=source_ref; ideas:{duplicate.id} "
                                       f"negative_results:{record_id}; archived PIT inputs")
    other = add_idea(conn, "weekly dividend seasonality", family="a")
    sc = campaign_scorecard(conn)
    menu = campaign_menu(sc, budget=3)
    assert {c.hypothesis_id for c in menu} == {changed.id, other.id}
    assert duplicate.id in campaign_exclusions(sc)
    choice = next(c for c in menu if c.hypothesis_id == changed.id)
    assert f"negative_results:{record_id}" in choice.prior_evidence_ids
    assert "economic_rejected=0/0" in choice.reason
    assert sc["totals"]["attempted"] == 0  # log row is not an additional trial


@pytest.mark.parametrize(("anchors", "existing_ten"), [
    ("negative_results:10", False),
    ("negative_results:10", True),
    ("negative_results:1 negative_results:999", False),
    ("negative_results:1suffix", False),
    ("negative_results:01", False),
    ("negative_results:1 idea_attempts:999", False),
    ("negative_results:1 ideas:999", False),
])
def test_duplicate_evidence_ids_must_resolve_exactly_and_causally(history_db, anchors,
                                                               existing_ten):
    old = add_idea(history_db, "opening imbalance persistence", family="a")
    record_negative_result(history_db, kind="gate_fail", verdict="FAIL", actor="system",
        reason="SYNTHETIC_FIXTURE non-PIT", source="manual", hypothesis=old.title,
        created_at="2025-12-31T00:00:00+00:00")
    if existing_ten:
        for _ in range(9):
            record_negative_result(history_db, kind="dead_end", verdict="UNTESTED", actor="system",
                reason="SYNTHETIC_FIXTURE unrelated", source="manual",
                hypothesis="weekly dividend seasonality", created_at="2025-12-31T00:00:00+00:00")
    candidate = add_idea(history_db, old.title, family="a", duplicate_of_idea_id=old.id,
                         source_ref="SYNTHETIC_FIXTURE-archived-PIT-v2",
                         override_reason=f"changed_fields=source_ref; ideas:1 {anchors}; "
                                         "archived PIT inputs")
    sc = campaign_scorecard(history_db)
    assert candidate.id in campaign_exclusions(sc)
    assert all(c.hypothesis_id != candidate.id for c in campaign_menu(sc, budget=3))


def test_ancestry_alone_cannot_replace_the_exact_blocking_attempt_anchor(history_db):
    old = add_idea(history_db, "opening imbalance persistence", family="a")
    attempt(history_db, old, AttemptOutcome.HOLDOUT_NEGATIVE)
    candidate = add_idea(history_db, old.title, family="a", duplicate_of_idea_id=old.id,
                         source_ref="SYNTHETIC_FIXTURE-archived-PIT-v2",
                         override_reason="changed_fields=source_ref; ideas:1 idea_attempts:10; "
                                         "archived PIT inputs")
    sc = campaign_scorecard(history_db)
    assert candidate.id in campaign_exclusions(sc)


def test_history_priority_uses_rejected_yield_not_just_rejection_count(history_db):
    conn = history_db
    for family, outcomes in [
        ("a", [AttemptOutcome.HOLDOUT_NEGATIVE, AttemptOutcome.CANDIDATE_PREVIEW_PASS,
               AttemptOutcome.CANDIDATE_PREVIEW_PASS]),
        ("b", [AttemptOutcome.HOLDOUT_NEGATIVE, AttemptOutcome.CANDIDATE_PREVIEW_PASS]),
    ]:
        for index, outcome in enumerate(outcomes):
            old = add_idea(conn, f"historical axis {index}", family=family)
            attempt(conn, old, outcome)
    a = add_idea(conn, "weekly dividend seasonality", family="a")
    add_idea(conn, "overnight earnings surprise", family="b")
    (choice,) = campaign_menu(campaign_scorecard(conn), budget=1, novelty_min=0)
    assert choice.hypothesis_id == a.id
    assert "economic_rejected=1/3" in choice.reason
    assert {"idea_attempts:1", "idea_attempts:2", "idea_attempts:3"} <= set(
        choice.prior_evidence_ids)
    sc = campaign_scorecard(conn)
    expected = campaign_menu(sc, budget=3)
    sc["hypotheses"].reverse()
    sc["attempts"].reverse()
    sc["negative_results"].reverse()
    assert campaign_menu(sc, budget=3) == expected


def test_existing_retry_ledger_keeps_each_non_alpha_attempt_in_denominator(history_db):
    conn = history_db
    old = add_idea(conn, "opening imbalance persistence", family="a")
    attempt(conn, old, AttemptOutcome.RUN_ERROR)
    attempt(conn, old, AttemptOutcome.RUN_ERROR)
    candidate = add_idea(conn, "weekly dividend seasonality", family="a")
    sc = campaign_scorecard(conn)
    assert sc["totals"]["attempted"] == 2
    assert sc["totals"]["run_error"] == 2
    assert sc["totals"]["economic_evaluated"] == 0
    (choice,) = campaign_menu(sc, budget=1, novelty_min=0)
    assert choice.hypothesis_id == candidate.id
    assert {"idea_attempts:1", "idea_attempts:2"} <= set(choice.prior_evidence_ids)
