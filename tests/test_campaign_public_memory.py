"""Bounded unverified campaign context, including the actual contained local reader."""
from __future__ import annotations

import copy
import gc
import json
import shutil
import sqlite3
import weakref

import pytest

from algua.operator.research_cycle import CycleLimits, ResearchCycle
from algua.operator.research_memory import ResearchMemory
from algua.registry.db import connect
from algua.registry.store import SqliteStrategyRepository
from tests.campaign_fixtures import add_idea
from tests.test_research_memory import _explore
from tests.test_research_memory import memory_case as memory_case


def _next_menu(authority, cycle):
    add_idea(authority, "SYNTHETIC_FIXTURE retention hypothesis", family="retention",
        duplicate_of_idea_id=1, source_ref="SYNTHETIC_FIXTURE archived-input-v2",
        override_reason="changed_fields=source_ref; ideas:1 idea_attempts:1; "
                        "Archived input timestamps replace the original sampling")
    following = ResearchCycle(authority, cycle.directory, "next-memory-cycle")
    return following.campaign_menu(limits=CycleLimits(max_hypotheses=3), context={},
                                   ttl_minutes=1440)


def _finish(cycle, worker, receipt):
    report = worker / "report.md"
    report.write_text('```json\n{"hypotheses":[{"idea_id":1,"title":"fixture",'
                      '"outcome":"sweep_unstable","reason":"SYNTHETIC_FIXTURE negative"}]}\n```')
    cycle.finish(phase="completed", worker_exit=0, report=report,
                 evidence_ref=receipt["reference"])


def test_actual_contained_context_retains_negative_variants_after_prune(
    memory_case, monkeypatch, record_testsuite_property,
):
    from algua.operator import campaign_memory as module
    from algua.operator.campaign_memory import capture_public_memory

    original = module._run_contained
    monkeypatch.setenv("ALGUA_ALPACA_API_KEY", "FIXTURE_MUST_NOT_REACH_CHILD")
    monkeypatch.setenv("MLFLOW_DISABLE_TELEMETRY", "true")
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMBA_NUM_THREADS"):
        monkeypatch.setenv(name, "64")
    prefix = """import os
from algua.config import settings
def forbidden(*args, **kwargs):
    raise AssertionError('configuration or authored execution must not run')
settings.Settings.__init__ = forbidden
settings.get_settings = forbidden
from algua.strategies import loader
loader.load_strategy = forbidden
loader._resolve_model_handle = forbidden
assert not any(k.startswith(('ALGUA_', 'OPENAI_', 'ANTHROPIC_')) for k in os.environ)
"""
    suffix = """
import json
from mlflow.telemetry import get_telemetry_client
assert get_telemetry_client() is None, 'local archive reader enabled usage telemetry'
sys.stderr.write(json.dumps({'definition_imports': sorted(n for n in sys.modules
    if n.startswith(('algua.config', 'algua.strategies', 'algua.models')))}))
"""
    monkeypatch.setattr(module, "_BOOTSTRAP", prefix + module._BOOTSTRAP + suffix)

    def observed(*args, **kwargs):
        result = original(*args, **kwargs)
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        assert "-I" in args[0] and "-B" in args[0]
        assert kwargs["grace"] == 0 and kwargs["timeout"] <= 20
        assert all(kwargs["env"].get(name) == "1" for name in (
            "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMBA_NUM_THREADS"))
        record_testsuite_property("child_definition_imports",
                                  result.stderr.decode(errors="replace"))
        return result

    monkeypatch.setattr(module, "_run_contained", observed)
    authority, cycle, worker, source, archive, memory = memory_case
    _explore(source)
    receipt = memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    _finish(cycle, worker, receipt)
    menu = _next_menu(authority, cycle)
    assert "idea_attempts:1" in {r for c in menu["choices"] for r in c["prior_evidence_ids"]}
    before = copy.deepcopy(menu)
    authority_before = list(authority.iterdump())
    assert memory.cleanup_allowed(worker)
    shutil.rmtree(worker)
    snapshot = capture_public_memory(menu, cycle_directory=cycle.directory,
        tracking_uri=archive.tracking_uri, tracking_backend="mlflow-sqlite")
    assert snapshot["authority"] == "none" and snapshot["association"] == "cycle_only"
    assert snapshot["evidence_mode"] == "UNVERIFIED_WORKER"
    assert snapshot["observations"][0]["metrics"]["total_return_is"] == -0.3
    assert [r["kind"] for r in snapshot["observations"]] == [
        "backtest", "sweep", "sweep_trial", "sweep_trial"]
    assert snapshot["observations"][2]["parent_refs"] == [
        snapshot["observations"][1]["source_ref"]]
    assert snapshot["receipts"][0]["attempt_evidence_ids"] == ["idea_attempts:1"]
    assert snapshot["coverage"]["included_observations"] == 4
    assert menu == before and list(authority.iterdump()) == authority_before
    assert capture_public_memory(menu, cycle_directory=cycle.directory,
        tracking_uri=archive.tracking_uri, tracking_backend="mlflow-sqlite",
        phase="revalidate") == snapshot


