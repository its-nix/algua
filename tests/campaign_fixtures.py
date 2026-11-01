"""Persist fixture ideas/outcomes through the existing repositories."""
from algua.contracts.idea import (
    DataCapability,
    Horizon,
    IdeaStatus,
    Market,
    SourceType,
)
from algua.registry.idea_attempts import IdeaAttemptsRepository
from algua.registry.ideas import IdeaRepository


def add_idea(conn, text, *, family=None, category=None, **kwargs):
    fields = dict(title=text, hypothesis=text, family=family, category=category or family or text,
        tags=["SYNTHETIC_FIXTURE"], source_type=SourceType.MANUAL,
        source_ref="SYNTHETIC_FIXTURE", source_date=None, source_note=None,
        required_data=[DataCapability.OHLCV], status=IdeaStatus.OPEN,
        market=Market.US_EQUITIES, horizon=Horizon.DAILY, falsification="fixture only")
    fields.update(kwargs)
    return IdeaRepository(conn).add(**fields)


def attempt(conn, idea, outcome=None, *, reason="SYNTHETIC_FIXTURE", evidence_ref=None):
    repo = IdeaAttemptsRepository(conn)
    (claimed,) = repo.claim(run_stamp="SYNTHETIC_FIXTURE", limit=1, ttl_minutes=180,
                            category=idea.category)
    assert claimed.id == idea.id
    if outcome is not None:
        repo.record_outcome(idea.id, token=claimed.claim_token, outcome=outcome,
                            reason=reason, evidence_ref=evidence_ref)
    return claimed
