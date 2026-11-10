# tests/test_data_capabilities.py
from algua.contracts.idea import DataCapability, Horizon
from algua.data.capabilities import supported_capabilities, supported_horizons


def test_decision_horizons_match_the_daily_execution_engine():
    from algua.backtest.engine import _SUPPORTED_CADENCES

    assert _SUPPORTED_CADENCES == {'1d'}
    assert supported_horizons() == frozenset({Horizon.DAILY})


def test_supported_is_ohlcv_only_today():
    supported = supported_capabilities()
    assert supported == frozenset({DataCapability.OHLCV})


def test_alt_data_is_not_supported():
    supported = supported_capabilities()
    assert DataCapability.OHLCV in supported
    assert DataCapability.FORM_13F not in supported
    assert DataCapability.OPTIONS_FLOW not in supported
