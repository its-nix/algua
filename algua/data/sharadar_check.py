"""Adversarial sample check for Sharadar data against the agreed PIT standard (spec §4.6, §5.A).

Pure functions over the frames `algua.data.importers.sharadar_tables` returns. Each check yields a
`CheckResult`; `"fail"` stops the data project, `"info"` informs the importer plan and never gates.
Findings may carry vendor values (dates, prices), so they belong only in the owner's PRIVATE report;
`SampleCheckReport.summary()` is the public-safe projection (names, statuses, counts).
Spec: docs/superpowers/specs/2026-11-12-pit-data-pipeline-design.md.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from algua.data.corpactions import CorporateAction, Dividend, Split, check_adj_close_consistent

Status = Literal["pass", "fail", "info"]

BANKRUPTCY_ACTIONS = frozenset({"bankruptcyliquidation"})
ACQUISITION_ACTIONS = frozenset({"acquisitionby", "mergerto"})
OTHER_DELIST_ACTIONS = frozenset({"delisted", "regulatorydelisting", "voluntarydelisting"})
TERMINAL_WINDOW_DAYS = 30
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


def _result(name: str, failed: bool, counts: dict[str, int],
            findings: list[dict[str, object]]) -> CheckResult:
    return CheckResult(name, "fail" if failed else "pass", counts, findings)


def check_sample_coverage(sep: pd.DataFrame, actions: pd.DataFrame,
                          tickers: pd.DataFrame) -> CheckResult:
    """The sample must contain every adversarial case, so an easy sample cannot pass."""
    kinds = actions["action"]
    counts = {
        "split": int((kinds == "split").sum()),
        "dividend": int((kinds == "dividend").sum()),
        "bankruptcy": int(kinds.isin(BANKRUPTCY_ACTIONS).sum()),
        "acquisition": int((kinds.isin(ACQUISITION_ACTIONS)
                            & actions["contraticker"].notna()).sum()),
        "reused_ticker": int((tickers.groupby("ticker")["permaticker"].nunique() >= 2).sum()),
    }
    findings: list[dict[str, object]] = [{"missing": k} for k, n in counts.items() if n == 0]
    return _result("sample_coverage", bool(findings), counts, findings)


def check_identity(sep: pd.DataFrame, tickers: pd.DataFrame) -> CheckResult:
    """Securities sharing a ticker must have disjoint price ranges, and every SEP row must belong
    to exactly one security by those ranges."""
    findings: list[dict[str, object]] = []
    overlaps = 0
    for ticker, group in tickers.groupby("ticker"):
        spans = group.sort_values("firstpricedate")[
            ["permaticker", "firstpricedate", "lastpricedate"]].to_numpy()
        for (pa, _, la), (pb, fb, _) in zip(spans, spans[1:], strict=False):
            if pd.isna(la) or pd.isna(fb) or fb <= la:
                overlaps += 1
                findings.append({"ticker": ticker, "overlap": [int(pa), int(pb)]})
    unassigned = 0
    for row in sep[["ticker", "date"]].itertuples(index=False):
        owners = tickers[(tickers["ticker"] == row.ticker)
                         & (tickers["firstpricedate"] <= row.date)
                         & (tickers["lastpricedate"] >= row.date)]
        if len(owners) != 1:
            unassigned += 1
            findings.append({"ticker": row.ticker, "date": str(row.date.date()),
                             "owners": len(owners)})
    counts = {
        "permatickers": int(tickers["permaticker"].nunique()),
        "reused_tickers": int((tickers.groupby("ticker")["permaticker"].nunique() >= 2).sum()),
        "overlaps": overlaps,
        "unassigned_rows": unassigned,
    }
    return _result("identity", bool(overlaps or unassigned), counts, findings)


def _split_factor(dates: pd.Series, splits: pd.DataFrame, invert: bool) -> np.ndarray:
    factor = np.ones(len(dates))
    for split in splits.itertuples(index=False):
        ratio = 1.0 / split.value if invert else split.value
        factor = np.where((dates < split.date).to_numpy(), factor * ratio, factor)
    return factor


def _mismatches(group: pd.DataFrame, splits: pd.DataFrame, invert: bool) -> np.ndarray:
    expected = group["close"].to_numpy() * _split_factor(group["date"], splits, invert)
    unadj = group["closeunadj"].to_numpy()
    return np.abs(expected - unadj) > RTOL * np.abs(unadj)


def check_raw_units(sep: pd.DataFrame, actions: pd.DataFrame) -> CheckResult:
    """`close` is split-adjusted: close × Π(ratio of later splits) must equal `closeunadj`."""
    splits_all = actions[actions["action"] == "split"]
    findings: list[dict[str, object]] = []
    mismatched = 0
    with_splits = 0
    for ticker, group in sep.groupby("ticker"):
        splits = splits_all[splits_all["ticker"] == ticker]
        with_splits += int(not splits.empty)
        bad = _mismatches(group, splits, invert=False)
        if not bad.any():
            continue
        mismatched += int(bad.sum())
        finding: dict[str, object] = {
            "ticker": ticker,
            "dates": [str(d.date()) for d in group["date"][bad]][:10],
        }
        if not splits.empty and not _mismatches(group, splits, invert=True).any():
            finding["hint"] = "inverted_split_ratio"
        findings.append(finding)
    counts = {"rows": len(sep), "mismatched_rows": mismatched, "tickers_with_splits": with_splits}
    return _result("raw_units", bool(mismatched), counts, findings)


def _events(ticker_actions: pd.DataFrame) -> list[CorporateAction]:
    events: list[CorporateAction] = []
    for a in ticker_actions.itertuples(index=False):
        if a.action == "split":
            events.append(Split(ex_date=a.date, ratio=float(a.value)))
        elif a.action == "dividend" and math.isfinite(a.value) and a.value > 0:
            events.append(Dividend(ex_date=a.date, cash=float(a.value)))
    return events


def check_adjusted(sep: pd.DataFrame, actions: pd.DataFrame) -> CheckResult:
    """Does vendor `closeadj` equal Algua's back-adjustment of `closeunadj`? Informs §4.10 only."""
    findings: list[dict[str, object]] = []
    consistent = inconsistent = 0
    for ticker, group in sep.groupby("ticker"):
        index = pd.DatetimeIndex(group["date"])
        try:
            check_adj_close_consistent(
                pd.Series(group["closeunadj"].to_numpy(), index=index),
                pd.Series(group["closeadj"].to_numpy(), index=index),
                _events(actions[actions["ticker"] == ticker]),
                rtol=RTOL,
            )
            consistent += 1
        except ValueError as exc:
            inconsistent += 1
            findings.append({"ticker": ticker, "error": str(exc)})
    counts = {"consistent": consistent, "inconsistent": inconsistent}
    return CheckResult("adjusted_close", "info", counts, findings)


