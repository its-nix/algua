from datetime import UTC, datetime

import pandas as pd

from algua.portfolio.allocator import PortfolioConstraints, allocate_targets
from algua.registry.allocations import portfolio_risk_estimates
from algua.registry.db import connect, migrate
from algua.registry.store import SqliteStrategyRepository


def test_persisted_risk_is_identity_bound_known_at_and_not_selected_by_performance(tmp_path,
                                                                               monkeypatch):
    with connect(tmp_path / "disposable.db") as conn:
        migrate(conn)
        repo = SqliteStrategyRepository(conn)

        def record(name, vol, *, created="2024-01-04T00:00:00+00:00", end="2024-01-03",
                   code="code", observations=63, sharpe=1.0):
            monkeypatch.setattr("algua.registry.store.runs._now", lambda: created)
            return repo.record_run(
                "walk_forward", name,
                provenance={"code_hash": code, "config_hash": "config", "period_end": end},
                metrics={"ann_vol_oos": vol, "n_obs_oos": observations, "sharpe_oos": sharpe},
            )

        a_id = record("a", 0.2, sharpe=99.0)
        b_id = record("b", 0.4, sharpe=-3.0)
        record("b", 0.01, created="2024-01-08T00:00:00+00:00")  # not yet persisted
        record("b", 0.01, end="2024-01-08")  # future sample with lying creation timestamp
        record("b", 0.01, code="other")  # another artifact
        record("b", 0.01, observations=2)  # underpowered estimate, not a risk input
        now = datetime(2024, 1, 5, tzinfo=UTC)
        estimates = portfolio_risk_estimates(
            repo, {"a": ("code", "config"), "b": ("code", "config")}, as_of=now,
        )
        assert [r.source for r in estimates["a"]] == [f"run:{a_id}"]
        assert [r.source for r in estimates["b"]] == [f"run:{b_id}"]
        result = allocate_targets(
            {"a": pd.Series({"AAA": 1.0}), "b": pd.Series({"BBB": 1.0})},
            {"a": 0.5, "b": 0.5}, PortfolioConstraints(1, 1, None),
            as_of=now, risk_estimates=estimates,
        )
        pd.testing.assert_series_equal(result, pd.Series({"AAA": 0.5, "BBB": 0.25}))
