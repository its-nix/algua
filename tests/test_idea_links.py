"""Journey labels for an owner Inbox item (spec 2026-11-14 §7.3) — pure mapping."""
import pytest

from algua.registry.idea_links import journey


def _idea(outcome="", reason="", status="open", dup=""):
    return {"id": "5", "status": status, "duplicate_of": dup, "latest_outcome": outcome,
            "latest_reason": reason}


def _taken(idea):
    return journey({"status": "taken", "inspiration_id": "n"}, {"n": [idea]})


def test_queued_and_bare_inspiration():
    assert journey({"status": "queued"}, {}) == [
        {"label": "Queued for the next leap", "tone": "pending"}]
    assert journey({"status": "taken", "inspiration_id": "n"}, {}) == [
        {"label": "Inspiration", "tone": "neutral"}]


@pytest.mark.parametrize(("idea", "last"), [
    (_idea(), {"label": "Idea #5", "tone": "pending"}),
    (_idea("promoted_candidate"), {"label": "Candidate", "tone": "progressed"}),
    (_idea("candidate_preview_pass"), {"label": "Backtested", "tone": "neutral"}),
    (_idea("holdout_negative", "sharpe < 0"), {"label": "Refuted: sharpe < 0", "tone": "refuted"}),
    (_idea(status="refuted"), {"label": "Refuted: refuted", "tone": "refuted"}),
    (_idea(dup="3"), {"label": "Duplicate of idea #3", "tone": "neutral"}),
    (_idea("promoted_candidate", dup="3"), {"label": "Candidate", "tone": "progressed"}),
    (_idea("run_error"), {"label": "Outcome: run_error", "tone": "neutral"}),
    (_idea(status="discarded"), {"label": "Discarded", "tone": "neutral"}),
])
def test_outcome_mapping_and_only_last_is_toned(idea, last):
    steps = _taken(idea)
    assert steps[-1] == last
    assert all(s["tone"] == "neutral" for s in steps[:-1])
