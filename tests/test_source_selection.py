from types import SimpleNamespace

import pytest

from algua.config.settings import Settings
from algua.operator.source_recipe import assess_recipe
from algua.operator.source_selection import record_source_pass, review_sources, source_plan
from tests.test_research_profile import configured as configured

PROFILE = {
    "coverage": {"grid_sessions": 505},
    "windows": 4,
    "holdout_frac": 0.2,
    "execution": {"decision_lag_bars": 1},
}


def recipe(lookback=21, construction="top_k_equal_weight"):
    leg = dict(
        market="us_equities",
        horizon="daily",
        required_data=["ohlcv"],
        construction=construction,
        feature_lookback=lookback,
    )
    return {**leg, "controls": [dict(leg, construction="equal_weight_positive")]}


def note(settings, name, declared=None):
    from algua.knowledge.frontmatter import render_doc

    folder = settings.knowledge_dir / "inspirations"
    folder.mkdir(parents=True, exist_ok=True)
    metadata = dict(id=f"2026-11-12-{name}", status="fresh", market="us_equities", horizon="daily")
    if declared is not None:
        metadata["pilot_recipe"] = declared
    (folder / f"{metadata['id']}.md").write_text(render_doc(metadata, "source body"))
    return metadata["id"]


def test_rank_fit_before_unknown_and_backlog_unsupported_controls(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", knowledge_dir=tmp_path / "kb")
    blocked = note(settings, "blocked", recipe(253))
    unknown = note(settings, "unknown")
    fit = note(settings, "fit", recipe())
    plan = source_plan(settings, PROFILE, code="v1")
    assert [s["source_id"] for s in plan["sources"]] == [fit, unknown]
    assert plan["backlog"][0]["source_id"] == blocked
    r = recipe()
    r["controls"][0]["required_data"] = ["historical_market_cap"]
    assert assess_recipe(r, PROFILE)["status"] == "blocked"


def test_blockers_per_source_do_not_freeze_other_or_new_notes(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", knowledge_dir=tmp_path / "kb")
    a = note(settings, "aaa")
    b = note(settings, "bbb")
    plan = source_plan(settings, PROFILE, code="v1", limit=1)
    result = review_sources(
        plan, [{"source_id": a, "recipe": recipe(253), "reason": "history too short"}], new_ideas=[]
    )
    record_source_pass(settings.data_dir, result, clean=True, imported_sources=set())
    assert source_plan(settings, PROFILE, code="v1")["sources"][0]["source_id"] == b
    c = note(settings, "ccc")
    fresh = source_plan(settings, PROFILE, code="v1")
    assert a not in [s["source_id"] for s in fresh["sources"]]
    assert c in [s["source_id"] for s in fresh["sources"]]
    assert a in [s["source_id"] for s in source_plan(settings, PROFILE, code="v2")["sources"]]


def test_review_requires_offered_feasible_source_and_keeps_missing_explicit(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", knowledge_dir=tmp_path / "kb")
    a = note(settings, "aaa")
    note(settings, "bbb")
    plan = source_plan(settings, PROFILE, code="v1")
    idea = SimpleNamespace(
        inspirations=[SimpleNamespace(inspiration_id=a)],
        market="us_equities",
        horizon="daily",
        required_data=["ohlcv"],
    )
    row = {
        "source_id": a,
        "recipe": recipe(),
        "reason": "declared daily extension with explicit assumptions",
    }
    result = review_sources(plan, [row], new_ideas=[idea])
    assert result["complete"] is False and len(result["missing_sources"]) == 1
    with pytest.raises(ValueError):
        review_sources(plan, [], new_ideas=[idea])
    row["recipe"] = recipe(253)
    with pytest.raises(ValueError):
        review_sources(plan, [row], new_ideas=[idea])


def test_actual_cli_review_and_existing_import_reach_research_queue(tmp_path, monkeypatch):
    import json

    from typer.testing import CliRunner

    from algua.cli.main import app
    from algua.contracts.idea import Obscurity
    from algua.registry.db import connect, migrate
    from algua.registry.ideas import IdeaRepository, InspirationLink
    from tests.campaign_fixtures import add_idea

    settings = Settings(data_dir=tmp_path / "data", knowledge_dir=tmp_path / "kb")
    a = note(settings, "aaa", recipe())
    # A complete accepted note supplies the trusted venue resolver on import.
    path = settings.knowledge_dir / "inspirations" / f"{a}.md"
    path.write_text(
        path.read_text().replace(
            "status: fresh", "venue: paper/fixture\nobscurity: niche\nstatus: fresh"
        )
    )
    monkeypatch.setenv("ALGUA_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("ALGUA_KNOWLEDGE_DIR", str(settings.knowledge_dir))
    authority = tmp_path / "authority.db"
    scratch = tmp_path / "scratch.db"
    monkeypatch.setenv("ALGUA_DB_PATH", str(authority))
    for file in (authority, scratch):
        conn = connect(file)
        migrate(conn)
        conn.close()
    conn = connect(scratch)
    add_idea(
        conn,
        "SYNTHETIC_FIXTURE source handoff",
        category="momentum",
        inspirations=[InspirationLink(a, "paper/fixture", Obscurity.NICHE)],
    )
    conn.close()
    plan = source_plan(settings, PROFILE, code="v1")
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan))
    reviews = tmp_path / "reviews.json"
    reviews.write_text(
        json.dumps([{"source_id": a, "recipe": recipe(), "reason": "fixture-supported recipe"}])
    )
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "research",
            "sources",
            "review",
            "--plan",
            str(plan_file),
            "--reviews",
            str(reviews),
            "--scratch-db",
            str(scratch),
            "--seeded-max-id",
            "0",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["complete"] is True
    result = runner.invoke(
        app,
        [
            "research",
            "idea",
            "import",
            "--from",
            str(scratch),
            "--run",
            "fixture-source",
            "--max",
            "1",
            "--seeded-max-id",
            "0",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert len(json.loads(result.stdout)["imported"]) == 1
    conn = connect(authority)
    assert len(IdeaRepository(conn).list()) == 1
    assert conn.execute("SELECT count(*) FROM idea_attempts").fetchone()[0] == 0
    conn.close()
    result = runner.invoke(app, ["research", "campaign-menu", "--budget", "1"])
    assert result.exit_code == 0, result.stdout
    assert len(json.loads(result.stdout)["choices"]) == 1


def test_only_reviewed_sources_consume_retries_and_real_changes_reopen(tmp_path):
    from algua.knowledge.inspirations import mark_used

    settings = Settings(data_dir=tmp_path / "data", knowledge_dir=tmp_path / "kb")
    a = note(settings, "aaa")
    b = note(settings, "bbb")
    plan = source_plan(settings, PROFILE, code="v1")
    result = review_sources(
        plan, [{"source_id": a, "recipe": None, "reason": "unspecified signal"}], new_ideas=[]
    )
    record_source_pass(settings.data_dir, result, clean=False, imported_sources=set())
    assert not (settings.data_dir / "leap-sources.json").exists()
    for _ in range(2):
        record_source_pass(settings.data_dir, result, clean=True, imported_sources=set())
    mark_used(settings, a, idea_id=1)
    assert [s["source_id"] for s in source_plan(settings, PROFILE, code="v1")["sources"]] == [b]
    path = settings.knowledge_dir / "inspirations" / f"{a}.md"
    path.write_text(path.read_text() + "\nSubstantive new source details.\n")
    assert a in [s["source_id"] for s in source_plan(settings, PROFILE, code="v1")["sources"]]


@pytest.mark.parametrize(
    "body,worker,import_exit",
    [
        ("", 0, 0),
        ("[]", 0, 0),
        ('{"ok":true,"imported":null}', 0, 0),
        ('{"ok":true,"imported":[],"critic_errors":1}', 0, 0),
        ('{"ok":true,"imported":[]}', 1, 0),
        ('{"ok":false,"imported":[]}', 0, 1),
    ],
)
def test_cli_failed_finalization_does_not_spend_source_retry(
    tmp_path, monkeypatch, body, worker, import_exit
):
    import json

    from typer.testing import CliRunner

    from algua.cli.main import app

    settings = Settings(data_dir=tmp_path / "data", knowledge_dir=tmp_path / "kb")
    a = note(settings, "aaa")
    result = review_sources(
        source_plan(settings, PROFILE, code="v1"),
        [{"source_id": a, "recipe": None, "reason": "unspecified"}],
        new_ideas=[],
    )
    receipt = tmp_path / "result.json"
    receipt.write_text(json.dumps(result))
    imported = tmp_path / "import.json"
    imported.write_text(body)
    monkeypatch.setenv("ALGUA_DATA_DIR", str(settings.data_dir))
    output = CliRunner().invoke(
        app,
        [
            "research",
            "sources",
            "record",
            "--result",
            str(receipt),
            "--import-result",
            str(imported),
            "--worker-exit",
            str(worker),
            "--import-exit",
            str(import_exit),
        ],
    )
    assert output.exit_code == 0, output.stdout
    assert json.loads(output.stdout)["recorded"] is False
    assert not (settings.data_dir / "leap-sources.json").exists()


def test_cli_preflight_checks_common_control_history_without_running_code(tmp_path):
    import json

    from typer.testing import CliRunner

    from algua.cli.main import app

    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps(PROFILE))
    declared = recipe()
    declared["controls"][0]["feature_lookback"] = 253
    file = tmp_path / "recipe.json"
    file.write_text(json.dumps(declared))
    runner = CliRunner()
    result = runner.invoke(
        app, ["research", "sources", "preflight", "--recipe", str(file), "--profile", str(profile)]
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout)["status"] == "blocked"
    file.write_text('{"missing":true}')
    result = runner.invoke(
        app, ["research", "sources", "preflight", "--recipe", str(file), "--profile", str(profile)]
    )
    assert result.exit_code == 1
    assert json.loads(result.stdout)["ok"] is False


def test_cli_plan_uses_verified_profile_and_refuses_drift(configured, tmp_path, monkeypatch):
    import json

    from typer.testing import CliRunner

    from algua.cli.main import app

    store, _, descriptor_path, descriptor = configured
    settings = Settings(data_dir=store.data_dir, knowledge_dir=tmp_path / "kb")
    a = note(settings, "aaa")
    monkeypatch.setenv("ALGUA_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("ALGUA_KNOWLEDGE_DIR", str(settings.knowledge_dir))
    runner = CliRunner()
    args = ["research", "sources", "plan", "--code", "fixture", "--limit", "3"]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.stdout
    plan = json.loads(result.stdout)
    assert [s["source_id"] for s in plan["sources"]] == [a]
    assert plan["profile"]["coverage"]["grid_sessions"] == 2
    assert plan["profile"]["qualification_eligible"] is False
    descriptor_path.write_text(json.dumps({**descriptor, "content_hash": "0" * 64}))
    result = runner.invoke(app, args)
    assert result.exit_code == 1
    assert json.loads(result.stdout)["ok"] is False
    assert not (settings.data_dir / "leap-sources.json").exists()


def test_critic_only_import_archives_rejections_without_any_idea_admission(tmp_path, monkeypatch):
    import json

    from typer.testing import CliRunner

    from algua.cli.main import app
    from algua.registry.db import connect, migrate
    from tests.campaign_fixtures import add_idea

    authority = tmp_path / "authority.db"
    scratch = tmp_path / "scratch.db"
    monkeypatch.setenv("ALGUA_DB_PATH", str(authority))
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path / "data"))
    for file in (authority, scratch):
        conn = connect(file)
        migrate(conn)
        if file == scratch:
            add_idea(conn, "must never be imported", category="momentum")
        conn.close()
    critic = tmp_path / "critic.jsonl"
    critic.write_text(
        json.dumps(
            {
                "title": "invalid source claim",
                "hypothesis": "future fill",
                "reason_kind": "lookahead_by_construction",
                "reason": "requires tomorrow close",
            }
        )
        + "\n"
    )
    result = CliRunner().invoke(
        app,
        [
            "research",
            "idea",
            "import",
            "--from",
            str(scratch),
            "--run",
            "fixture-critic-only",
            "--max",
            "3",
            "--seeded-max-id",
            "0",
            "--critic-file",
            str(critic),
            "--critic-only",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["imported"] == [] and payload["critic_rows"] == 1
    conn = connect(authority)
    assert conn.execute("SELECT count(*) FROM ideas").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM negative_results").fetchone()[0] == 1
    conn.close()


def test_unknown_recipes_prefer_daily_market_match_and_unused_notes(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", knowledge_dir=tmp_path / "kb")
    monthly = note(settings, "aaa-monthly")
    used = note(settings, "bbb-used")
    fresh = note(settings, "zzz-daily")
    folder = settings.knowledge_dir / "inspirations"
    path = folder / f"{monthly}.md"
    path.write_text(path.read_text().replace("horizon: daily", "horizon: monthly"))
    path = folder / f"{used}.md"
    path.write_text(path.read_text().replace("status: fresh", "status: used"))
    assert [s["source_id"] for s in source_plan(settings, PROFILE, code="v1")["sources"]] == [
        fresh,
        used,
        monthly,
    ]


def test_feasible_recipe_order_preserves_retry_priority_over_source_metadata(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", knowledge_dir=tmp_path / "kb")
    used = note(settings, "aaa-used", recipe())
    fresh = note(settings, "zzz-fresh", recipe())
    path = settings.knowledge_dir / "inspirations" / f"{used}.md"
    path.write_text(
        path.read_text()
        .replace("status: fresh", "status: used")
        .replace("horizon: daily", "horizon: monthly", 1)
    )
    assert [s["source_id"] for s in source_plan(settings, PROFILE, code="v1")["sources"]] == [
        used,
        fresh,
    ]
