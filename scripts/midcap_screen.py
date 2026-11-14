"""Read-only selection of the approved current-midcap machinery sample; never PIT authority."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from bs4 import BeautifulSoup

from algua.calendar.market_calendar import MarketCalendar
from algua.data.store import DataStore
from scripts.pilot_proxy_source import RecipeError, parse_source_payload

PROFILE: dict[str, Any] = {
    "id": "liquid-midcap-machinery/v1",
    "min_price": 10,
    "min_median_dollar_volume": 20_000_000,
    "liquidity_sessions": 60,
    "min_history_sessions": 252,
    "max_symbols": 300,
    "target_holding_sessions": [2, 20],
}


def membership_sectors(raw: bytes) -> dict[str, str]:
    # Reuse the source parser's symbol validation and Yahoo alias-collision check.
    parse_source_payload(raw, count=1)
    table = BeautifulSoup(raw, "html.parser").find("table", id="constituents")
    if table is None:
        raise ValueError("missing constituents table")
    rows = table.find_all("tr")
    headers = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])]
    if headers.count("GICS Sector") != 1:
        raise ValueError("one GICS Sector column is required")
    symbol_col, sector_col = headers.index("Symbol"), headers.index("GICS Sector")
    result = {}
    for row in rows[1:]:
        cells = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]
        if len(cells) != len(headers) or not cells[sector_col]:
            raise ValueError("incomplete constituent sector row")
        symbol = cells[symbol_col].replace(".", "-")
        if symbol in result:
            raise ValueError("duplicate constituent")
        result[symbol] = cells[sector_col]
    return result


def screen(frame: pd.DataFrame, sectors: dict[str, str]) -> dict:
    if frame.empty or frame.index.tz is None:
        raise ValueError("nonempty timezone-aware bars required")
    flat = frame.reset_index()
    if flat.duplicated([flat.columns[0], "symbol"]).any():
        raise ValueError("duplicate symbol/session bars")
    dates = frame.index.unique().sort_values()
    latest = dates[-1]
    calendar = MarketCalendar("XNYS")
    valid_dates = set(calendar.sessions_in_range(dates[0].date(), latest.date()))
    if any(stamp.date() not in valid_dates for stamp in dates):
        raise ValueError("non-session bars cannot count as trading history")
    recent_days = [latest.date()]
    for _ in range(PROFILE["liquidity_sessions"] - 1):
        recent_days.append(calendar.previous_session(recent_days[-1]))
    recent = pd.DatetimeIndex(sorted(recent_days), tz="UTC", name=frame.index.name)
    records: list[dict[str, Any]] = []
    for symbol, sector in sorted(sectors.items()):
        bars = frame[frame["symbol"] == symbol].sort_index()
        reasons = []
        last_price = median = None
        if len(bars) < PROFILE["min_history_sessions"]:
            reasons.append("insufficient_history")
        if bars.empty or bars.index[-1] != latest:
            reasons.append("stale_or_missing_latest_bar")
        tail = bars.reindex(recent)
        if (
            len(recent) < PROFILE["liquidity_sessions"]
            or tail[["close", "volume"]].isna().any().any()
        ):
            reasons.append("incomplete_liquidity_window")
        elif not ((tail["close"] > 0) & (tail["volume"] >= 0)).all():
            raise ValueError(f"invalid price or volume for {symbol}")
        else:
            last_price = float(tail["close"].iloc[-1])
            median = float((tail["close"] * tail["volume"]).median())
            if not math.isfinite(median) or not math.isfinite(last_price):
                raise ValueError(f"nonfinite liquidity for {symbol}")
            if last_price < PROFILE["min_price"]:
                reasons.append("price_below_floor")
            if median < PROFILE["min_median_dollar_volume"]:
                reasons.append("liquidity_below_floor")
        records.append(
            {
                "symbol": symbol,
                "sector": sector,
                "sessions": len(bars),
                "latest_close": last_price,
                "median_dollar_volume_60": median,
                "eligible": not reasons,
                "reasons": reasons,
            }
        )
    # Round-robin sectors, highest liquidity within each; no return-based stock selection.
    groups: dict[str, list[dict[str, Any]]] = {}
    for sector in sorted(set(sectors.values())):
        groups[sector] = sorted(
            [r for r in records if r["sector"] == sector and r["eligible"]],
            key=lambda r: (-r["median_dollar_volume_60"], r["symbol"]),
        )
    selected: list[str] = []
    while any(groups.values()) and len(selected) < PROFILE["max_symbols"]:
        for candidates in groups.values():
            if candidates and len(selected) < PROFILE["max_symbols"]:
                selected.append(candidates.pop(0)["symbol"])
    chosen = set(selected)
    for row in records:
        row["selected"] = row["symbol"] in chosen
        if row["eligible"] and not row["selected"]:
            row["reasons"].append("sample_size_cap")
    return {
        "profile": PROFILE,
        "latest_bar": latest.isoformat(),
        "selected_symbols": sorted(selected),
        "selected_count": len(selected),
        "eligible_count": sum(r["eligible"] for r in records),
        "selected_by_sector": dict(Counter(sectors[s] for s in selected)),
        "records": records,
        "point_in_time_membership": False,
        "broker_tradability_verified": False,
        "live_authority": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--membership-html", required=True, type=Path)
    args = parser.parse_args()
    try:
        store = DataStore(args.data_dir)
        snapshot = store.get_snapshot(args.snapshot)
        store.verify_snapshot(snapshot)
        raw = args.membership_html.read_bytes()
        result = screen(store.read_bars(args.snapshot), membership_sectors(raw))
        result.update(
            {
                "ok": True,
                "snapshot_id": args.snapshot,
                "content_hash": snapshot.content_hash,
                "membership_sha256": hashlib.sha256(raw).hexdigest(),
                "screened_at": datetime.now(UTC).isoformat(),
                "source_metadata": snapshot.to_dict()["source_metadata"],
            }
        )
        print(json.dumps(result, indent=2, allow_nan=False))
    except (ValueError, OSError, RecipeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