def _selection_menu(attempts, refs):
    return {"choices": [{"prior_evidence_ids": values} for values in refs],
            "scorecard": {"attempts": attempts}, "request": {"database": "/fixture.db"}}


def _attempt(identity, cycle, reference, *, outcome="sweep_unstable"):
    return {"id": identity, "idea_id": identity, "run_stamp": cycle,
            "outcome": outcome, "evidence_ref": reference}


def _reference(identity="a"):
    return f"mlflow:{identity * 32}/public-evidence.json#sha256={'b' * 64}"


def test_relevance_union_terminal_window_and_cycle_order():
    from algua.operator.campaign_memory import select_cycles

    attempts = [_attempt(i, f"cycle-{i}", _reference()) for i in range(1, 70)]
    attempts.append(_attempt(70, "unfinished", _reference(), outcome=None))
    refs = [[f"idea_attempts:{i}" for i in range(1, 35)],
            [f"idea_attempts:{i}" for i in range(35, 71)] + ["ideas:1", "idea_attempts:01"]]
    selected, coverage = select_cycles(_selection_menu(attempts, refs))
    assert [c["research_cycle_id"] for c in selected] == ["cycle-69", "cycle-68"]
    assert coverage["candidate_attempts_considered"] == 64
    assert coverage["candidate_cycles"] == 64


def test_recent_sample_is_cross_family_but_legacy_relevance_stays_explicit():
    from algua.operator.campaign_memory import select_cycles

    rows = [_attempt(1, "completed-negative", _reference()),
            _attempt(2, "unfinished", _reference(), outcome=None),
            _attempt(3, "errored", None, outcome="run_error")]
    menu = _selection_menu(rows, [["ideas:99"]])
    selected, coverage = select_cycles(menu)
    assert [c["research_cycle_id"] for c in selected] == ["completed-negative"]
    assert coverage["candidate_attempts_considered"] == 2
    assert coverage["cycles_without_receipt"] == 1
    legacy, coverage = select_cycles(menu, protocol="relevant_attempts_desc/v1")
    assert legacy == [] and coverage["candidate_attempts_considered"] == 0


def test_old_protocol_actual_archive_roundtrip_keeps_original_selection(memory_case):
    from algua.operator.campaign_memory import select_cycles
    from algua.operator.campaign_memory_admission import revalidate_memory_context
    from algua.operator.campaign_memory_worker import read_batch

    authority, cycle, worker, source, archive, memory = memory_case
    _explore(source)
    receipt = memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    _finish(cycle, worker, receipt)
    menu = _next_menu(authority, cycle)
    cycles, coverage = select_cycles(menu, protocol="relevant_attempts_desc/v1")
    request = {"schema_version": "campaign-public-memory-request/v1", "phase": "capture",
        "database": menu["request"]["database"], "cycle_directory": str(cycle.directory),
        "tracking_uri": archive.tracking_uri, "tracking_backend": "mlflow-sqlite",
        "cutoff": 1, "cycles": cycles, "coverage": coverage}
    old = read_batch(request)  # Existing requests without a protocol field keep their old meaning.
    assert old["selection_protocol"] == "relevant_attempts_desc/v1"
    menu["request"]["context"]["public_research_memory"] = old
    before = list(authority.iterdump())
    assert revalidate_memory_context(cycle, menu, tracking_uri=archive.tracking_uri,
                                     tracking_backend="mlflow-sqlite") == old
    assert list(authority.iterdump()) == before


def test_conflict_in_unselected_cycle_is_not_hidden():
    from algua.operator.campaign_memory import select_cycles

    rows = [_attempt(4, "first", _reference()), _attempt(3, "second", _reference()),
            _attempt(2, "conflict", _reference()), _attempt(1, "conflict", _reference("c"))]
    with pytest.raises(ValueError, match="receipt_invalid"):
        select_cycles(_selection_menu(rows, [[f"idea_attempts:{i}" for i in range(1, 5)]]))


