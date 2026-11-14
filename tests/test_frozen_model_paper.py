"""Trusted-fixture mechanics, and the separate closed authoritative admission boundary."""
from __future__ import annotations

import json

import pytest

from algua.cli.main import app
from algua.contracts.frozen_model import MODEL_ARTIFACT
from algua.contracts.model_types import ModelHandle
from tests._frozen_harness import unseal
from tests._frozen_paper_world import (
    CHECKOUT_MODULE,
    SNAP,
    TENANT,
    build_world,
    runner,
    teardown_world,
)
from tests.test_trained_model_context import trained as trained

pytestmark = pytest.mark.serial  # writes into the real algua/ source tree


@pytest.fixture
def world(trained, monkeypatch, tmp_path):
    root = tmp_path / 'paper'
    try:
        yield build_world(monkeypatch, root, model_handle=ModelHandle(*trained[-2:]))
    finally:
        teardown_world(root / 'data')


def test_model_paper_tick_uses_bundle_and_exact_snapshot(world):
    original = world.deployment().manifest_digest
    CHECKOUT_MODULE.write_text("raise RuntimeError('mutable checkout must not load')\n")
    code, payload = world.trade_tick()
    assert code == 0, payload
    assert world.orders(TENANT)
    assert len(world.sent) == 2
    for sent in world.sent:
        request = json.loads(sent['request.json'])
        assert request['wire']['version'] == request['early']['boundary_version'] == 2
        assert request['early']['bars_snapshot_id'] == SNAP
        assert request['early']['model_ref'] == request['early']['resolved_config']['model_ref']
    rows = world.rows('SELECT * FROM frozen_invocations ORDER BY id')
    assert len(rows) == 2
    assert {row['snapshot_id'] for row in rows} == {SNAP}
    assert {row['deployment_id'] for row in rows} == {world.deployment().id}
    [tick] = world.ticks(TENANT)
    assert tick['frozen_invocation_id'] == rows[-1]['id'] and tick['snapshot_id'] == SNAP
    assert world.deployment().manifest_digest == original


def test_model_corruption_produces_no_tenant_orders(world):
    original = world.deployment().manifest_digest
    unseal(world.bundle_root)
    path = world.bundle_root / MODEL_ARTIFACT
    path.chmod(0o644)
    path.write_bytes(path.read_bytes() + b' ')
    code, payload = world.trade_tick()
    assert code == 1 and payload['code'] == 'frozen_content_unavailable', payload
    assert world.orders(TENANT) == []
    assert world.launches == []
    assert not any(row['lane'] == 'live' for row in world.ticks(TENANT))
    assert world.deployment().manifest_digest == original


def test_model_paper_still_requires_paper_stage(world):
    with world.conn() as conn:
        conn.execute("UPDATE strategies SET stage='backtested' WHERE name=?", (TENANT,))
        conn.commit()
    code, payload = world.trade_tick()
    assert code == 1 and payload['ok'] is False
    assert world.orders(TENANT) == [] and world.launches == []


def test_restarted_model_tick_preserves_existing_order_idempotency(world):
    code, first = world.trade_tick()
    assert code == 0, first
    orders = world.orders(TENANT)
    submitted = list(world.broker.submitted_for(TENANT))
    CHECKOUT_MODULE.unlink()
    code, second = world.trade_tick()
    assert code == 0, second
    assert world.orders(TENANT) == orders
    assert {effect[3] for effect in world.broker.submitted_for(TENANT)} == {
        effect[3] for effect in submitted}
    assert len(world.rows('SELECT * FROM frozen_invocations')) == 4


def test_model_paper_does_not_enable_live(world):
    with world.conn() as conn:
        conn.execute("UPDATE strategies SET stage='forward_tested' WHERE name=?", (TENANT,))
        conn.commit()
    result = runner.invoke(app, ['registry', 'transition', TENANT, '--to', 'live',
                                '--actor', 'human'])
    assert result.exit_code == 1
    assert json.loads(result.stdout)['code'] == 'frozen_live_unsupported'
    assert world.orders(TENANT) == []
    assert not any(row['lane'] == 'live' for row in world.ticks(TENANT))
    assert world.rows('SELECT * FROM approvals') == []
    assert world.launches == []
