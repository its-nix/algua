"""Pure resource limits shared by the research ledger and its startup supervisor."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CycleLimits:
    max_hypotheses: int = 3
    max_wall_seconds: int = 2700
    worker_limit: int = 1
    cpu_seconds: int = 2700
    memory_mb: int = 16384
    file_mb: int = 512
    max_cost: float | None = None

    def __post_init__(self) -> None:
        bounds = {"max_hypotheses": 40, "max_wall_seconds": 86400, "worker_limit": 1,
                  "cpu_seconds": 86400, "memory_mb": 65536, "file_mb": 1024}
        for key, ceiling in bounds.items():
            value = getattr(self, key)
            if type(value) is not int or not 1 <= value <= ceiling:
                raise ValueError(f"{key} must be an integer in [1, {ceiling}]")
        if self.max_cost is not None and (
            not math.isfinite(self.max_cost) or self.max_cost < 0
        ):
            raise ValueError("max_cost must be finite and nonnegative")


def duration_seconds(value: str) -> int:
    match = re.fullmatch(r"([1-9][0-9]*)([smh]?)", value)
    if match is None:
        raise ValueError("timeout must be a positive integer with optional s/m/h suffix")
    seconds = int(match[1]) * {"": 1, "s": 1, "m": 60, "h": 3600}[match[2]]
    if seconds > 86400:
        raise ValueError("timeout cannot exceed 24h")
    return seconds

