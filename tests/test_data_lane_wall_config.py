"""Config-level guards that every decision/execution lane is barred from algua.data.

Restored from the former test_fundamentals_wall / test_news_wall after the hindsight accessor (and
its dedicated contract) was removed; the AST defense lives in tests/test_data_wall.py (issue #277).
"""
import pathlib
import tomllib

REPO = pathlib.Path(__file__).resolve().parents[1]


def _contracts():
    data = tomllib.loads((REPO / "pyproject.toml").read_text())
    return data["tool"]["importlinter"]["contracts"]


def test_strategies_barred_from_data_lane():
    cs = _contracts()
    assert any(
        c.get("source_modules") == ["algua.strategies"]
        and "algua.data" in c.get("forbidden_modules", [])
        for c in cs
    ), "missing: algua.strategies forbidden from algua.data"


def test_contracts_barred_from_data_lane():
    cs = _contracts()
    contracts_rule = next(c for c in cs if c.get("source_modules") == ["algua.contracts"])
    assert "algua.data" in contracts_rule["forbidden_modules"]


def test_live_execution_barred_from_data_lane():
    cs = _contracts()
    assert any(
        set(c.get("source_modules", [])) == {"algua.live", "algua.execution"}
        and c.get("forbidden_modules") == ["algua.data"]
        for c in cs
    ), "missing: algua.live/algua.execution forbidden from algua.data"


def test_news_full_history_read_not_on_a_decision_lane_module():
    # The only full-history news read surface is store.read_news (in algua.data, walled from all
    # decision/execution lanes). Assert no news read leaked onto contracts.types (a base layer).
    import algua.contracts.types as t

    assert not hasattr(t, "read_news") and not hasattr(t, "query_news")


def test_all_decision_lanes_barred_from_data_lane_in_config():
    cs = _contracts()
    barred = {
        m
        for c in cs
        if "algua.data" in c.get("forbidden_modules", [])
        for m in c.get("source_modules", [])
    }
    for lane in [
        "algua.backtest", "algua.features", "algua.strategies",
        "algua.contracts", "algua.live", "algua.execution",
    ]:
        assert lane in barred, f"{lane} is not forbidden from algua.data by any contract"
