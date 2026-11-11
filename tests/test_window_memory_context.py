"""Window evidence fits bounded planner memory before verbose aggregate records."""
from __future__ import annotations

import pytest

from algua.operator.campaign_memory_worker import project_snapshot
from algua.operator.research_memory_checkpoint import canonical
from algua.registry.db import connect
from algua.registry.runs import record_walk_forward_run
from algua.registry.store import SqliteStrategyRepository
from tests.registry.test_public_windows import sentinel_result
from tests.test_research_memory import memory_case as memory_case

PROTOCOL = 'recent_completed_windows_first/v1'
COVERAGE = dict(candidate_attempts_considered=1, candidate_cycles=1, cycles_without_receipt=0)


def archive_case(memory_case):
    _, _, worker, source, archive, memory = memory_case
    conn = connect(source)
    repo = SqliteStrategyRepository(conn)
    # Two earlier verbose records reproduce the production context starvation.
    for i in range(2):
        repo.record_run('backtest', f'SYNTHETIC_FIXTURE aggregate {i}',
                        config={'params': {'padding': 'x' * 3500}}, metrics={'sharpe_is': 0.1})
    identity = record_walk_forward_run(repo, 'SYNTHETIC_FIXTURE public windows', sentinel_result(),
                                      params={'padding': 'x' * 3500},
                                      research_inputs={'delisting_snapshot': None,
                                                       'assume_terminal_last_close': False})
    conn.close()
    receipt = memory.capture(worker, worker_exit=0, source_commit='b' * 40)
    return archive, receipt, memory.read(), identity


def test_new_protocol_keeps_complete_window_inputs_and_old_protocol_replays(memory_case):
    archive, receipt, payload, identity = archive_case(memory_case)
    inputs = payload['evaluations'][-1]['inputs']
    assert 4096 < len(canonical(inputs)) < 16384
    kwargs = dict(coverage=COVERAGE, cutoff=1, tracking_uri=archive.tracking_uri)
    legacy = project_snapshot([dict(receipt=receipt, payload=payload)],
                               selection_protocol='recent_completed_attempts_desc/v1', **kwargs)
    assert [r['source_ref'].rsplit(':', 1)[1] for r in legacy['observations']] == ['2', '3']
    assert legacy['coverage']['omitted_for_input_bytes'] == 1
    assert legacy['coverage']['included_observations'] == 2
    current = project_snapshot([dict(receipt=receipt, payload=payload)],
                                selection_protocol=PROTOCOL, **kwargs)
    from copy import deepcopy

    from algua.operator.campaign_memory_schema import validate_snapshot

    relabeled = deepcopy(current)
    relabeled['selection_protocol'] = 'recent_completed_attempts_desc/v1'
    with pytest.raises(ValueError):
        validate_snapshot(relabeled)
    assert len(current['observations']) > 1
    disordered = deepcopy(current)
    disordered['observations'].reverse()
    with pytest.raises(ValueError):
        validate_snapshot(disordered)
    first = current['observations'][0]
    assert first['source_ref'] == f'scratch:fixture-memory:runs:{identity}'
    assert first['inputs'] == inputs  # No removal of provenance, parameters or dated windows.
    assert len(canonical(current)) <= 24 * 1024
    assert current['authority'] == 'none' and current['evidence_mode'] == 'UNVERIFIED_WORKER'
    assert project_snapshot([dict(receipt=receipt, payload=payload)],
                            selection_protocol='recent_completed_attempts_desc/v1',
                            **kwargs) == legacy


@pytest.mark.parametrize('fault', ['oversized', 'malformed'])
def test_large_windows_omit_whole_or_malformed_refuse_before_budget(memory_case, fault):
    archive, receipt, payload, _ = archive_case(memory_case)
    row = payload['evaluations'][-1]
    if fault == 'oversized':
        row['inputs']['params']['padding'] = 'x' * 17000
        # Pure projection fixture only: receipt SHA is not reverified after this mutation.
    else:
        row['inputs']['public_window_record']['windows'][0]['private_tail'] = 123
    kwargs = dict(coverage=COVERAGE, cutoff=1, tracking_uri=archive.tracking_uri,
                  selection_protocol=PROTOCOL)
    if fault == 'malformed':
        with pytest.raises(ValueError):
            project_snapshot([dict(receipt=receipt, payload=payload)], **kwargs)
    else:
        view = project_snapshot([dict(receipt=receipt, payload=payload)], **kwargs)
        assert not any(r['kind'] == 'walk_forward' for r in view['observations'])
        assert view['coverage']['omitted_for_input_bytes'] == 1
