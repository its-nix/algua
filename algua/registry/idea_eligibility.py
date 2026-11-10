"""Current platform eligibility shared by admission, menus and atomic claims."""
from __future__ import annotations

from algua.contracts.idea import DataCapability, Horizon, Idea, IdeaStatus, Market
from algua.data.capabilities import (
    supported_capabilities,
    supported_horizons,
    supported_markets,
)
from algua.research.ideas import classify_idea


def platform_eligibility(caps: list[DataCapability], *, market: Market | None,
                         horizon: Horizon | None) -> tuple[IdeaStatus, str | None]:
    return classify_idea(caps, supported_capabilities(), market=market,
                         supported_markets=supported_markets(), horizon=horizon,
                         supported_horizons=supported_horizons())


def idea_eligibility(idea: Idea) -> tuple[IdeaStatus, str | None]:
    return platform_eligibility(idea.required_data, market=idea.market, horizon=idea.horizon)
