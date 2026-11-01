"""The existing KB experience surface consolidates campaign history by family."""
from algua.contracts.idea import AttemptOutcome
from algua.knowledge import experience
from algua.registry.db import connect, migrate
from algua.registry.idea_scorecard import campaign_scorecard
from tests.campaign_fixtures import add_idea, attempt


def test_campaign_family_note_retains_evidence_and_non_alpha_denominators(tmp_path):
    conn = connect(tmp_path / "r.db")
    try:
        migrate(conn)
        old = add_idea(conn, "opening imbalance persistence", family="a")
        attempt(conn, old, AttemptOutcome.RUN_ERROR, reason="SYNTHETIC_FIXTURE unavailable inputs")
        render = getattr(experience, "render_campaign_experience", None)
        assert callable(render), "Campaign history needs a consolidated existing-KB experience view"
        note = render(campaign_scorecard(conn))
        assert "family:a" in note
        assert "idea_attempts:1" in note
        assert "unavailable inputs" in note
        assert '"run_error": 1' in note
        assert '"economic_rejected": 0' in note
        assert "not independent statistical trials" in note
    finally:
        conn.close()
