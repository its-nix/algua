"""Advisory feasibility of a declared recipe, before any authored strategy executes."""

from __future__ import annotations

from algua.operator.research_history import window_capacity

FIELDS = {"market", "horizon", "required_data", "construction", "feature_lookback", "controls"}
LEG_FIELDS = FIELDS - {"controls"}


def assess_recipe(recipe: object, profile: dict) -> dict:
    if recipe is None:
        return {"status": "unknown", "reasons": ["recipe_not_declared"]}
    if not isinstance(recipe, dict) or set(recipe) != FIELDS:
        raise ValueError("source_recipe:invalid_fields")
    controls = recipe["controls"]
    if not isinstance(controls, list) or not 1 <= len(controls) <= 4:
        raise ValueError("source_recipe:controls_required")
    reasons: list[str] = []
    capacities = []
    for index, leg in enumerate([recipe, *controls]):
        if not isinstance(leg, dict) or set(leg) != (FIELDS if index == 0 else LEG_FIELDS):
            raise ValueError("source_recipe:invalid_leg")
        required = leg["required_data"]
        lookback = leg["feature_lookback"]
        if (
            not isinstance(required, list)
            or not required
            or any(not isinstance(v, str) or not v for v in required)
            or type(lookback) is not int
            or not 0 <= lookback <= 10000
            or any(not isinstance(leg[k], str) for k in ("market", "horizon", "construction"))
        ):
            raise ValueError("source_recipe:invalid_values")
        if leg["market"] != "us_equities" or leg["horizon"] != "daily":
            reasons.append(f"leg:{index}:unsupported_market_or_cadence")
        if set(required) != {"ohlcv"}:
            reasons.append(f"leg:{index}:missing_data")
        allowed = (
            {"top_k_equal_weight"}
            if index == 0
            else {"top_k_equal_weight", "equal_weight_positive"}
        )
        if leg["construction"] not in allowed:
            reasons.append(f"leg:{index}:unsupported_construction")
        capacities.append(lookback)
    # All comparison legs share the same conservative embargo; no incomparable windows.
    common = max(capacities)
    try:
        capacity = window_capacity(
            profile["coverage"]["grid_sessions"],
            lookback=common,
            lag=profile["execution"]["decision_lag_bars"],
            windows=profile["windows"],
            holdout_frac=profile["holdout_frac"],
        )
    except ValueError:
        capacity = [0] * profile["windows"]
    if not all(capacity):
        reasons.append("insufficient_post_warmup_history")
    return {
        "status": "blocked" if reasons else "feasible",
        "reasons": reasons,
        "common_feature_lookback": common,
        "window_capacity": capacity,
        "authority": "none",
        "qualification_eligible": False,
    }
