"""Engineering model-pin retention fixtures; no inference or numerical experiment is run."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from dataclasses import asdict

import pytest

from algua.backtest.result import BacktestResult
from algua.cli.main import main
from algua.models import register
from algua.operator.campaign_memory import capture_public_memory
from algua.operator.campaign_memory_schema import model_refs
from algua.operator.research_cycle import CycleLimits, ResearchCycle
from algua.operator.research_memory import ResearchMemory
from algua.operator.research_memory_projection import _model_refs
from algua.operator.research_prompt_memory import decode_admitted_memory, render_research_goal
from algua.registry.db import connect
from algua.registry.run_views import run_detail_payload
from algua.registry.runs import record_backtest_run
from algua.registry.store import SqliteStrategyRepository
from algua.tracking.research_archive import LocalResearchArchive
from tests.campaign_fixtures import add_idea
from tests.test_cli_research_memory import cli_memory as cli_memory


def reference(*, width=64, cutoff="2020-01-01T00:00:00+00:00"):
    return {"name": "engineering-model-fixture", "version": 1, "digest": "a" * width,
            "training_as_of": cutoff, "provenance_digest": "b" * width}


@pytest.mark.parametrize("validator", ["producer", "consumer"])
@pytest.mark.parametrize("width,cutoff", [(16, "2020-01-01T00:00:00+00:00"),
    (64, "2020-01-01"), (64, "2020-01-01T12:34:56"),
    (64, "2020-W01-1T00:00:00+00:00")])
def test_width_and_time_admission_are_independently_compatible(validator, width, cutoff):
    refs = [reference(width=width, cutoff=cutoff)]
    original = copy.deepcopy(refs)
    if validator == "producer":
        assert _model_refs(refs, "backtest") == original
    else:
        model_refs(refs, "backtest")
    assert refs == original


@pytest.mark.parametrize("cutoff", ["2020-01-01", "2020-01-01T12:34:56"])
def test_real_registered_pin_retains_worker_and_survives_context_and_primary_prompt(
    cli_memory, monkeypatch, capsys, cutoff,
):
    authority, cycle, worker, source, tracking = cli_memory
    archive = LocalResearchArchive(f"sqlite:///{tracking}")
    memory = ResearchMemory(cycle, archive)
    memory.seed(worker)
    version = register("engineering-model-fixture", b"ENGINEERING_FIXTURE_NOT_A_TRAINED_MODEL",
        root=worker / "opaque-model-store", training_snapshot_id=None, training_as_of=cutoff,
        code_hash=None, hyperparameters={"opaque": "unchanged"}, seed=None,
        eval_report={"fixture": "no inference or numerical experiment"})
    ref = version.as_ref().as_dict()
    assert len(ref["digest"]) == len(ref["provenance_digest"]) == 16
    assert ref["training_as_of"] == cutoff
    result = BacktestResult(strategy="SYNTHETIC_FIXTURE model-pin-retention",
        metrics={"sharpe": -0.5, "sortino": -0.6, "total_return": -0.2,
            "max_drawdown": -0.1, "ann_volatility": 0.2, "cagr": -0.2, "calmar": -2.0},
        config_hash="engineering-fixture", data_source="synthetic_fixture_not_numerical",
        timeframe="1d", period={"start": "2024-01-02", "end": "2024-01-05"}, model_ref=ref)
    conn = connect(source)
    try:
        repo = SqliteStrategyRepository(conn)
        run_id = record_backtest_run(repo, result.strategy, result, params={"fixture": True})
        assert run_detail_payload(repo, run_id)["components"] == [ref]
    finally:
        conn.close()

    def forbidden(*args, **kwargs):
        raise AssertionError("memory resolved or loaded model bytes")

    import algua.models as models
    import algua.models.registry as model_registry

    for module in (models, model_registry):
        for name in ("get_version", "get_version_with_bytes", "load_artifact_bytes", "register"):
            monkeypatch.setattr(module, name, forbidden)
    receipt = memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    retained = memory.read()
    assert retained["evaluations"][0]["model_refs"] == [ref]
    assert retained["coverage"]["model_bytes_preserved"] is False
    assert retained["coverage"]["evaluated_worktree_verified"] is False
    assert retained["evidence_mode"] == "UNVERIFIED_WORKER" and retained["authority"] == "none"
    assert not memory.cleanup_allowed(worker)
    assert worker.exists()
    assert (
        (worker / "opaque-model-store/engineering-model-fixture/v1/artifact.bin").read_bytes()
        == b"ENGINEERING_FIXTURE_NOT_A_TRAINED_MODEL"
    )
    with pytest.raises(SystemExit) as stopped:
        main(["research", "memory", "show", "--run", cycle.cycle_id])
    shown = json.loads(capsys.readouterr().out)
    assert stopped.value.code == 0 and shown["evaluations"][0]["model_refs"] == [ref]

    report = cycle.directory / "engineering-fixture-report.md"
    report.write_text('```json\n{"hypotheses":[{"idea_id":1,"title":"fixture",'
        '"outcome":"sweep_unstable","reason":"ENGINEERING_FIXTURE_ONLY"}]}\n```')
    cycle.finish(phase="completed", worker_exit=0, report=report, evidence_ref=receipt["reference"])
    add_idea(authority, "SYNTHETIC_FIXTURE changed CLI retention hypothesis",
        family="cli-retention",
        duplicate_of_idea_id=1, source_ref="ENGINEERING_FIXTURE changed inputs",
        override_reason="changed_fields=source_ref; ideas:1 idea_attempts:1; "
                        "Archived timestamps replace the original sampling")
    add_idea(authority, "SYNTHETIC_FIXTURE unrelated calendar", family="calendar")
    following = ResearchCycle(authority, cycle.directory, "engineering-model-next")
    limits = CycleLimits(max_hypotheses=3)
    menu = following.campaign_menu(limits=limits, context={}, ttl_minutes=1440)
    snapshot = capture_public_memory(menu, cycle_directory=cycle.directory,
        tracking_uri=archive.tracking_uri, tracking_backend="mlflow-sqlite")
    assert snapshot["observations"][0]["model_refs"] == [ref]
    context = {"public_research_memory": snapshot}
    menu = following.campaign_menu(limits=limits, context=context, ttl_minutes=1440)
    campaign = {"menu": menu, "selection": {"menu_id": menu["menu_id"], "choices": [
        {**choice, "reason": "ENGINEERING_FIXTURE admission only"} for choice in menu["choices"]]}}
    claims, admission = following.start(limits=limits, context=context, ttl_minutes=1440,
                                       campaign=campaign)
    admission["claimed"] = [asdict(claim) for claim in claims]
    wrapper = decode_admitted_memory(json.dumps(admission).encode(),
        cycle_id=following.cycle_id, database=menu["request"]["database"])
    goal = render_research_goal("ENGINEERING_FIXTURE no model use asserted", wrapper)
    assert wrapper["snapshot"]["observations"][0]["model_refs"] == [ref]
    assert cutoff in goal and "cycle_only" in goal
    for table in ("search_trials", "gate_evaluations", "holdout_evaluations", "families"):
        assert authority.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize("validator", ["producer", "consumer"])
@pytest.mark.parametrize("fault", ["mixed", "width15", "width17", "width32", "width63", "width65",
    "nonhex", "NaT", "invalid-time", "oversized-time", "bool-version", "zero-version",
    "negative-version", "extra-key", "forbidden-name", "excess"])
def test_malformed_refs_keep_closed_public_admission(validator, fault):
    refs = [reference()]
    if fault == "mixed":
        refs[0]["digest"] = "a" * 16
    elif fault.startswith("width"):
        refs[0]["digest"] = refs[0]["provenance_digest"] = "a" * int(fault[5:])
    elif fault == "nonhex":
        refs[0]["digest"] = "z" * 64
    elif fault in ("NaT", "invalid-time", "oversized-time"):
        refs[0]["training_as_of"] = {"NaT": "NaT", "invalid-time": "not-a-date",
                                    "oversized-time": "2" * 129}[fault]
    elif fault.endswith("version"):
        refs[0]["version"] = {"bool-version": True, "zero-version": 0,
                               "negative-version": -1}[fault]
    elif fault == "extra-key":
        refs[0]["PRIVATE_FIELD"] = "not public input"
    elif fault == "forbidden-name":
        refs[0]["name"] = "broader registry name"
    else:
        refs *= 17
    with pytest.raises(ValueError):
        _model_refs(refs, "backtest") if validator == "producer" else model_refs(refs, "backtest")


@pytest.mark.parametrize("kind", ["walk_forward", "sweep", "sweep_trial"])
def test_windowed_models_stay_unsupported(kind):
    refs = [reference()]
    with pytest.raises(ValueError):
        _model_refs(refs, kind)
    with pytest.raises(ValueError):
        model_refs(refs, kind)


def test_shared_pin_validator_imports_no_model_or_runtime_packages(tmp_path):
    bootstrap = """import importlib.abc, sys
forbidden = ('algua.models', 'algua.strategies', 'algua.config', 'algua.cli')
class RefuseRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == prefix or fullname.startswith(prefix + '.') for prefix in forbidden):
            raise AssertionError('model pin validation imported runtime code')
sys.meta_path.insert(0, RefuseRuntime())
from algua.operator.research_memory_model_refs import public_model_refs
value = [{'name':'fixture', 'version':1, 'digest':'a'*16,
          'training_as_of':'2020-01-01', 'provenance_digest':'b'*16}]
assert public_model_refs(value, kind='backtest') == value
print('data-only pin validation passed')
"""
    completed = subprocess.run([sys.executable, "-I", "-B", "-c", bootstrap],
        capture_output=True, timeout=20,
        env={"HOME": str(tmp_path), "TMPDIR": str(tmp_path), "PATH": "/usr/bin:/bin"})
    assert completed.returncode == 0, completed.stderr.decode()
    assert completed.stdout == b"data-only pin validation passed\n"
