"""Synthetic lineage + real frozen bundle/child and SSH signatures; no network or real trades."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from algua.calendar.factory import get_calendar
from algua.cli import experimental_handoff
from algua.cli.capped_runtime import verify_live_authorization
from algua.cli.main import app
from algua.contracts.lifecycle import Actor, Stage
from algua.operator.schedule import target_session
from algua.registry import capped_auth, experimental_qualification, live_gate
from algua.registry.allocations import active_allocation
from algua.registry.capped_active import active
from algua.registry.capped_state import revoke
from algua.registry.drawdown_auth import signed_change
from algua.registry.experimental_sessions import PROFILE_DIGEST
from algua.registry.store import SqliteStrategyRepository
from algua.risk.layered import DrawdownPolicy
from tests._frozen_paper_world import ACCOUNT_ID, GATE, TENANT, build_world, teardown_world
from tests._ssh_signing import _anchor, _make_key, _sign
from tests.test_trained_model_context import trained as trained

pytestmark = pytest.mark.serial  # writes into the real algua/ source tree


def _qualify(conn):
    """Explicit synthetic history/session rows test binding, never statistical eligibility."""
    repo = SqliteStrategyRepository(conn)
    dep = repo.active_deployment(repo.get(TENANT).id)
    gate = conn.execute(
        "SELECT * FROM gate_evaluations WHERE id=?", (dep.research_gate_id,)
    ).fetchone()
    stamp = "2026-08-31T20:00:00+00:00"
    conn.execute(
        "UPDATE gate_evaluations SET created_at=?,decision_json=? WHERE id=?",
        (stamp, '{"passed":true}', gate["id"]),
    )
    burn = conn.execute(
        "INSERT INTO holdout_evaluations "
        "(strategy_id,data_source,snapshot_id,period_start,period_end,holdout_frac,config_hash,"
        "reused,created_at,committed_at,holdout_start,holdout_end) "
        "VALUES (?,'test','snap','2024-01-01','2024-12-31',0.2,'wf-config',0,?,?,"
        "'2024-10-01','2024-12-31')",
        (dep.strategy_id, stamp, stamp),
    ).lastrowid
    series = conn.execute(
        "INSERT INTO holdout_returns "
        "(holdout_evaluation_id,strategy_id,holdout_start,holdout_end,n_bars,returns_blob,"
        "bar_dates_blob,created_at) VALUES (?,?,'2024-10-01','2024-12-31',63,?,?,?)",
        (burn, dep.strategy_id, b"SYNTHETIC_FIXTURE", b"SYNTHETIC_FIXTURE", stamp),
    ).lastrowid
    common = {
        k: gate[k]
        for k in ("data_source", "snapshot_id", "period_start", "period_end", "universe_name")
    }
    wf = repo.record_run(
        "walk_forward",
        TENANT,
        strategy_id=dep.strategy_id,
        provenance=common | {"config_hash": "wf-config"},
    )
    repo.record_run(
        "gate",
        TENANT,
        strategy_id=dep.strategy_id,
        derived_from=[wf],
        provenance=common
        | {k: getattr(dep, k) for k in ("code_hash", "config_hash", "dependency_hash")},
        gate_id=gate["id"],
        passed=True,
        series_holdout_id=series,
        metrics={"sharpe_oos": 0.4, "n_obs_oos": 63},
    )
    conn.execute("UPDATE runs SET created_at=?", (stamp,))
    cal, now = get_calendar(), datetime.now(UTC)
    last = target_session(now, cal)
    for _ in range(5):
        conn.execute(
            "INSERT INTO experimental_paper_sessions "
            "(deployment_id,session,account_id,profile_digest,passed,evidence_json) "
            "VALUES (?,?,?,?,1,'{}')",
            (dep.id, last.isoformat(), ACCOUNT_ID, PROFILE_DIGEST),
        )
        last = cal.previous_session(last)
    conn.commit()
    report = experimental_qualification.qualification_report(conn, TENANT, calendar=cal, now=now)
    assert report["passed"]
    return experimental_qualification.record_qualification(
        conn, TENANT, calendar=cal, now=now, expected=report, actor=Actor.AGENT
    )


@pytest.fixture
def ready(tmp_path, monkeypatch, request):
    from algua.contracts.model_types import ModelHandle

    model = (
        ModelHandle(*request.getfixturevalue("trained")[-2:])
        if getattr(request, "param", "legacy") == "model"
        else None
    )
    world = build_world(monkeypatch, tmp_path / "paper", model_handle=model)
    key, pub = _make_key(tmp_path)
    anchor = _anchor(tmp_path, "owner", pub, namespaces="algua-go-live")
    monkeypatch.setattr(live_gate, "ALLOWED_SIGNERS_PATH", anchor)
    monkeypatch.setenv("ALGUA_BARS_REFRESH_PROVIDER_LIVE", "synthetic")
    monkeypatch.setattr(world.broker, "clock", lambda: datetime.now(UTC).isoformat())
    monkeypatch.setattr(world.broker, "account_activities", lambda after=None: [], raising=False)
    monkeypatch.setattr(
        world.broker, "get_order_by_client_order_id", lambda coid: None, raising=False
    )
    monkeypatch.setattr(
        world.broker,
        "snapshot",
        lambda symbols: SimpleNamespace(
            equity=world.broker.equity, qtys={}, market_values={}, prices={}
        ),
        raising=False,
    )
    monkeypatch.setattr(capped_auth, "build_broker", lambda kind: world.broker)
    monkeypatch.setattr(experimental_handoff, "build_broker", lambda kind: world.broker)
    monkeypatch.setattr(
        "algua.execution.paper_exit_drain.build_paper_drain_broker", lambda: world.broker
    )
    counter = 0

    def sign(payload):
        nonlocal counter
        counter += 1
        folder = tmp_path / f"sign-{counter}"
        folder.mkdir()
        return _sign(key, payload, folder, namespace="algua-go-live")

    try:
        with world.conn() as conn:
            _qualify(conn)
            policy = DrawdownPolicy("20000", permitted_symbols=tuple(GATE))
            challenge = signed_change(
                conn, world.broker, "live", purpose="configure", policy=policy, signature=None
            )
            signed_change(
                conn,
                world.broker,
                "live",
                purpose="configure",
                policy=policy,
                signature=sign(challenge["challenge"]),
            )
            assert experimental_handoff.handoff(conn, TENANT)["handoff_complete"]
            yield world, conn, sign, anchor
    finally:
        teardown_world(world.data_dir)


def _activate(conn, sign, capital="10000"):
    challenge = capped_auth.authorize(
        conn, TENANT, capital=capital, actor=Actor.HUMAN, signature=None
    )
    signature = sign(challenge["challenge"])
    result = capped_auth.authorize(
        conn, TENANT, capital=capital, actor=Actor.HUMAN, signature=signature
    )
    assert result["activated"]
    return verify_live_authorization(
        conn, SqliteStrategyRepository(conn), TENANT, live_gate.ALLOWED_SIGNERS_PATH
    ), signature


def test_signed_activation_binds_frozen_approval_and_legal_atomic_stages(ready):
    world, conn, sign, anchor = ready
    token, _ = _activate(conn, sign)
    repo = SqliteStrategyRepository(conn)
    assert repo.get(TENANT).stage is Stage.LIVE
    assert active(conn, token)
    assert active_allocation(conn, token.strategy_id)["capital"] == 10000
    approval = conn.execute("SELECT * FROM approvals WHERE id=?", (token.approval_id,)).fetchone()
    assert approval["approved_by"] == "owner"
    assert approval["code_hash"] == world.deployment().code_hash
    rows = conn.execute(
        "SELECT from_stage,to_stage,actor FROM stage_transitions "
        "WHERE strategy_id=? ORDER BY id DESC LIMIT 2",
        (token.strategy_id,),
    ).fetchall()
    assert [tuple(r) for r in rows] == [
        ("forward_tested", "live", "human"),
        ("paper", "forward_tested", "human"),
    ]
    assert conn.execute("SELECT COUNT(*) FROM forward_gate_evaluations").fetchone()[0] == 0


def test_agent_preview_and_bare_human_never_activate(ready):
    _, conn, _, _ = ready
    args = ["live", "activate-experimental", TENANT, "--capital", "10000"]
    for suffix in ([], ["--actor", "human"]):
        result = CliRunner().invoke(app, args + suffix)
        assert result.exit_code == 0, result.stdout
        assert json.loads(result.stdout)["ok"]
        assert SqliteStrategyRepository(conn).get(TENANT).stage is Stage.PAPER
        assert conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0


@pytest.mark.parametrize("change", ["capital", "provider", "account", "expired", "forged"])
def test_signature_refuses_changed_context_or_invalid_proof(ready, monkeypatch, change):
    world, conn, sign, anchor = ready
    challenge = capped_auth.authorize(
        conn, TENANT, capital="10000", actor=Actor.HUMAN, signature=None
    )
    signature = sign(challenge["challenge"])
    capital = "9999" if change == "capital" else "10000"
    if change == "provider":
        monkeypatch.setenv("ALGUA_BARS_REFRESH_PROVIDER_LIVE", "other")
    if change == "account":
        from dataclasses import replace

        original = world.broker.account()
        monkeypatch.setattr(world.broker, "account", lambda: replace(original, account_id="other"))
    if change == "expired":
        conn.execute("UPDATE capped_live_challenges SET expires_at='2000-01-01'")
        conn.commit()
    if change == "forged":
        signature = b"forged"
    with pytest.raises((ValueError, live_gate.SignatureError)):
        capped_auth.authorize(conn, TENANT, capital=capital, actor=Actor.HUMAN, signature=signature)
    assert SqliteStrategyRepository(conn).get(TENANT).stage is Stage.PAPER
    assert conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0


def test_resize_replay_revocation_and_unsigned_increase(ready):
    _, conn, sign, anchor = ready
    first, signature = _activate(conn, sign)
    with pytest.raises(ValueError):
        capped_auth.authorize(conn, TENANT, capital="10000", actor=Actor.HUMAN, signature=signature)
    second, _ = _activate(conn, sign, capital="12000")
    assert not active(conn, first) and active(conn, second)
    from algua.registry.capped_allocation import require_ordinary_allocation

    repo = SqliteStrategyRepository(conn)
    require_ordinary_allocation(conn, repo.get(TENANT).id, "11000")
    with pytest.raises(ValueError, match="signed"):
        require_ordinary_allocation(conn, repo.get(TENANT).id, "12001")
    with conn:
        revoke(conn, second.strategy_id, "test")
    assert not active(conn, second)
    with pytest.raises(live_gate.LiveAuthorizationError):
        verify_live_authorization(conn, repo, TENANT, anchor)


def test_atomic_failure_rolls_back_nonce_approval_stages_and_allocation(ready, monkeypatch):
    _, conn, sign, _ = ready
    challenge = capped_auth.authorize(
        conn, TENANT, capital="10000", actor=Actor.HUMAN, signature=None
    )
    signature = sign(challenge["challenge"])
    original = SqliteStrategyRepository._apply_transition_locked

    def fail_live(self, *args, **kwargs):
        if kwargs["to"] is Stage.LIVE:
            raise ValueError("synthetic failure at second edge")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(SqliteStrategyRepository, "_apply_transition_locked", fail_live)
    with pytest.raises(ValueError, match="second edge"):
        capped_auth.authorize(conn, TENANT, capital="10000", actor=Actor.HUMAN, signature=signature)
    assert SqliteStrategyRepository(conn).get(TENANT).stage is Stage.PAPER
    assert conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0
    assert conn.execute("SELECT consumed_at FROM capped_live_challenges").fetchone()[0] is None


def test_runtime_refuses_qualification_source_or_provider_drift(ready, monkeypatch):
    _, conn, sign, anchor = ready
    token, _ = _activate(conn, sign)
    monkeypatch.setenv("ALGUA_BARS_REFRESH_PROVIDER_LIVE", "other")
    assert not active(conn, token)
    with pytest.raises(live_gate.LiveAuthorizationError):
        verify_live_authorization(conn, SqliteStrategyRepository(conn), TENANT, anchor)
    monkeypatch.setenv("ALGUA_BARS_REFRESH_PROVIDER_LIVE", "synthetic")
    conn.execute("UPDATE holdout_evaluations SET reused=1")
    conn.commit()
    with pytest.raises(live_gate.LiveAuthorizationError, match="source evidence changed"):
        verify_live_authorization(conn, SqliteStrategyRepository(conn), TENANT, anchor)


@pytest.mark.parametrize("ready", ["legacy", "model"], indirect=True)
def test_frozen_live_uses_real_child_after_checkout_removal(ready):
    from algua.backtest._sample import SyntheticProvider
    from algua.cli.frozen_live import run_frozen_live
    from algua.data.store import DataStore
    from algua.execution.drawdown_cycle import manage_cycle
    from algua.primitives.timeparse import utc
    from tests._frozen_paper_world import CHECKOUT_MODULE, window

    world, conn, sign, _ = ready
    token, _ = _activate(conn, sign)
    CHECKOUT_MODULE.unlink()
    start, end = window()
    provider = SyntheticProvider()
    snap = DataStore(world.data_dir).ingest_bars(
        provider="synthetic",
        symbols=GATE,
        start=start,
        end=end,
        as_of=datetime.now(UTC).isoformat(),
        source="synthetic test",
        frame=provider.get_bars(GATE, utc(start), utc(end), "1d").reset_index(),
    )
    assert manage_cycle(conn, world.broker, "live")["ready"]
    result = run_frozen_live(
        conn,
        TENANT,
        token,
        world.broker,
        provider,
        0.2,
        start=start,
        end=end,
        snapshot_id=snap.snapshot_id,
    )
    assert result["ok"], result
    assert world.launches and result["submitted"]
    tick = conn.execute("SELECT * FROM tick_snapshots WHERE lane='live'").fetchone()
    assert tick["deployment_id"] == token.deployment_id and tick["frozen_invocation_id"]
    assert not any(e[0] == "cancel_open_orders" for e in world.broker.effects)


def test_handoff_refuses_unpublished_fill_after_cancel(ready, monkeypatch):
    from algua.execution.live_ledger import (
        backfill_paper_venue_broker_order_id,
        record_paper_venue_order,
    )

    world, conn, _, _ = ready
    record_paper_venue_order(
        conn,
        TENANT,
        "AAA",
        "buy",
        None,
        "pending-paper",
        strategy_id=SqliteStrategyRepository(conn).get(TENANT).id,
    )
    backfill_paper_venue_broker_order_id(conn, "pending-paper", "paper-order")
    order = {"id": "paper-order", "client_order_id": "pending-paper", "filled_qty": "1"}
    opened = [order]
    monkeypatch.setattr(world.broker, "list_open_orders", lambda: list(opened))
    monkeypatch.setattr(world.broker, "cancel_order", lambda oid: opened.clear())
    monkeypatch.setattr(world.broker, "get_order_by_client_order_id", lambda coid: order)
    with pytest.raises(Exception, match="publishes|published"):
        experimental_handoff.handoff(conn, TENANT)


def test_capped_authority_is_immutable_except_one_way_revocation(ready):
    import sqlite3

    _, conn, sign, _ = ready
    token, _ = _activate(conn, sign)
    conn.execute("PRAGMA recursive_triggers=OFF")  # raw SQLite handles also retain history
    for sql in (
        "UPDATE capped_live_authorizations SET capital='99999'",
        "INSERT OR REPLACE INTO capped_live_authorizations "
        "SELECT * FROM capped_live_authorizations",
        "DELETE FROM capped_live_authorizations",
    ):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(sql)
        conn.rollback()
    with conn:
        revoke(conn, token.strategy_id, "test")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE capped_live_authorizations SET revoked_at=NULL")
    conn.rollback()


def test_handoff_is_idempotent_and_preserves_qualification_without_a_new_tick(ready):
    from algua.risk import kill_switch

    _, conn, _, _ = ready
    before = conn.execute("SELECT * FROM experimental_qualifications").fetchall()
    assert experimental_handoff.handoff(conn, TENANT)["handoff_complete"]
    assert experimental_handoff.handoff(conn, TENANT)["handoff_complete"]
    assert not kill_switch.is_tripped(conn, TENANT)
    assert conn.execute("SELECT COUNT(*) FROM tick_snapshots").fetchone()[0] == 0
    assert conn.execute("SELECT * FROM experimental_qualifications").fetchall() == before


def test_signed_capital_is_bounded_by_shared_live_ceiling_not_paper_allocations(ready):
    from tests._frozen_paper_world import SIBLING

    _, conn, sign, _ = ready
    # The world already has a $10k PAPER sibling, which does not consume the live budget.
    token, _ = _activate(conn, sign, capital="20000")
    assert active(conn, token)
    conn.execute("UPDATE strategies SET stage='live' WHERE name=?", (SIBLING,))
    conn.commit()
    with pytest.raises(ValueError, match="total live allocation"):
        capped_auth.authorize(conn, TENANT, capital="10000.01", actor=Actor.HUMAN, signature=None)


def test_live_exit_revokes_exact_authority_in_the_stage_transaction(ready):
    _, conn, sign, _ = ready
    token, _ = _activate(conn, sign)
    repo = SqliteStrategyRepository(conn)
    rec = repo.get(TENANT)
    with conn:
        repo._apply_transition_locked(
            rec,
            Stage.DORMANT,
            Actor.AGENT,
            "test bench",
            token.code_hash,
            token.config_hash,
            token.dependency_hash,
            None,
            None,
            datetime.now(UTC).isoformat(),
            revoke_allocation=True,
        )
    assert not active(conn, token)
    assert conn.execute(
        "SELECT revoked_at FROM approvals WHERE id=?", (token.approval_id,)
    ).fetchone()[0]


def test_corrupt_bundle_refuses_live_verification_and_never_imports_checkout(ready):
    from tests._frozen_harness import unseal

    _, conn, sign, anchor = ready
    token, _ = _activate(conn, sign)
    world = ready[0]
    unseal(world.bundle_root)
    path = world.bundle_root / "algua" / "__init__.py"
    path.write_bytes(path.read_bytes() + b"\n# changed\n")
    with pytest.raises(live_gate.LiveAuthorizationError):
        verify_live_authorization(conn, SqliteStrategyRepository(conn), TENANT, anchor)
    assert not world.launches and not world.broker.effects
    assert active(conn, token)  # Cheap check is advisory; only the full verifier grants a tick.


def test_normal_live_cli_routes_frozen_tenant_without_checkout(ready, monkeypatch):
    from algua.backtest._sample import SyntheticProvider
    from algua.cli import layered_runtime, live_cmd
    from algua.data.store import DataStore
    from algua.primitives.timeparse import utc
    from tests._frozen_paper_world import CHECKOUT_MODULE, window

    world, conn, sign, _ = ready
    _activate(conn, sign)
    CHECKOUT_MODULE.unlink()
    start, end = window()
    snap = DataStore(world.data_dir).ingest_bars(
        provider="synthetic",
        symbols=GATE,
        start=start,
        end=end,
        as_of=datetime.now(UTC).isoformat(),
        source="synthetic test",
        frame=SyntheticProvider().get_bars(GATE, utc(start), utc(end), "1d").reset_index(),
    )
    monkeypatch.setattr(live_cmd, "_alpaca_live_broker", lambda auth: world.broker)
    monkeypatch.setattr(live_cmd, "_select_provider", world.select_provider)
    monkeypatch.setattr(layered_runtime, "build_broker", lambda kind: world.broker)
    monkeypatch.setattr(live_cmd, "ALLOWED_SIGNERS_PATH", ready[3])
    result = CliRunner().invoke(
        app, ["live", "run-all", "--snapshot", snap.snapshot_id, "--start", start, "--end", end]
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["strategies"] and payload["strategies"][0]["submitted"], payload
    assert (
        world.launches
        and conn.execute("SELECT COUNT(*) FROM tick_snapshots WHERE lane='live'").fetchone()[0] == 1
    )


def test_unsigned_decrease_cannot_race_a_smaller_allocation_into_an_increase(ready, monkeypatch):
    from algua.cli import live_cmd
    from algua.registry.allocations import allocate_in_lane

    _, conn, sign, _ = ready
    token, _ = _activate(conn, sign)

    def concurrent_decrease():
        allocate_in_lane(conn, token.strategy_id, 5000, "agent", 100000, frozenset({"live"}))
        return 100000

    monkeypatch.setattr(live_cmd, "_live_account_equity", concurrent_decrease)
    result = CliRunner().invoke(app, ["live", "allocate", TENANT, "--capital", "9000"])
    assert result.exit_code == 1, result.stdout
    assert active_allocation(conn, token.strategy_id)["capital"] == 5000


def test_original_paper_window_need_not_keep_growing_after_activation(ready):
    from datetime import timedelta

    from algua.registry.capped_qualification import verified_qualification

    _, conn, sign, _ = ready
    token, _ = _activate(conn, sign)
    repo = SqliteStrategyRepository(conn)
    dep, cal = repo.active_deployment(token.strategy_id), get_calendar()
    last = target_session(datetime.now(UTC), cal)
    for _ in range(6):
        last = cal.next_session(last)
    later = cal.session_close(last) + timedelta(minutes=1)
    assert (
        verified_qualification(
            conn, dep, token.qualification_id, calendar=cal, at=later, require_fresh=False
        )["id"]
        == token.qualification_id
    )
    with pytest.raises(ValueError, match="stale"):
        verified_qualification(
            conn, dep, token.qualification_id, calendar=cal, at=later, require_fresh=True
        )


def test_inflight_resize_cannot_supersede_concurrent_revocation(ready, monkeypatch):
    _, conn, sign, _ = ready
    prior, _ = _activate(conn, sign)
    challenge = capped_auth.authorize(
        conn, TENANT, capital='12000', actor=Actor.HUMAN, signature=None)
    signature = sign(challenge['challenge'])
    original = capped_auth.commit_activation

    def stop_before_commit(*args, **kwargs):
        with conn:
            revoke(conn, prior.strategy_id, 'concurrent stop')
        return original(*args, **kwargs)

    monkeypatch.setattr(capped_auth, 'commit_activation', stop_before_commit)
    with pytest.raises(ValueError, match='prior.*authority'):
        capped_auth.authorize(conn, TENANT, capital='12000', actor=Actor.HUMAN,
                              signature=signature)
    assert conn.execute('SELECT COUNT(*) FROM capped_live_authorizations').fetchone()[0] == 1
    assert conn.execute('SELECT consumed_at FROM capped_live_challenges WHERE nonce=?',
                        (challenge['nonce'],)).fetchone()[0] is None
    assert not active(conn, prior)


def test_allocation_decrease_during_tick_aborts_stale_sizing(ready, monkeypatch):
    from algua.backtest._sample import SyntheticProvider
    from algua.cli import frozen_live
    from algua.data.store import DataStore
    from algua.execution.drawdown_cycle import manage_cycle
    from algua.primitives.timeparse import utc
    from algua.registry.allocations import allocate_in_lane
    from tests._frozen_paper_world import window

    world, conn, sign, _ = ready
    token, _ = _activate(conn, sign)
    start, end = window()
    provider = SyntheticProvider()
    snap = DataStore(world.data_dir).ingest_bars(
        provider='synthetic', symbols=GATE, start=start, end=end,
        as_of=datetime.now(UTC).isoformat(), source='synthetic test',
        frame=provider.get_bars(GATE, utc(start), utc(end), '1d').reset_index())
    assert manage_cycle(conn, world.broker, 'live')['ready']
    original = frozen_live.build_frozen_planner

    def decrease(*args, **kwargs):
        port = original(*args, **kwargs)
        allocate_in_lane(conn, token.strategy_id, 1000, 'agent', 100000, frozenset({'live'}))
        return port

    monkeypatch.setattr(frozen_live, 'build_frozen_planner', decrease)
    result = frozen_live.run_frozen_live(
        conn, TENANT, token, world.broker, provider, .2,
        start=start, end=end, snapshot_id=snap.snapshot_id)
    assert result['ok'] is False, result
    assert not world.broker.submitted_for(TENANT)