@pytest.mark.parametrize("run_id", ["Legacy_Run-42", "Run_α", "Legacy_Run-42\n"])
def test_installed_legacy_run_ids_are_not_narrowed_by_context_parser(run_id):
    from mlflow.utils.validation import _validate_run_id

    from algua.operator.campaign_memory import select_cycles

    _validate_run_id(run_id)
    reference = f"mlflow:{run_id}/public-evidence.json#sha256={'b' * 64}"
    selected, _ = select_cycles(_selection_menu(
        [_attempt(1, "legacy-cycle", reference)], [["idea_attempts:1"]]))
    assert selected[0]["evidence_ref"] == reference


def test_missing_and_legacy_references_do_not_backfill_beyond_window():
    from algua.operator.campaign_memory import select_cycles

    rows = [_attempt(i, f"cycle-{i}", None if i % 2 else "legacy:report") for i in range(2, 66)]
    rows.append(_attempt(1, "old-archive", _reference()))
    selected, coverage = select_cycles(_selection_menu(rows, [[f"idea_attempts:{i}"
                                      for i in range(1, 66)]]))
    assert selected == [] and coverage["cycles_without_receipt"] == 64


@pytest.mark.parametrize("fault", ["metrics", "input", "kind", "model", "source_ref", "authority"])
def test_full_public_payload_validation_refuses_private_or_malformed_vocabulary(memory_case, fault):
    from algua.operator.campaign_memory_worker import project_snapshot

    authority, cycle, worker, source, archive, memory = memory_case
    _explore(source)
    receipt = memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    payload = memory.read()
    if fault == "metrics":
        payload["evaluations"][0]["metrics"]["holdout_sharpe"] = 99
    elif fault == "input":
        payload["evaluations"][0]["inputs"]["private_diagnostics"] = "NEVER_CONTEXT"
    elif fault == "kind":
        payload["evaluations"][0]["kind"] = "gate"
    elif fault == "model":
        payload["evaluations"][0]["model_refs"] = [{"name": "missing-pin"}]
    elif fault == "source_ref":
        payload["evaluations"][0]["source_ref"] = "scratch:another:runs:1"
    else:
        payload["authority"] = "gate"
    with pytest.raises(ValueError, match="artifact_payload_invalid"):
        project_snapshot([{"receipt": receipt, "payload": payload}],
                         coverage={"candidate_attempts_considered": 1, "candidate_cycles": 1,
                                   "cycles_without_receipt": 0}, cutoff=1,
                         tracking_uri=archive.tracking_uri)


def test_whole_input_four_kib_and_omission_precedence(memory_case):
    from algua.operator.campaign_memory_worker import project_snapshot

    _, _, worker, source, archive, memory = memory_case
    _explore(source)
    receipt = memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    payload = memory.read()
    prototype = payload["evaluations"][0]
    payload["evaluations"] = []
    for i in range(1, 31):
        row = copy.deepcopy(prototype)
        row.update(source_run_id=i, source_ref=f"scratch:fixture-memory:runs:{i}")
        row["inputs"] = {"params": {"label": "x" * (4100 if i == 1 else 2387)}}
        payload["evaluations"].append(row)
    payload["coverage"].update(retained_evaluations=30, kind_counts={"backtest": 30},
                               truncated_sweeps=[])
    view = project_snapshot([{"receipt": receipt, "payload": payload}],
        coverage={"candidate_attempts_considered": 1, "candidate_cycles": 1,
                  "cycles_without_receipt": 0}, cutoff=1, tracking_uri=archive.tracking_uri)
    coverage = view["coverage"]
    assert coverage["omitted_for_input_bytes"] == 1
    assert coverage["omitted_for_count"] == 5
    assert coverage["omitted_for_context_bytes"] > 0
    assert len(json.dumps(view, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False).encode()) <= 24 * 1024
    assert [int(o["source_ref"].rsplit(":", 1)[1]) for o in view["observations"]] == list(
        range(2, 2 + coverage["included_observations"]))
    assert all(o["inputs"] == {"params": {"label": "x" * 2387}} for o in view["observations"])
    assert coverage["retained_public_observations"] == (
        coverage["included_observations"] + coverage["omitted_observations"])


def test_caller_rejects_late_false_timeout_result(memory_case, monkeypatch):
    from algua.operator import campaign_memory as module

    authority, cycle, _, _, archive, _ = memory_case
    menu = _next_menu(authority, cycle)
    ticks = iter([100.0, 100.0, 121.0])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(ticks))

    def late(*args, **kwargs):
        from algua.primitives.contained_process import ContainedResult
        return ContainedResult(0, None, False, b"{}", False, b"", False)

    monkeypatch.setattr(module, "_run_contained", late)
    with pytest.raises(ValueError, match="read_deadline_exceeded"):
        module.capture_public_memory(menu, cycle_directory=cycle.directory,
            tracking_uri=archive.tracking_uri, tracking_backend="mlflow-sqlite")


