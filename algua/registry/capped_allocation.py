"""Unsigned legacy commands cannot increase capital on the configured experimental account."""

from algua.contracts.lifecycle import Stage
from algua.registry.allocations import active_allocation
from algua.registry.drawdown_store import account_state, policy_for
from algua.registry.store import SqliteStrategyRepository
from algua.risk.layered import decimal


def require_ordinary_allocation(conn, strategy_id: int, capital) -> None:
    state = account_state(conn, "live")
    if state is None or not policy_for(conn, state).permitted_symbols:
        return
    prior = active_allocation(conn, strategy_id)
    if prior is None or decimal(capital) > decimal(prior["capital"]):
        raise ValueError(
            "experimental live increases require a signed activate-experimental request"
        )


def still_live_allocated(conn, name: str) -> bool:
    """True iff `name` is still Stage.LIVE with an active allocation. Re-read at submit time so a
    mid-cycle `live -> dormant` bench (#247) halts further orders instead of orphaning a position
    run-all would never flatten (#281); broader than dormant (any non-LIVE transition halts)."""
    rec = SqliteStrategyRepository(conn).get(name)
    return rec.stage is Stage.LIVE and active_allocation(conn, rec.id) is not None
