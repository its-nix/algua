import pytest

from algua.risk.layered import DrawdownPolicy


def test_explicit_instrument_list_is_normalized_and_empty_is_not_live_ready():
    policy = DrawdownPolicy("1000", permitted_symbols=["SPY", "IEF"])
    assert policy.permitted_symbols == ("SPY", "IEF")
    assert policy.to_dict()["permitted_symbols"] == ["SPY", "IEF"]
    assert DrawdownPolicy("1000").permitted_symbols == ()


@pytest.mark.parametrize("symbols", [["SPY", "SPY"], [""], ["spy"], ["SPY/PUT"], True, "SPY"])
def test_bad_instrument_list_refuses(symbols):
    with pytest.raises(ValueError):
        DrawdownPolicy("1000", permitted_symbols=symbols)


def test_buy_reservation_refuses_unapproved_symbol_before_shared_cash(monkeypatch):
    from decimal import Decimal
    from types import SimpleNamespace

    from algua.execution import drawdown_guard

    policy = DrawdownPolicy("1000", permitted_symbols=["SPY"])
    monkeypatch.setattr(drawdown_guard, "account_state", lambda *args: {})
    monkeypatch.setattr(drawdown_guard, "cycle_active", lambda *args: True)
    monkeypatch.setattr(drawdown_guard, "policy_for", lambda *args: policy)
    broker = SimpleNamespace(_drawdown_cycle={"available": Decimal("1000")})
    calls = []
    checked = drawdown_guard.reserve(
        None, broker, "live", lambda s, amount: calls.append(s) or amount
    )
    assert checked("UNAPPROVED", 500) == 0 and not calls
    assert broker._drawdown_cycle["available"] == 1000
    assert checked("SPY", 500) == 500 and calls == ["SPY"]