def test_caller_rejects_deadline_reached_during_schema_validation(memory_case, monkeypatch):
    from algua.operator import campaign_memory as module
    from algua.primitives.contained_process import ContainedResult

    authority, cycle, _, _, archive, _ = memory_case
    menu = _next_menu(authority, cycle)
    ticks = iter([100.0, 100.0, 119.0, 121.0])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(module, "_run_contained", lambda *a, **k:
        ContainedResult(0, None, False, b"{}", False, b"", False))
    monkeypatch.setattr(module, "_wire", lambda raw: {})
    with pytest.raises(ValueError, match="read_deadline_exceeded"):
        module.capture_public_memory(menu, cycle_directory=cycle.directory,
            tracking_uri=archive.tracking_uri, tracking_backend="mlflow-sqlite")


def test_deadline_dominates_schema_failure_after_validation_crosses_deadline(
    memory_case, monkeypatch,
):
    from algua.operator import campaign_memory as module
    from algua.operator.campaign_memory_schema import MemoryContextError
    from algua.primitives.contained_process import ContainedResult

    authority, cycle, _, _, archive, _ = memory_case
    ticks = iter([100.0, 100.0, 119.0, 121.0])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(module, "_run_contained", lambda *a, **k:
        ContainedResult(0, None, False, b"{}", False, b"", False))

    def expired_validation(raw):
        raise MemoryContextError("worker_result_invalid")

    monkeypatch.setattr(module, "_wire", expired_validation)
    with pytest.raises(ValueError, match="read_deadline_exceeded"):
        module.capture_public_memory(_next_menu(authority, cycle),
            cycle_directory=cycle.directory, tracking_uri=archive.tracking_uri,
            tracking_backend="mlflow-sqlite")


def test_two_actual_cycles_release_full_payload_before_opening_the_next(memory_case, monkeypatch):
    from algua.operator.campaign_memory import capture_public_memory, select_cycles
    from algua.operator.campaign_memory_worker import read_batch
    from algua.tracking.research_archive import LocalResearchArchive

    authority, first, worker, source, archive, memory = memory_case
    _explore(source)
    receipt = memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    _finish(first, worker, receipt)
    second_idea = add_idea(authority, "SYNTHETIC_FIXTURE overnight gap response",
                           family="gap-response")
    second = ResearchCycle(authority, first.directory, "fixture-second")
    second.start(limits=CycleLimits(max_hypotheses=1), context={"evidence_mode": "FIXTURE"},
                 category="gap-response", ttl_minutes=1440)
    worker2 = worker.parent / "disposable-second"
    source2 = worker2 / ".funnel-scratch/data/algua.db"
    source2.parent.mkdir(parents=True)
    with sqlite3.connect(source2) as destination:
        authority.backup(destination)
    memory2 = ResearchMemory(second, archive)
    memory2.seed(worker2)
    _explore(source2)
    receipt2 = memory2.capture(worker2, worker_exit=0, source_commit="c" * 40)
    report = worker2 / "report.md"
    report.write_text('```json\n' + json.dumps({"hypotheses": [{"idea_id": second_idea.id,
        "title": "fixture", "outcome": "sweep_unstable", "reason": "SYNTHETIC_FIXTURE"}]})
        + '\n```')
    second.finish(phase="completed", worker_exit=0, report=report,
                   evidence_ref=receipt2["reference"])
    _next_menu(authority, first)
    add_idea(authority, "SYNTHETIC_FIXTURE overnight gap response", family="gap-response",
        duplicate_of_idea_id=second_idea.id, source_ref="SYNTHETIC_FIXTURE archived-gap-v2",
        override_reason="changed_fields=source_ref; ideas:2 idea_attempts:2; "
                        "Archived gap timestamps replace the original sampling")
    menu = ResearchCycle(authority, first.directory, "next-both").campaign_menu(
        limits=CycleLimits(max_hypotheses=6), context={}, ttl_minutes=1440)
    cycles, coverage = select_cycles(menu)
    assert [c["research_cycle_id"] for c in cycles] == ["fixture-second", "fixture-memory"]
    assert memory.cleanup_allowed(worker) and memory2.cleanup_allowed(worker2)
    shutil.rmtree(worker)
    shutil.rmtree(worker2)
    expected = capture_public_memory(menu, cycle_directory=first.directory,
        tracking_uri=archive.tracking_uri, tracking_backend="mlflow-sqlite")

    class OwnedPayload(dict):
        pass

    class OwnedInputs(dict):
        pass

    references = []
    original = LocalResearchArchive.read

    def observed(self, *args, **kwargs):
        gc.collect()
        assert all(ref() is None for ref in references), "previous full payload is still retained"
        payload = OwnedPayload(original(self, *args, **kwargs))
        for row in payload["evaluations"]:
            inputs = OwnedInputs(row["inputs"])
            inputs.owner = payload
            row["inputs"] = inputs
        references.append(weakref.ref(payload))
        return payload

    monkeypatch.setattr(LocalResearchArchive, "read", observed)
    actual = read_batch({"schema_version": "campaign-public-memory-request/v1", "phase": "capture",
        "selection_protocol": "recent_completed_windows_first/v1",
        "database": menu["request"]["database"], "cycle_directory": str(first.directory),
        "tracking_uri": archive.tracking_uri, "tracking_backend": "mlflow-sqlite", "cutoff": 2,
        "cycles": cycles, "coverage": coverage})
    gc.collect()
    assert all(ref() is None for ref in references)
    assert len(actual["observations"]) == 8 and actual == expected


