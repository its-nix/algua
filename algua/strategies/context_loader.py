"""Bind the authored ``score(context)`` interface without growing the legacy loader."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from types import ModuleType

from algua.contracts.model_types import ModelHandle
from algua.contracts.strategy_interface import CONTEXT_INTERFACE_V1
from algua.portfolio.construction import ConstructFn
from algua.portfolio.overlays import OverlayFn
from algua.strategies.base import LoadedStrategy, StrategyConfig


def bind_context_strategy(
    module: ModuleType,
    config: StrategyConfig,
    construct_fn: ConstructFn,
    overlay_fns: tuple[OverlayFn, ...],
    resolve_model: Callable[[], ModelHandle] | None,
) -> LoadedStrategy:
    """Validate the exclusive context entry point and bind its pinned dependencies."""
    if hasattr(module, "signal"):
        raise ValueError("context_v1 must expose only score(context), not a second signal API")
    if getattr(module, "signal_panel", None) is not None:
        raise ValueError(
            "signal_panel is not supported with context_v1; the canonical context loop is required"
        )
    score_fn = module.score
    if not callable(score_fn) or len(inspect.signature(score_fn).parameters) != 1:
        raise ValueError("context_v1 requires score(context)")
    handle = resolve_model() if resolve_model is not None else None
    return LoadedStrategy(
        config=config,
        strategy_interface=CONTEXT_INTERFACE_V1,
        score_fn=score_fn,
        model_handle=handle,
        construct_fn=construct_fn,
        overlay_fns=overlay_fns,
    )
