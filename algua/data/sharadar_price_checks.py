"""Price-series checks of the Sharadar sample check: raw units, adjusted close, revisions.

Carved from `algua.data.sharadar_check` (which re-exports these names); see that module's docstring.
"""
from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import pandas as pd

from algua.data.corpactions import CorporateAction, Dividend, Split, check_adj_close_consistent
from algua.data.sharadar_check_types import RTOL, CheckResult, owners, result, valid_value

#: Absolute tolerance on split-adjusted `close`: half a cent, the coarsest plausible vendor
#: rounding. Rounding error is multiplied by the split factor when compared in raw units, so the
#: comparison is made in `close` space instead.
CLOSE_ATOL = 0.005


def _securities(sep: pd.DataFrame, actions: pd.DataFrame, tickers: pd.DataFrame | None
                ) -> Iterator[tuple[str, pd.DataFrame, pd.DataFrame]]:
    """Yield (label, SEP rows, that security's actions). With `tickers`, rows are split per
    security and actions limited to its price range, so a reused ticker's two securities never
    share a split history. Rows no single security owns fall back to the ticker (identity fails
    them separately)."""
    if tickers is None:
        owner = pd.Series(np.nan, index=sep.index)
    else:
        _, owner = owners(sep, tickers)
    keyed = sep.assign(_owner=owner.fillna(-1).astype("int64"))
    for (ticker, perma), group in keyed.groupby(["ticker", "_owner"]):
        acts = actions[actions["ticker"] == ticker]
        label = str(ticker)
        if perma != -1 and tickers is not None:
            sec = tickers[tickers["permaticker"] == perma].iloc[0]
            acts = acts[(acts["date"] >= sec["firstpricedate"])
                        & (acts["date"] <= sec["lastpricedate"])]
            label = f"{ticker}#{perma}"
        yield label, group.drop(columns="_owner"), acts


def _split_factor(dates: pd.Series, splits: pd.DataFrame, invert: bool) -> np.ndarray:
    factor = np.ones(len(dates))
    for split in splits.itertuples(index=False):
        ratio = 1.0 / split.value if invert else split.value
        factor = np.where((dates < split.date).to_numpy(), factor * ratio, factor)
    return factor


def _mismatches(group: pd.DataFrame, splits: pd.DataFrame, invert: bool) -> np.ndarray:
    implied_close = group["closeunadj"].to_numpy() / _split_factor(group["date"], splits, invert)
    close = group["close"].to_numpy()
    tol = np.maximum(RTOL * np.abs(close), CLOSE_ATOL)
    return np.abs(implied_close - close) > tol


def check_raw_units(sep: pd.DataFrame, actions: pd.DataFrame,
                    tickers: pd.DataFrame | None = None) -> CheckResult:
    """`close` is split-adjusted: `closeunadj` ÷ Π(ratio of later splits) must equal `close`."""
    findings: list[dict[str, object]] = []
    mismatched = 0
    with_splits = 0
    invalid = 0
    for label, group, acts in _securities(sep, actions, tickers):
        splits = acts[acts["action"] == "split"]
        bad_values = ~splits["value"].map(valid_value)
        if bad_values.any():
            invalid += int(bad_values.sum())
            findings.append({"security": label, "problem": "invalid_split_value",
                             "dates": [str(d.date()) for d in splits["date"][bad_values]]})
            splits = splits[~bad_values]
        with_splits += int(not splits.empty)
        bad = _mismatches(group, splits, invert=False)
        if not bad.any():
            continue
        mismatched += int(bad.sum())
        finding: dict[str, object] = {
            "security": label,
            "dates": [str(d.date()) for d in group["date"][bad]][:10],
        }
        if not splits.empty and not _mismatches(group, splits, invert=True).any():
            finding["hint"] = "inverted_split_ratio"
        findings.append(finding)
    counts = {"rows": len(sep), "mismatched_rows": mismatched, "tickers_with_splits": with_splits,
              "invalid_split_values": invalid}
    return result("raw_units", bool(mismatched or invalid), counts, findings)


def _events(ticker_actions: pd.DataFrame) -> list[CorporateAction]:
    events: list[CorporateAction] = []
    for a in ticker_actions.itertuples(index=False):
        if not valid_value(a.value):
            continue
        if a.action == "split":
            events.append(Split(ex_date=a.date, ratio=float(a.value)))
        elif a.action == "dividend":
            events.append(Dividend(ex_date=a.date, cash=float(a.value)))
    return events


def check_adjusted(sep: pd.DataFrame, actions: pd.DataFrame,
                   tickers: pd.DataFrame | None = None) -> CheckResult:
    """Does vendor `closeadj` equal Algua's back-adjustment of `closeunadj`? Informs §4.10 only.
    Spinoffs are not modelled, so a spinoff name shows as inconsistent here."""
    findings: list[dict[str, object]] = []
    consistent = inconsistent = 0
    for label, group, acts in _securities(sep, actions, tickers):
        index = pd.DatetimeIndex(group["date"])
        try:
            check_adj_close_consistent(
                pd.Series(group["closeunadj"].to_numpy(), index=index),
                pd.Series(group["closeadj"].to_numpy(), index=index),
                _events(acts),
                rtol=RTOL,
            )
            consistent += 1
        except ValueError as exc:
            inconsistent += 1
            findings.append({"security": label, "error": str(exc)})
    counts = {"consistent": consistent, "inconsistent": inconsistent}
    return CheckResult("adjusted_close", "info", counts, findings)


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
