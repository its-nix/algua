"""Frozen live tick composition; the supervisor retains every broker, risk and ledger effect."""

from __future__ import annotations

from dataclasses import replace
from functools import partial

from algua.cli._common import SYSTEMIC_SETUP_EXCEPTIONS, StrategySetupError, breach_payload
from algua.cli.frozen_planner import build_frozen_planner
from algua.config.settings import get_settings
from algua.contracts.capped_live import CappedLiveAuthorization
from algua.contracts.types import OrderIntent
from algua.data.store import DataStore
from algua.execution import drawdown_guard
from algua.execution.flatten import flatten_strategy
from algua.execution.live_ledger import (
    LedgerKind,
    backfill_broker_order_id,
    believed_positions,
    fill_cursor,
    ingest_activities,
    record_live_order,
)
from algua.execution.live_sizing import LiveSizingError, build_live_sizing_snapshot
from algua.execution.order_state import (
    client_order_id,
    get_nav_peak,
    record_tick_snapshot,
    update_nav_peak,
)
from algua.execution.tick_clock import tick_clock
from algua.execution.venue_sync import scoped_live_cancel
from algua.live.frozen_dispatch import FrozenTenantFailure
from algua.live.live_loop import (
    SubmittedOrder,
    TickHalted,
    TickHooks,
    planner_context_for_deployment,
    run_tick,
)
from algua.primitives.timeparse import utc
from algua.registry.allocations import active_allocation
from algua.registry.capped_active import active
from algua.registry.capped_context import frozen_tenant, provider_policy
from algua.registry.store.frozen_evidence import record_frozen_invocation
from algua.risk import global_halt, kill_switch
from algua.risk.breach import trip_for_breach
from algua.risk.limits import RiskBreach


def frozen_views(conn, verified) -> dict:
    return {
        name: frozen_tenant(conn, name).view
        for name, auth in verified
        if isinstance(auth, CappedLiveAuthorization)
    }


