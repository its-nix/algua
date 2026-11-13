"""Tests: `research promote` accepts --fundamentals/--news-snapshot and the PIT funnel is
unblocked end-to-end to candidate for BOTH lanes (Task 6, #132)."""
from __future__ import annotations

import sqlite3

from typer.testing import CliRunner

from algua.cli.main import app
from tests._human_actor_helpers import promote_signed

runner = CliRunner()

# --- #329 authenticated --actor human plumbing ---------------------------------------------------
_HUMAN_KEY = None
_TMP_PATH = None


def _promote(args):
    """Drop-in for `runner.invoke(app, args)` at gated promote call sites: when `args` requests
    `--actor human`, run the signed challenge dance; otherwise a plain invoke."""
    if "human" in args:
        return promote_signed(runner, app, args, _HUMAN_KEY, _TMP_PATH)
    return runner.invoke(app, args)


def _burned_holdout_rows(tmp_path):
    conn = sqlite3.connect(tmp_path / "r.db")
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM holdout_evaluations WHERE committed_at IS NOT NULL"
        ).fetchone()[0]
    finally:
        conn.close()
