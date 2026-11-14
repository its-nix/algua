"""Shared types and helpers for the Sharadar sample check (see `algua.data.sharadar_check`)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import pandas as pd

Status = Literal["pass", "fail", "info"]

RTOL = 1e-3


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: Status
    counts: dict[str, int]
    findings: list[dict[str, object]]


@dataclass(frozen=True)
class SampleCheckReport:
    checks: tuple[CheckResult, ...]

    @property
    def passed(self) -> bool:
        return all(c.status != "fail" for c in self.checks)

    def summary(self) -> dict[str, object]:
        """Public-safe projection: no findings, so no vendor values."""
        return {
            "passed": self.passed,
            "checks": [{"name": c.name, "status": c.status, "counts": dict(c.counts)}
                       for c in self.checks],
        }


def result(name: str, failed: bool, counts: dict[str, int],
            findings: list[dict[str, object]]) -> CheckResult:
    return CheckResult(name, "fail" if failed else "pass", counts, findings)


def valid_value(v: object) -> bool:
    return isinstance(v, float | int) and math.isfinite(v) and v > 0


def owners(sep: pd.DataFrame, tickers: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Per SEP row: how many securities' price ranges contain it, and the permaticker when exactly
    one does (NaN otherwise). Both indexed like `sep`."""
    spans = tickers[["ticker", "permaticker", "firstpricedate", "lastpricedate"]]
    m = sep[["ticker", "date"]].reset_index().merge(spans, on="ticker", how="inner")
    m = m[(m["date"] >= m["firstpricedate"]) & (m["date"] <= m["lastpricedate"])]
    n = m.groupby("index").size().reindex(sep.index, fill_value=0)
    single = m[m["index"].isin(n[n == 1].index)].set_index("index")["permaticker"]
    return n, single.reindex(sep.index)
