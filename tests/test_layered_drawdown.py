from decimal import Decimal as D

import pytest

from algua.risk.layered import DrawdownPolicy, evaluate


def test_inclusive_layers_and_no_automatic_restoration():
    p = DrawdownPolicy("1000")
    assert evaluate(p, D("900.01"), D("1000"), 0).severity == 0
    assert evaluate(p, D("900"), D("1000"), 0).fraction == D(".5")
    assert evaluate(p, D("800"), D("1000"), 0).severity == 2
    assert evaluate(p, D("1100"), D("1000"), 1).fraction == D(".5")
    assert evaluate(p, D("1100"), D("1000"), 2).fraction == 0


@pytest.mark.parametrize(
    "changes",
    [
        dict(reduce_at=".2", halt_at=".1"),
        dict(reduced_fraction="1"),
        dict(normal_capital="NaN"),
        dict(halt_at="Infinity"),
        dict(reduce_at=True),
    ],
)
def test_invalid_policy_refuses(changes):
    with pytest.raises(ValueError):
        DrawdownPolicy(**({"normal_capital": "1000"} | changes))


def test_deposits_do_not_erase_fixed_capital_losses_and_flow_ambiguity_refuses():
    from datetime import UTC, datetime

    from algua.execution.drawdown_flows import cash_flows

    state = {"baseline_at": "2026-11-02T10:00:00+00:00", "baseline_seen": {}}
    row = {
        "id": "deposit",
        "activity_type": "CSD",
        "net_amount": "10000",
        "transaction_time": "2026-11-03T10:00:00+00:00",
    }
    now = datetime(2026, 11, 3, 15, tzinfo=UTC)
    flow, _, _ = cash_flows([row], state, before_read=now, prior_close=now)
    nav = D("1000") + D("10900") - D("1000") - flow
    assert evaluate(DrawdownPolicy("1000"), nav, D("1000"), 0).severity == 1
    row.pop("transaction_time")
    row["date"] = "2026-11-03"
    with pytest.raises(ValueError, match="exact timezone"):
        cash_flows([row], state, before_read=now, prior_close=now)


def test_identical_duplicate_cash_activity_is_counted_once():
    from datetime import UTC, datetime

    from algua.execution.drawdown_flows import cash_flows

    row = {
        "id": "withdraw",
        "activity_type": "CSW",
        "net_amount": "-100",
        "transaction_time": "2026-11-03T10:00:00+00:00",
    }
    now = datetime(2026, 11, 3, 15, tzinfo=UTC)
    state = {"baseline_at": "2026-11-02T10:00:00+00:00", "baseline_seen": {}}
    flow, _, _ = cash_flows([row, row], state, before_read=now, prior_close=now)
    assert flow == -100
    assert evaluate(DrawdownPolicy("1000"), D("700") - flow, D("1000"), 0).severity == 2