def run_frozen_live(
    conn,
    name,
    authorization,
    broker,
    provider,
    max_drawdown,
    *,
    start,
    end,
    reserve_buy=None,
    cancel=None,
    snapshot_id=None,
) -> dict | None:
    if not isinstance(authorization, CappedLiveAuthorization):
        return None
    try:
        tenant = frozen_tenant(conn, name)
        if (
            tenant.rec.id != authorization.strategy_id
            or tenant.deployment_id != authorization.deployment_id
            or not active(conn, authorization)
        ):
            raise ValueError("frozen live authority no longer matches the tenant")
        if not snapshot_id:
            raise ValueError("frozen live requires the exact bars snapshot")
        store = DataStore(get_settings().data_dir)
        snapshot = store.get_snapshot(snapshot_id)
        if snapshot.provider != provider_policy()["provider"]:
            raise ValueError("live snapshot provider differs from the approved provider")
        store.verify_snapshot(snapshot)
        alloc = active_allocation(conn, tenant.rec.id)
        if alloc is None or float(alloc["capital"]) > float(authorization.capital):
            raise ValueError("live allocation is missing or exceeds signed capital")
        drawdown_guard.require_cycle(conn, broker, "live")
        if broker.account().account_id != authorization.account_id:
            raise ValueError("live broker account differs from the signed account")
        bounds = utc(start), utc(end)
        port = build_frozen_planner(
            tenant,
            snapshot_id,
            bounds,
            data_dir=get_settings().data_dir,
            record=partial(record_frozen_invocation, conn),
        )
        assert port is not None
        context = planner_context_for_deployment(tenant.deployment, get_settings().exchange)
        assert context is not None
        if context.protocol_version == 2:
            context = replace(context, bars_snapshot_id=snapshot_id)
        fresh: set[str] = set()

        def before(intent: OrderIntent, coid: str | None) -> None:
            if coid is None:
                raise ValueError("frozen live order requires a durable client order id")
            exists = conn.execute(
                "SELECT 1 FROM live_orders WHERE client_order_id=?", (coid,)
            ).fetchone()
            record_live_order(conn, name, intent.symbol, intent.side.value, None, coid)
            if exists is None:
                fresh.add(coid)

        def submitted(record: SubmittedOrder) -> None:
            backfill_broker_order_id(conn, record.client_order_id, record.order_id)
            fresh.discard(record.client_order_id)

        def noop(intent: OrderIntent, coid: str | None) -> None:
            if coid in fresh:
                with conn:
                    conn.execute(
                        "DELETE FROM live_orders WHERE client_order_id=? "
                        "AND broker_order_id IS NULL",
                        (coid,),
                    )
                fresh.discard(coid)

        def halt() -> bool:
            allocation = active_allocation(conn, tenant.rec.id)
            return (
                kill_switch.is_tripped(conn, name)
                or global_halt.is_engaged(conn)
                or not active(conn, authorization)
                or not drawdown_guard.cycle_active(conn, broker, "live")
                or allocation is None
                or allocation["id"] != alloc["id"]
                or float(allocation["capital"]) > float(authorization.capital)
            )

        hooks = TickHooks(
            client_order_id_for=client_order_id,
            before_submit=before,
            on_submitted=submitted,
            on_noop=noop,
            should_halt=halt,
            cancel=cancel or partial(scoped_live_cancel, conn, broker, name),
            reserve_buy=drawdown_guard.reserve(conn, broker, "live", reserve_buy),
            peak_equity=get_nav_peak(conn, name),
            live_snapshot=lambda bars: drawdown_guard.sizing_snapshot(
                conn,
                broker,
                "live",
                build_live_sizing_snapshot(
                    conn, name, float(alloc["capital"]), bars, list(tenant.view.universe)
                ),
            ),
            live_positions=lambda: believed_positions(conn, name, LedgerKind.LIVE),
            planner_context=context,
            planner=port,
        )
    except SYSTEMIC_SETUP_EXCEPTIONS:
        raise
    except Exception as exc:
        raise StrategySetupError(name, exc) from exc
    try:
        result = run_tick(
            tenant.view, broker, provider, *bounds, hooks=hooks, max_drawdown=max_drawdown
        )
    except TickHalted as exc:
        return breach_payload(str(exc), strategy=name, halted=True)
    except RiskBreach as exc:
        trip_for_breach(conn, name, exc)
        if exc.is_dark_feed:
            global_halt.engage(conn, reason=exc.detail, actor="system")
            return breach_payload(
                exc.detail, strategy=name, halted=True, liquidation_submitted=False
            )
        res = flatten_strategy(
            conn,
            broker,
            name,
            LedgerKind.LIVE,
            lane="live",
            cancel=cancel or partial(scoped_live_cancel, conn, broker, name),
            ingest=lambda: ingest_activities(
                conn,
                broker.account_activities(after=fill_cursor(conn, LedgerKind.LIVE)),
                LedgerKind.LIVE,
            ),
            held=lambda: {s: float(q) for s, q in broker.get_positions().items() if q != 0},
        )
        return breach_payload(
            exc.detail,
            strategy=name,
            kind=exc.kind,
            liquidation_submitted=res.flatten_error is None,
        )
    except LiveSizingError as exc:
        return {"ok": True, "strategy": name, "skipped": str(exc)}
    except FrozenTenantFailure as exc:
        raise StrategySetupError(name, exc) from exc
    if result.peak_equity is not None:
        update_nav_peak(conn, name, result.peak_equity)
        tick_ts, clock_source = tick_clock(broker.clock)
        account = broker.account()
        if account.account_id != authorization.account_id:
            raise ValueError("live account changed during tick")
        record_tick_snapshot(
            conn,
            name,
            tick_ts=tick_ts,
            decision_ts=result.decision_ts.isoformat() if result.decision_ts else None,
            equity=result.equity,
            peak_equity=result.peak_equity,
            positions=result.positions_before,
            n_submitted=len(result.submitted),
            reconcile_ok=result.reconcile_ok,
            lane="live",
            strategy_id=tenant.rec.id,
            code_hash=tenant.identity.code_hash,
            config_hash=tenant.identity.config_hash,
            dependency_hash=tenant.identity.dependency_hash,
            account_id=account.account_id,
            cash=account.cash,
            clock_source=clock_source,
            snapshot_id=snapshot_id,
            deployment_id=tenant.deployment_id,
            frozen_invocation_id=port.final_invocation_id,
        )
    return {
        "ok": True,
        "strategy": name,
        "venue": "live",
        "submitted": result.submitted,
        "decision_ts": result.decision_ts.isoformat() if result.decision_ts else None,
        "reconcile_ok": result.reconcile_ok,
    }
