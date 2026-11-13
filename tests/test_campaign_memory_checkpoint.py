"""Shared checkpoint checks over actual retained fixture experiments."""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

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
    from algua.operator.research_memory_checkpoint import (
        MAX_CHECKPOINT_BYTES,
        load_checkpoint,
        validate_retained_payload,
    )
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
        metadata["padding"] = "x" * MAX_CHECKPOINT_BYTES
    cycle.path.write_text(json.dumps(metadata))
    database = authority.execute("PRAGMA database_list").fetchone()[2]
    with pytest.raises(ValueError):
        checkpoint = load_checkpoint(cycle.directory, cycle.cycle_id, database=database,
                                     budget=ReadBudget(2 * MAX_CHECKPOINT_BYTES))
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


@pytest.mark.parametrize('adapter', ['index', 'batch'])
def test_large_completed_checkpoint_is_readable_by_bounded_consumers(memory_case, adapter):
    from algua.operator.campaign_memory_worker import read_batch
    from algua.operator.research_memory_index import read_retained_research

    authority, cycle, worker, source, archive, memory = memory_case
    target = cycle.directory.with_name('research-cycles')
    cycle.directory.rename(target)
    cycle.directory = target
    cycle.path = target / f'{cycle.cycle_id}.json'
    # Captured campaign history is retained alongside, not inside, the hashed execution context.
    metadata = json.loads(cycle.path.read_text())
    metadata['request']['fixture_captured_campaign'] = 'x' * (600 * 1024)
    cycle.path.write_text(json.dumps(metadata))
    _explore(source)
    receipt = memory.capture(worker, worker_exit=0, source_commit='b' * 40)
    before = cycle.path.read_bytes()
    assert 512 * 1024 < len(before) < 1024 * 1024
    database = authority.execute('PRAGMA database_list').fetchone()[2]
    if adapter == 'index':
        result = read_retained_research(cycle.cycle_id, database=Path(database),
            data_dir=cycle.directory.parent, tracking_uri=archive.tracking_uri,
            tracking_backend='mlflow-sqlite')
        assert len(result['evaluations']) == 4
    else:
        result = read_batch({'schema_version': 'campaign-public-memory-request/v1',
            'phase': 'capture', 'database': database, 'cycle_directory': str(cycle.directory),
            'tracking_uri': archive.tracking_uri, 'tracking_backend': 'mlflow-sqlite',
            'cutoff': 1, 'cycles': [{'research_cycle_id': cycle.cycle_id,
                'evidence_ref': receipt['reference'], 'attempts': [
                    {'evidence_id': 'idea_attempts:1', 'idea_id': 1}]}],
            'coverage': {'candidate_attempts_considered': 1, 'candidate_cycles': 1,
                         'cycles_without_receipt': 0}})
        assert result['status'] == 'available' and len(result['observations']) == 4
    assert cycle.path.read_bytes() == before
