"""The model profile is explicit; v1 bytes and bindings remain unchanged."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pandas as pd
import pytest

from algua.data.store import DataStore
from algua.live.frozen_wire import WireError, WireIdentity, decode_request, encode_request
from algua.live.frozen_wire_json import canonical_bytes
from algua.live.frozen_wire_result import decode_result, encode_result
from algua.live.planner import phase_a, phase_b
from algua.live.planner_binding import phase_a_binding
from algua.live.planner_contract import (
    CapturedStrategyState,
    LatePlannerInput,
    PhaseBindingFailure,
    PlannerInputFailure,
    SnapshotRequired,
    VenueBeliefDisabled,
)
from tests._frozen_harness import (
    ENV_DIGEST,
    MANIFEST,
    digest,
    early_input,
    in_process,
)
from tests.test_frozen_model_manifest import model_strategy
from tests.test_trained_model_context import trained as trained


def model_early(trained):
    strategy = model_strategy(trained)
    data, _, record, dates, *_ = trained
    bars = DataStore(data).read_bars(record.snapshot_id).loc[dates[16]:dates[24]]
    return strategy, replace(early_input(strategy), boundary_version=2,
        now=(dates[24] + pd.Timedelta(days=1)).to_pydatetime(), raw_bars=bars,
        early_positions={}, bars_snapshot_id=record.snapshot_id)


def identity(early, version=2, key='model'):
    return WireIdentity(early.strategy_name, 7, 11, MANIFEST, digest(key), ENV_DIGEST,
                        protocol_version=version)


def model_late(strategy, early):
    first = phase_a(strategy, early)
    assert isinstance(first, SnapshotRequired), first
    return LatePlannerInput(early, first.phase_a_binding,
        CapturedStrategyState(early.request_id, 100., 100., {}, {}, 100., VenueBeliefDisabled()))


def test_v1_request_and_binding_golden_unchanged():
    strategy = in_process()
    early = early_input(strategy)
    target = WireIdentity(strategy.name, 7, 11, MANIFEST, digest('good'), ENV_DIGEST)
    assert hashlib.sha256(encode_request('a', early, None, target)[0]).hexdigest() == (
        '233369aaca9eec22d4a5dcfc77f54dbada5c9f16e23874d8a44ae9b4e72245ca')
    assert phase_a_binding(early, decision_ts=None, warming=False) == (
        'b878b1eb0b25aad2b2995b281905caca41dbde1a5e1a42c36bb99cd65d8bdd38')


def test_model_v2_request_roundtrip(trained):
    strategy, early = model_early(trained)
    late = model_late(strategy, early)
    raw, bars = encode_request('b', early, late, identity(early))
    document = json.loads(raw)
    assert document['wire']['version'] == 2
    assert document['early']['model_ref'] == strategy.config.model_ref.as_dict()
    assert 'artifact_bytes' not in raw.decode()
    decoded = decode_request(raw, bars)
    assert decoded.identity.protocol_version == decoded.early.boundary_version == 2
    assert decoded.early.bars_snapshot_id == early.bars_snapshot_id
    assert phase_b(strategy, decoded.late) == phase_b(strategy, late)
    result = phase_a(strategy, early)
    payload = encode_result('a', early.request_id, result, protocol_version=2)
    assert decode_result(payload, phase='a', request_id=early.request_id,
                         protocol_version=2) == result
    with pytest.raises(WireError):
        decode_result(payload, phase='a', request_id=early.request_id)


@pytest.mark.parametrize('snapshot', [None, '', '  ', ' snapshot ', 4])
def test_model_snapshot_required(trained, snapshot):
    strategy, early = model_early(trained)
    early = replace(early, bars_snapshot_id=snapshot)
    assert isinstance(phase_a(strategy, early), PlannerInputFailure)
    with pytest.raises(WireError):
        encode_request('a', early, None, identity(early))


@pytest.mark.parametrize('field,value', [('model_ref', None), ('bars_snapshot_id', '')])
def test_wire_extension_cannot_disagree(trained, field, value):
    _, early = model_early(trained)
    raw, bars = encode_request('a', early, None, identity(early))
    document = json.loads(raw)
    document['early'][field] = value
    with pytest.raises(WireError):
        decode_request(canonical_bytes(document), bars)


def test_changed_snapshot_or_model_invalidates_phase_b(trained):
    strategy, early = model_early(trained)
    late = model_late(strategy, early)
    changed = replace(late, early=replace(early, bars_snapshot_id='another-snapshot'))
    assert isinstance(phase_b(strategy, changed), PhaseBindingFailure)
    config = json.loads(early.resolved_config_json)
    config['model_ref']['digest'] = 'a' * 16
    changed = replace(early, resolved_config_json=json.dumps(config, sort_keys=True,
                                                           separators=(',', ':')))
    assert phase_a_binding(changed, decision_ts=None, warming=False) != phase_a_binding(
        early, decision_ts=None, warming=False)
    assert isinstance(phase_b(strategy, replace(late, early=changed)), PhaseBindingFailure)


@pytest.mark.parametrize('warmup', [False, True])
def test_future_model_cutoff_refuses_before_warmup(trained, warmup):
    strategy, early = model_early(trained)
    dates = trained[3]
    bars = DataStore(trained[0]).read_bars(trained[2].snapshot_id)
    cutoff = dates[2] if warmup else dates[8]
    early = replace(early, raw_bars=bars.loc[:cutoff], now=(cutoff + pd.Timedelta(days=1)))
    result = phase_a(strategy, early)
    assert isinstance(result, PlannerInputFailure), result
    assert 'training_as_of' in result.detail


@pytest.mark.parametrize('value', [None, [], 1, 'config', True])
def test_model_config_must_be_an_object_before_profile_dispatch(trained, value):
    _, early = model_early(trained)
    raw, bars = encode_request('a', early, None, identity(early))
    document = json.loads(raw)
    document['early']['resolved_config'] = value
    with pytest.raises(WireError) as refused:
        decode_request(canonical_bytes(document), bars)
    assert refused.value.reason == 'bad_type'