@pytest.mark.parametrize("version,seed", [(2**80, 5), (1, -7), (2**80, -7)])
def test_valid_producer_large_model_version_and_signed_seed_roundtrip(memory_case, version, seed):
    from algua.operator.campaign_memory_worker import project_snapshot

    _, _, worker, source, archive, memory = memory_case
    pins = [{"name": "fixture-only-pin", "version": version, "digest": "c" * 64,
             "training_as_of": "2024-01-01T00:00:00+00:00", "provenance_digest": "d" * 64}]
    conn = connect(source)
    with conn:
        SqliteStrategyRepository(conn).record_run(
            "backtest", "SYNTHETIC_FIXTURE metadata-only", components=pins,
            provenance={"seed": seed}, config={"params": {"n": 3}})
    conn.close()
    receipt = memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    snapshot = project_snapshot([{"receipt": receipt, "payload": memory.read()}],
        coverage={"candidate_attempts_considered": 1, "candidate_cycles": 1,
                  "cycles_without_receipt": 0}, cutoff=1, tracking_uri=archive.tracking_uri)
    assert snapshot["observations"][0]["model_refs"] == pins
    assert snapshot["observations"][0]["provenance"]["seed"] == seed


def test_projection_preserves_public_model_pins_without_resolution(memory_case):
    from algua.operator.campaign_memory_worker import project_snapshot

    _, _, worker, source, archive, memory = memory_case
    _explore(source)
    receipt = memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    payload = memory.read()
    pins = [{"name": "fixture-model", "version": 1, "digest": "c" * 64,
             "training_as_of": "2024-01-01T00:00:00+00:00", "provenance_digest": "d" * 64}]
    payload["evaluations"][0]["model_refs"] = pins
    snapshot = project_snapshot([{"receipt": receipt, "payload": payload}],
        coverage={"candidate_attempts_considered": 1, "candidate_cycles": 1,
                  "cycles_without_receipt": 0}, cutoff=1, tracking_uri=archive.tracking_uri)
    assert snapshot["observations"][0]["model_refs"] == pins


@pytest.mark.parametrize("fault", ["extra", "count", "authority", "association", "size", "ref"])
def test_pure_stored_snapshot_validator_refuses_edits(memory_case, fault):
    from algua.operator.campaign_memory import validate_public_memory_snapshot
    from algua.operator.campaign_memory_worker import project_snapshot

    _, _, worker, source, archive, memory = memory_case
    _explore(source)
    receipt = memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    snapshot = project_snapshot([{"receipt": receipt, "payload": memory.read()}],
        coverage={"candidate_attempts_considered": 1, "candidate_cycles": 1,
                  "cycles_without_receipt": 0}, cutoff=1, tracking_uri=archive.tracking_uri)
    detached = validate_public_memory_snapshot(snapshot)
    assert detached == snapshot and detached is not snapshot
    if fault == "extra":
        snapshot["private"] = "NEVER_CONTEXT"
    elif fault == "count":
        snapshot["coverage"]["included_observations"] = 999
    elif fault in ("authority", "association"):
        snapshot[fault] = "trusted"
    elif fault == "size":
        snapshot["observations"][0]["inputs"]["params"]["label"] = "x" * 30_000
    else:
        snapshot["observations"][0]["archive_ref"] = _reference("f")
    with pytest.raises(ValueError, match="worker_result_invalid"):
        validate_public_memory_snapshot(snapshot)