def _terminal_class(window: pd.DataFrame) -> str:
    kinds = window["action"]
    if kinds.isin(BANKRUPTCY_ACTIONS).any():
        return "zero_recovery"
    acq = window[kinds.isin(ACQUISITION_ACTIONS)]
    if not acq.empty:
        resolved = acq["contraticker"].notna() & acq["value"].map(
            lambda v: math.isfinite(v) and v > 0)
        return "acquisition_resolved" if resolved.any() else "acquisition_unresolved"
    if kinds.isin(OTHER_DELIST_ACTIONS).any():
        return "other_delisting"
    return "no_action"


def check_terminal(actions: pd.DataFrame, tickers: pd.DataFrame) -> CheckResult:
    """Every delisted security needs a terminal action within the window after its last price."""
    counts = dict.fromkeys(("zero_recovery", "acquisition_resolved", "acquisition_unresolved",
                            "other_delisting", "no_action"), 0)
    findings: list[dict[str, object]] = []
    window_len = pd.Timedelta(days=TERMINAL_WINDOW_DAYS)
    for sec in tickers[tickers["isdelisted"]].itertuples(index=False):
        if pd.isna(sec.lastpricedate):
            cls = "no_action"
        else:
            window = actions[(actions["ticker"] == sec.ticker)
                             & (actions["date"] >= sec.lastpricedate)
                             & (actions["date"] <= sec.lastpricedate + window_len)]
            cls = _terminal_class(window)
        counts[cls] += 1
        if cls in ("acquisition_unresolved", "no_action"):
            findings.append({"permaticker": int(sec.permaticker), "ticker": sec.ticker,
                             "class": cls})
    return _result("terminal", counts["no_action"] > 0, counts, findings)


def check_revisions(sep_now: pd.DataFrame, sep_prev: pd.DataFrame, *,
                    older_than_days: int = 30) -> CheckResult:
    """How much OLD history changed between two pulls (restatement behaviour). Info only."""
    cutoff = sep_prev["date"].max() - pd.Timedelta(days=older_than_days)
    old_prev = sep_prev[sep_prev["date"] < cutoff]
    merged = old_prev.merge(sep_now, on=["ticker", "date"], how="left",
                            suffixes=("_prev", "_now"), indicator=True)
    present = merged[merged["_merge"] == "both"]
    changed = np.zeros(len(present), dtype=bool)
    for col in ("close", "closeunadj", "volume"):
        changed |= ~np.isclose(present[f"{col}_prev"], present[f"{col}_now"], rtol=1e-9, atol=0)
    findings: list[dict[str, object]] = [
        {"ticker": r.ticker, "date": str(r.date.date())}
        for r in present[changed].itertuples(index=False)
    ][:50]
    counts = {
        "compared_rows": len(present),
        "changed_rows": int(changed.sum()),
        "missing_rows": int((merged["_merge"] == "left_only").sum()),
    }
    return CheckResult("revisions", "info", counts, findings)


def run_sharadar_check(sep: pd.DataFrame, actions: pd.DataFrame, tickers: pd.DataFrame,
                       sep_prev: pd.DataFrame | None = None) -> SampleCheckReport:
    """Run every check in a fixed order; `revisions` only when a previous pull is given."""
    checks = [
        check_sample_coverage(sep, actions, tickers),
        check_identity(sep, tickers),
        check_raw_units(sep, actions),
        check_adjusted(sep, actions),
        check_terminal(actions, tickers),
    ]
    if sep_prev is not None:
        checks.append(check_revisions(sep, sep_prev))
    return SampleCheckReport(tuple(checks))
