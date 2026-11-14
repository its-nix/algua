import pytest

from algua.strategies.loader import load_strategy
from tests._context_strategies import context_strategies  # noqa: F401

pytestmark = [pytest.mark.serial, pytest.mark.usefixtures("context_strategies")]


def test_loads_fundamentals_example():
    ls = load_strategy("fundamentals_earnings_tilt")
    assert ls.config.needs_fundamentals is True
    assert ls.fundamentals_signal_fn is not None
    assert ls.signal_fn is None


def test_loads_plain_example_unchanged():
    ls = load_strategy("cross_sectional_momentum")
    assert ls.config.needs_fundamentals is False
    assert ls.signal_fn is not None
    assert ls.fundamentals_signal_fn is None
