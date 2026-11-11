"""Risk-only live checks reuse a currently verified, allocated strategy's existing authority."""

from algua.contracts.lifecycle import Stage
from algua.execution.broker_factory import BrokerKind, build_broker
from algua.registry import live_gate
from algua.registry.allocations import active_allocation
from algua.registry.store import SqliteStrategyRepository


def live_check_broker(conn, *, verifier=None):
    verifier = verifier or live_gate.verify_live_authorization
    repo = SqliteStrategyRepository(conn)
    for rec in repo.list_strategies(Stage.LIVE):
        if active_allocation(conn, rec.id) is None:
            continue
        try:
            authorization = verifier(
                conn, repo, rec.name, live_gate.ALLOWED_SIGNERS_PATH
            )
        except live_gate.LiveAuthorizationError:
            continue
        return build_broker(BrokerKind.ALPACA_LIVE, authorization)
    return build_broker(BrokerKind.ALPACA_LIVE_DRAIN)
