"""Shared checkpoint checks over actual retained fixture experiments."""
from __future__ import annotations

import copy
import json
import shutil

import pytest

from tests.test_research_memory import _explore
from tests.test_research_memory import memory_case as memory_case


def test_bounded_checkpoint_survives_prune_and_shares_retained_validation(memory_case):
    from algua.operator.research_memory_checkpoint import (
        load_checkpoint,
        validate_retained_payload,
    )
    from algua.tracking.bounded_local_read import ReadBudget

    authority, cycle, worker, source, _, memory = memory_case
    _explore(source)
    memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    expected = memory.read()
    assert memory.cleanup_allowed(worker)
    shutil.rmtree(worker)
    database = authority.execute("PRAGMA database_list").fetchone()[2]
    metadata = load_checkpoint(cycle.directory, cycle.cycle_id, database=database,
                               budget=ReadBudget(512 * 1024))
    assert validate_retained_payload(expected, metadata=metadata,
                                     cycle_id=cycle.cycle_id) == expected
    assert memory.read() == expected


@pytest.mark.parametrize("fault", ["registry", "cycle", "seed", "context", "receipt", "size"])
def test_checkpoint_refuses_wrong_or_oversized_evidence(memory_case, fault):
    from algua.operator.research_memory_checkpoint import load_checkpoint, validate_retained_payload
    from algua.tracking.bounded_local_read import ReadBudget

    authority, cycle, _, source, _, memory = memory_case
    _explore(source)
    memory.capture(cycle.directory.parent / "disposable-worker", worker_exit=0,
                   source_commit="b" * 40)
    payload = memory.read()
    metadata = json.loads(cycle.path.read_text())
    if fault == "registry":
        metadata["request"]["database"] = "/unrelated.db"
    elif fault == "cycle":
        metadata["request"]["research_cycle_id"] = "another-cycle"
    elif fault == "seed":
        metadata["research_memory"]["seed"]["registry_digest"] = "invalid"
    elif fault == "context":
        metadata["request"]["context"]["changed"] = True
    elif fault == "receipt":
        metadata["research_memory"].pop("receipt")
    else:
        metadata["padding"] = "x" * (256 * 1024)
    cycle.path.write_text(json.dumps(metadata))
    database = authority.execute("PRAGMA database_list").fetchone()[2]
    with pytest.raises(ValueError):
        checkpoint = load_checkpoint(cycle.directory, cycle.cycle_id, database=database,
                                     budget=ReadBudget(512 * 1024))
        validate_retained_payload(payload, metadata=checkpoint, cycle_id=cycle.cycle_id)


def test_shared_payload_check_rejects_checkpoint_drift_without_mutating_payload(memory_case):
    from algua.operator.research_memory_checkpoint import validate_retained_payload

    _, cycle, worker, source, _, memory = memory_case
    _explore(source)
    memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    payload = memory.read()
    before = copy.deepcopy(payload)
    changed = json.loads(cycle.path.read_text())
    changed["request"]["context"]["changed"] = True
    with pytest.raises(ValueError, match="controller checkpoint"):
        validate_retained_payload(payload, metadata=changed, cycle_id=cycle.cycle_id)
    assert payload == before
