"""Adversarial sample check for Sharadar data against the agreed PIT standard (spec §4.6, §5.A).

Pure functions over the frames `algua.data.importers.sharadar_tables` returns. Each check yields a
`CheckResult`; `"fail"` stops the data project, `"info"` informs the importer plan and never gates.
Findings may carry vendor values (dates, prices), so they belong only in the owner's PRIVATE report;
`SampleCheckReport.summary()` is the public-safe projection (names, statuses, counts).
Spec: docs/superpowers/specs/2026-11-12-pit-data-pipeline-design.md.
"""
from __future__ import annotations

import pandas as pd

from algua.data.sharadar_check_types import (
    RTOL,
    CheckResult,
    SampleCheckReport,
    Status,
    owners,
    result,
    valid_value,
)
from algua.data.sharadar_price_checks import (
    CLOSE_ATOL,
    check_adjusted,
    check_raw_units,
    check_revisions,
)

BANKRUPTCY_ACTIONS = frozenset({"bankruptcyliquidation"})
ACQUISITION_ACTIONS = frozenset({"acquisitionby", "mergerto"})
OTHER_DELIST_ACTIONS = frozenset({"delisted", "regulatorydelisting", "voluntarydelisting"})
#: A terminal action may be dated up to this many days AFTER the last price...
TERMINAL_WINDOW_DAYS = 30
#: ...or up to this many days BEFORE it (a filing/announcement while the name still trades).
TERMINAL_LOOKBACK_DAYS = 365
_TRAILING_DIGITS = r"\d+$"

__all__ = [
    "ACQUISITION_ACTIONS", "BANKRUPTCY_ACTIONS", "CLOSE_ATOL", "OTHER_DELIST_ACTIONS", "RTOL",
    "TERMINAL_LOOKBACK_DAYS", "TERMINAL_WINDOW_DAYS", "CheckResult", "SampleCheckReport", "Status",
    "check_adjusted", "check_identity", "check_raw_units", "check_revisions",
    "check_sample_coverage", "check_terminal", "run_sharadar_check",
]


def _reused_ticker_count(tickers: pd.DataFrame) -> int:
    """Tickers held by >= 2 securities, exactly or after stripping a trailing numeric suffix (a
    vendor may rename the delisted holder of a reused symbol, e.g. `XYZ` -> `XYZ1`)."""
    base = tickers["ticker"].str.replace(_TRAILING_DIGITS, "", regex=True)
    return int((tickers.groupby(base)["permaticker"].nunique() >= 2).sum())


def check_sample_coverage(sep: pd.DataFrame, actions: pd.DataFrame,
                          tickers: pd.DataFrame) -> CheckResult:
    """The sample must contain every adversarial case, so an easy sample cannot pass."""
    kinds = actions["action"]
    valued = actions["value"].map(valid_value)
    counts = {
        "split": int(((kinds == "split") & valued).sum()),
        "dividend": int(((kinds == "dividend") & valued).sum()),
        "bankruptcy": int(kinds.isin(BANKRUPTCY_ACTIONS).sum()),
        "acquisition": int((kinds.isin(ACQUISITION_ACTIONS)
                            & actions["contraticker"].notna()).sum()),
        "reused_ticker": _reused_ticker_count(tickers),
    }
    findings: list[dict[str, object]] = [{"missing": k} for k, n in counts.items() if n == 0]
    return result("sample_coverage", bool(findings), counts, findings)


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
    n_owners, _ = owners(sep, tickers)
    bad = n_owners != 1
    for row, n in zip(sep.loc[bad, ["ticker", "date"]].itertuples(index=False),
                      n_owners[bad], strict=True):
        findings.append({"ticker": row.ticker, "date": str(row.date.date()), "owners": int(n)})
    counts = {
        "permatickers": int(tickers["permaticker"].nunique()),
        "reused_tickers": _reused_ticker_count(tickers),
        "overlaps": overlaps,
        "unassigned_rows": int(bad.sum()),
    }
    return result("identity", bool(overlaps or bad.any()), counts, findings)


def _terminal_class(window: pd.DataFrame) -> str:
    kinds = window["action"]
    if kinds.isin(BANKRUPTCY_ACTIONS).any():
        return "zero_recovery"
    if kinds.isin(ACQUISITION_ACTIONS).any():
        # Relationship-marker values are final market caps, not per-share consideration.
        return "acquisition_unresolved"
    if kinds.isin(OTHER_DELIST_ACTIONS).any():
        return "other_delisting"
    return "no_action"


def check_terminal(actions: pd.DataFrame, tickers: pd.DataFrame) -> CheckResult:
    """Every delisted security needs a terminal action near its last price: from
    TERMINAL_LOOKBACK_DAYS before it (never before its first price) to TERMINAL_WINDOW_DAYS
    after. Acquisition markers identify relationships, not verified consideration or effective-date
    prices; those remain unresolved. The resolved count is retained for report compatibility."""
    counts = dict.fromkeys(("zero_recovery", "acquisition_resolved", "acquisition_unresolved",
                            "other_delisting", "no_action"), 0)
    findings: list[dict[str, object]] = []
    for sec in tickers[tickers["isdelisted"]].itertuples(index=False):
        if pd.isna(sec.lastpricedate):
            cls = "no_action"
        else:
            start = sec.lastpricedate - pd.Timedelta(days=TERMINAL_LOOKBACK_DAYS)
            if not pd.isna(sec.firstpricedate):
                start = max(start, sec.firstpricedate)
            end = sec.lastpricedate + pd.Timedelta(days=TERMINAL_WINDOW_DAYS)
            window = actions[(actions["ticker"] == sec.ticker)
                             & (actions["date"] >= start) & (actions["date"] <= end)]
            cls = _terminal_class(window)
        counts[cls] += 1
        if cls in ("acquisition_unresolved", "no_action"):
            finding: dict[str, object] = {
                "permaticker": int(sec.permaticker), "ticker": sec.ticker, "class": cls}
            if cls == "acquisition_unresolved":
                finding["limitation"] = "consideration_and_effective_date_prices_not_verified"
            findings.append(finding)
    return result("terminal", counts["no_action"] > 0, counts, findings)


def run_sharadar_check(sep: pd.DataFrame, actions: pd.DataFrame, tickers: pd.DataFrame,
                       sep_prev: pd.DataFrame | None = None) -> SampleCheckReport:
    """Run every check in a fixed order; `revisions` only when a previous pull is given."""
    checks = [
        check_sample_coverage(sep, actions, tickers),
        check_identity(sep, tickers),
        check_raw_units(sep, actions, tickers),
        check_adjusted(sep, actions, tickers),
        check_terminal(actions, tickers),
    ]
    if sep_prev is not None:
        checks.append(check_revisions(sep, sep_prev))
    return SampleCheckReport(tuple(checks))
