from datetime import UTC, datetime, timedelta

import pytest

from algua.operator.research_daily_budget import DailyResearchBudget
from algua.registry.db import connect, migrate

NOW = datetime(2026, 11, 10, 22, tzinfo=UTC)


def budget(tmp_path, limit=4):
    db = tmp_path / 'registry.db'
    conn = connect(db)
    migrate(conn)
    conn.close()
    return DailyResearchBudget(tmp_path, db, limit)


def test_budget_is_durable_idempotent_and_rolls_at_utc_midnight(tmp_path):
    b = budget(tmp_path)
    for i in range(4):
        assert b.reserve(f'cycle-{i}', now=NOW)
    assert b.remaining(now=NOW) == 0
    assert not b.reserve('cycle-0', now=NOW)  # No second model launch under the same identity.
    assert not budget(tmp_path).reserve('fifth', now=NOW)
    assert b.reserve('tomorrow', now=NOW + timedelta(hours=2))
    assert b.remaining(now=NOW + timedelta(hours=2)) == 3


def test_corrupt_budget_fails_closed_even_after_day_rollover(tmp_path):
    b = budget(tmp_path)
    b.reserve('one', now=NOW)
    (tmp_path / 'research-budget.json').write_text('broken')
    with pytest.raises(ValueError, match='budget'):
        b.reserve('another', now=NOW + timedelta(days=1))


def test_existing_chooser_launches_count_before_budget_adoption(tmp_path):
    b = budget(tmp_path, limit=1)
    path = tmp_path / 'research-cycles/20261110-070000-old.choice'
    path.mkdir(parents=True)
    (path / 'menu.json').write_text('{}')
    assert b.remaining(now=NOW) == 0
    assert not b.reserve('new', now=NOW)


def test_reserved_chooser_directory_and_claim_count_as_one_cycle(tmp_path):
    from algua.registry.idea_attempts import IdeaAttemptsRepository
    from tests.campaign_fixtures import add_idea

    b = budget(tmp_path)
    cycle = datetime.now(UTC).strftime('%Y%m%d') + '-one-cycle'
    assert b.reserve(cycle)
    conn = connect(b.database)
    add_idea(conn, 'one cycle', family='fixture')
    IdeaAttemptsRepository(conn).claim(run_stamp=cycle, limit=1, ttl_minutes=180)
    conn.close()
    directory = tmp_path / f'research-cycles/{cycle}.choice'
    directory.mkdir(parents=True)
    (directory / 'menu.json').write_text('{}')
    assert b.remaining() == 3


def test_concurrent_admissions_cannot_overspend(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    b = budget(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as workers:
        admitted = list(workers.map(lambda i: b.reserve(f'parallel-{i}', now=NOW), range(8)))
    assert sum(admitted) == 4
    assert b.remaining(now=NOW) == 0


def test_naive_clock_and_future_budget_day_fail_closed(tmp_path):
    b = budget(tmp_path)
    with pytest.raises(ValueError, match='timezone-aware'):
        b.remaining(now=NOW.replace(tzinfo=None))
    assert b.reserve('one', now=NOW)
    with pytest.raises(ValueError, match='backwards'):
        b.remaining(now=NOW - timedelta(days=1))


def test_ready_is_idle_then_eligible_then_budget_exhausted_without_claims(tmp_path, monkeypatch):
    import json

    from typer.testing import CliRunner

    from algua.cli.main import app
    from tests.campaign_fixtures import add_idea

    b = budget(tmp_path, limit=1)
    monkeypatch.setenv('ALGUA_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('ALGUA_DB_PATH', str(b.database))
    monkeypatch.setenv('ALGUA_RESEARCH_DAILY_CYCLE_LIMIT', '1')
    runner = CliRunner()
    idle = runner.invoke(app, ['research', 'ready'])
    assert idle.exit_code == 1
    assert json.loads(idle.stdout)['reason'] == 'no_eligible_ideas'
    conn = connect(b.database)
    add_idea(conn, 'runnable daily recipe', family='fixture')
    conn.close()
    eligible = runner.invoke(app, ['research', 'ready'])
    assert eligible.exit_code == 0, eligible.stdout
    assert json.loads(eligible.stdout)['remaining_daily_cycles'] == 1
    assert b.reserve('only-launch')
    exhausted = runner.invoke(app, ['research', 'ready'])
    assert exhausted.exit_code == 1
    assert json.loads(exhausted.stdout)['reason'] == 'daily_budget_exhausted'
    conn = connect(b.database)
    assert conn.execute('SELECT COUNT(*) FROM idea_attempts').fetchone()[0] == 0
    conn.close()
