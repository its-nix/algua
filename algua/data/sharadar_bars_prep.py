"""Stage 1: freeze an UNQUALIFIED stable-identity bars snapshot from private Sharadar exports.

Binds the SEP rows to the shipped `compile-identities` artifact: every SEP ticker must be exactly
one artifact `current_storage_ticker` (a restated vendor key; no historical alias is inferred) and
the artifact must have been compiled from the SAME TICKERS/ACTIONS bytes supplied here. Bars are
stored under the stable ID `SHARADAR:PERMATICKER:<n>` through the existing streamed-ingest seam.
Raw reconstruction and the action/raw-unit check are the existing Sharadar provider functions.
Refusals are fixed text: errors reach stdout and the inputs are licensed vendor data.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from algua.data.importers.sharadar_tables import read_actions, read_sep, read_tickers
from algua.data.providers.errors import ProviderError
from algua.data.providers.sharadar import check_actions, normalize_prices
from algua.data.research_provenance import DataTier, ProvenanceDeclaration
from algua.data.sharadar_evidence import stable_id
from algua.data.sharadar_identity import (
    SCHEMA as IDENTITY_SCHEMA,
)
from algua.data.sharadar_identity import (
    IdentityCompileError,
    _capture,
    _read_hashed,
    _sanitized,
)
from algua.data.store import DataStore

MAX_SEP_BYTES = 4 << 30
MAX_ARTIFACT_BYTES = 256 << 20
MAX_SEP_ROWS = 40_000_000
UNIVERSE_METHOD = "sharadar-stable-identity-unverified"
LIMITATIONS = ("adjusted_close_vendor_revisable", "corporate_actions_unverified",
               "point_in_time_universe_unavailable")


@dataclass(frozen=True)
class LoadedIdentities:
    sha256: str
    tickers_sha256: str
    actions_sha256: str
    by_ticker: dict[str, str]  # current storage ticker -> stable ID
    ids: frozenset[str]


def load_identity_artifact(path: Path) -> LoadedIdentities:
    data = _capture(path, MAX_ARTIFACT_BYTES)
    try:
        doc = json.loads(data)
        if (doc["schema"] != IDENTITY_SCHEMA or doc["status"] != "unqualified_input_preparation"
                or doc["coverage"] != "unverified"):
            raise ValueError
        by_ticker: dict[str, str] = {}
        for row in doc["identities"]:
            perma = row["permaticker"]
            sid = stable_id(row["stable_key"])
            if (type(perma) is not int or perma <= 0
                    or row["stable_key"] != f"sharadar:permaticker:{perma}"
                    or not row["current_storage_ticker"]
                    or row["current_storage_ticker"] in by_ticker):
                raise ValueError
            by_ticker[row["current_storage_ticker"]] = sid
        if not by_ticker or len(set(by_ticker.values())) != len(by_ticker):
            raise ValueError
        return LoadedIdentities(hashlib.sha256(data).hexdigest(),
                                str(doc["inputs"]["tickers_sha256"]),
                                str(doc["inputs"]["actions_sha256"]), by_ticker,
                                frozenset(by_ticker.values()))
    except (ValueError, KeyError, TypeError):
        raise IdentityCompileError(
            "identity artifact is malformed or not a compiler output") from None


@dataclass(frozen=True)
class PreparedBars:
    snapshot_id: str
    content_hash: str
    identity_count_mapped: int
    sep_rows: int
    sep_sha256: str
    tickers_sha256: str
    actions_sha256: str
    identity_artifact_sha256: str


@_sanitized("bar preparation failed")
def prepare_bars(sep: Path, tickers: Path, actions: Path, identities: Path, *, as_of: str,
                 store: DataStore) -> PreparedBars:
    ident = load_identity_artifact(identities)
    tick_frame, tick_sha = _read_hashed(tickers, read_tickers, "TICKERS", 64 << 20)
    act_frame, act_sha = _read_hashed(actions, read_actions, "ACTIONS", 512 << 20)
    if (tick_sha, act_sha) != (ident.tickers_sha256, ident.actions_sha256):
        raise IdentityCompileError("identity artifact was not compiled from these TICKERS/ACTIONS")
    # the artifact's mapping must equal what these TICKERS rows say (guards a hand-edited artifact)
    if {t: f"SHARADAR:PERMATICKER:{int(p)}" for t, p in
            zip(tick_frame["ticker"], tick_frame["permaticker"], strict=True)} != ident.by_ticker:
        raise IdentityCompileError("identity artifact does not match TICKERS")
    sep_frame, sep_sha = _read_hashed(sep, read_sep, "SEP", MAX_SEP_BYTES)
    if len(sep_frame) > MAX_SEP_ROWS or sep_frame.empty:
        raise IdentityCompileError("SEP export is empty or exceeds the row limit")
    unmapped = set(sep_frame["ticker"]) - set(ident.by_ticker)
    if unmapped:
        raise IdentityCompileError("SEP has tickers without exactly one stable identity")
    sep_frame["date"] = sep_frame["date"].dt.strftime("%Y-%m-%d")
    act_frame = act_frame.assign(date=act_frame["date"].dt.strftime("%Y-%m-%d"))
    by_actions = {t: g for t, g in act_frame.groupby("ticker")}
    empty_actions = act_frame.iloc[0:0]
    first, last = str(sep_frame["date"].min()), str(sep_frame["date"].max())
    groups = sep_frame.groupby("ticker", sort=True)
    seen: list[str] = []

    def chunks() -> Iterator[pd.DataFrame]:
        for ticker, raw in groups:
            name = str(ticker)
            try:
                check_actions(raw, by_actions.get(name, empty_actions), name)
                frame = normalize_prices(raw, name, "0001-01-01", "9999-12-31")
            except ProviderError:
                raise IdentityCompileError(
                    "SEP rows for a ticker are invalid or fail the action/raw-unit check") from None
            frame["symbol"] = ident.by_ticker[name]
            seen.append(ident.by_ticker[name])
            yield frame

    store.clear_staging()
    rec = store.ingest_bars_streamed(
        provider="sharadar", symbols=seen, as_of=as_of, source="sharadar-prepare-bars",
        chunks=chunks(), timeframe="1d", adjustment="none", start=first, end=last,
        source_metadata={
            "stable_id_transform": "upper(sharadar:permaticker:N)",
            "identity_mapping": "current_storage_ticker_unverified_history",
            "coverage": "missing_sessions_not_filled_or_certified",
            "pit_status": "unverified_vendor_history",
            "sep_sha256": sep_sha, "tickers_sha256": tick_sha, "actions_sha256": act_sha,
            "identity_artifact_sha256": ident.sha256,
            "adjustments": "raw_OHLCV_reconstructed;closeadj_includes_dividends_and_spinoffs",
        },
        provenance=ProvenanceDeclaration(DataTier.PILOT_REAL_PROXY, UNIVERSE_METHOD, LIMITATIONS),
    )
    return PreparedBars(rec.snapshot_id, rec.content_hash, len(seen), len(sep_frame), sep_sha,
                        tick_sha, act_sha, ident.sha256)
