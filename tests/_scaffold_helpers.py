"""Shared test SETUP helpers for reaching the two gated lifecycle stages without running a gate.

``backtested -> candidate`` and ``paper -> forward_tested`` are taken only by ``research promote``
and ``paper promote`` (each consumes a gate token). There is no human exemption any more
(spec 2026-11-13): ``registry transition`` refuses both edges for every actor (#682), and the
``transitions`` service demands the token for every actor. Fixtures that merely NEED a strategy at
one of those stages write the transition through the repository primitive instead, recording what
the removed human branch used to record.
"""
from __future__ import annotations


def scaffold_repo_transition(repo, name: str, to, reason: str = "test scaffold") -> None:
    """TEST SETUP ONLY: move ``name`` to ``to`` on ``repo`` with no gate. ``-> candidate`` pins no
    identity; ``-> forward_tested`` refuses a frozen deployment first and pins the recomputed
    checkout identity (exactly what the old human raw transition recorded)."""
    from algua.contracts.lifecycle import Actor, Stage, validate_transition
    from algua.registry.approvals import compute_artifact_hashes
    from algua.registry.transitions import refuse_frozen_deployment

    target = Stage(to)
    rec = repo.get(name)
    validate_transition(rec.stage, target)
    hashes: dict = {}
    if rec.stage is Stage.PAPER and target is Stage.FORWARD_TESTED:
        refuse_frozen_deployment(repo, rec.id, target)
        identity = compute_artifact_hashes(name)
        hashes = {"code_hash": identity.code_hash, "config_hash": identity.config_hash,
                  "dependency_hash": identity.dependency_hash}
    repo.apply_transition(rec=rec, to=target, actor=Actor.HUMAN, reason=reason, **hashes)


def scaffold_transition(name: str, to: str, reason: str = "test scaffold") -> None:
    """TEST SETUP ONLY: :func:`scaffold_repo_transition` against the configured registry DB."""
    from algua.registry.db import registry_conn
    from algua.registry.store import SqliteStrategyRepository

    with registry_conn() as conn:
        scaffold_repo_transition(SqliteStrategyRepository(conn), name, to, reason)
