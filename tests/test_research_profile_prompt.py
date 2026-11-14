"""Configured profile is bound to admission, per-task goals and proxy-only finalization."""
from __future__ import annotations

import json

import pytest

from algua.operator.research_memory_checkpoint import canonical
from algua.operator.research_profile_prompt import (
    admitted_profile,
    profile_claims,
    render_profile_goal,
    validate_proxy_report,
)
from tests.test_research_profile import configured as configured
from tests.test_research_profile import profile


def test_profile_follows_exact_campaign_admission(configured):
    store, _, _, _ = configured
    receipt = profile.load_research_profile(store.data_dir)
    response = {"ok": True, "phase": "running", "research_cycle_id": "fixture",
        "campaign": {"menu": {"request": {"research_cycle_id": "fixture",
            "database": "/fixture.db", "context": {"research_profile": receipt}}}},
        "claimed": [{"id": 1, "claim_token": "never-forward"}]}
    assert admitted_profile(canonical(response), expected=receipt, cycle_id="fixture",
                            database="/fixture.db") == receipt
    response["campaign"]["menu"]["request"]["context"]["research_profile"] = {
        **receipt, "start": "2025-01-01"}
    with pytest.raises(ValueError, match="research_profile:admission"):
        admitted_profile(canonical(response), expected=receipt, cycle_id="fixture",
                         database="/fixture.db")


def test_primary_and_each_claim_carry_full_exact_profile_without_tokens(configured):
    store, _, _, _ = configured
    receipt = profile.load_research_profile(store.data_dir)
    claims = profile_claims([{"id": 1, "hypothesis": "original", "claim_token": "secret"}], receipt)
    assert claims[0]["hypothesis"] == "original" and "claim_token" not in claims[0]
    assert claims[0]["evaluation_profile"] == receipt
    result = render_profile_goal("original goal", receipt)
    assert result.startswith("original goal") and canonical(receipt).decode() in result
    for required in ("author", "interpret", "run_error", "--snapshot", "--start", "--end",
                     "integrity_fail", "preview_gate: null", "no merge_back"):
        assert required in result
    assert "secret" not in result


@pytest.mark.parametrize("change", [{"outcome": "candidate_preview_pass"},
    {"merge_back": {"strategy": "forged"}}, {"outcome": "holdout_negative"}])
def test_proxy_report_cannot_publish_candidate_or_relabel_qualification(tmp_path, change):
    path = tmp_path / "report.md"
    row = {"title": "fixture", "idea_id": 1, "outcome": "integrity_fail", "reason": "non-PIT"}
    path.write_text("```json\n" + json.dumps({"hypotheses": [row | change]}) + "\n```\n")
    with pytest.raises(ValueError, match="research_profile:report"):
        validate_proxy_report(path)
    path.write_text("```json\n" + json.dumps({"hypotheses": [row]}) + "\n```\n")
    validate_proxy_report(path)
