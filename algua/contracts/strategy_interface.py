"""Closed strategy decision-interface vocabulary."""

from __future__ import annotations

from typing import Literal, TypeGuard

StrategyInterface = Literal["legacy", "context_v1"]
LEGACY_INTERFACE: Literal["legacy"] = "legacy"
CONTEXT_INTERFACE_V1: Literal["context_v1"] = "context_v1"
SUPPORTED_STRATEGY_INTERFACES = frozenset({LEGACY_INTERFACE, CONTEXT_INTERFACE_V1})


def is_supported_strategy_interface(value: object) -> TypeGuard[StrategyInterface]:
    return value in SUPPORTED_STRATEGY_INTERFACES


def uses_context_interface(value: object) -> TypeGuard[Literal["context_v1"]]:
    return value == CONTEXT_INTERFACE_V1
