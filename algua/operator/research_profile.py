"""Opt-in fixed midcap proxy inputs, verified before a research cycle can claim work."""
from __future__ import annotations

import ast
import hashlib
import os
import re
from pathlib import Path

from algua.operator.research_memory_checkpoint import canonical, strict_json
from algua.provenance.research import (
    PILOT_PROXY_LIMITATIONS,
    DataTier,
    decode_research_provenance,
)
from algua.provenance.snapshot import compute_snapshot_id

SNAPSHOT_ID = "c63d16f44419cb96"
START, END = "2024-11-01", "2026-11-08"
UNIVERSE_MODULE = "algua/strategies/momentum/midcap_weekly_momentum_smoke.py"
_FIELDS = {"schema_version", "snapshot_id", "content_hash", "start", "end", "symbols_sha256"}


def symbols_digest(symbols: list[str]) -> str:
    return hashlib.sha256(canonical(sorted(symbols))).hexdigest()


def midcap_symbols(root: Path) -> list[str]:
    """Read the reviewed literal CONFIG without executing authored strategy Python."""
    try:
        tree = ast.parse((root / UNIVERSE_MODULE).read_text())
        configs = [node.value for node in tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "CONFIG" for t in node.targets)]
        if len(configs) != 1 or not isinstance(configs[0], ast.Call):
            raise ValueError
        values = [k.value for k in configs[0].keywords if k.arg == "universe"]
        if len(values) != 1:
            raise ValueError
        value = values[0]
        if (not isinstance(value, ast.Call) or value.args or value.keywords
                or not isinstance(value.func, ast.Attribute) or value.func.attr != "split"
                or not isinstance(value.func.value, ast.Constant)
                or not isinstance(value.func.value.value, str)):
            raise ValueError
        symbols = sorted(value.func.value.value.split())
        if len(symbols) != 300 or len(set(symbols)) != 300 or any(
                re.fullmatch(r"[A-Z][A-Z0-9-]*", s) is None for s in symbols):
            raise ValueError
        return symbols
    except (OSError, SyntaxError, ValueError):
        raise ValueError("research_profile:universe_invalid") from None


def load_research_profile(data_dir: Path, *, root: Path | None = None) -> dict | None:
    """Validate all declared inputs and the full logical payload; unconfigured is a no-op."""
    configured = os.environ.get("ALGUA_RESEARCH_PROFILE")
    if configured is None:
        return None
    try:
        path = Path(configured)
        if not configured or not path.is_file() or path.stat().st_size > 16 * 1024:
            raise ValueError
        descriptor = strict_json(path.read_bytes())
        if (not isinstance(descriptor, dict) or set(descriptor) != _FIELDS
                or descriptor["schema_version"] != "midcap-research-profile/v1"
                or descriptor["snapshot_id"] != SNAPSHOT_ID
                or descriptor["start"] != START or descriptor["end"] != END
                or any(not isinstance(descriptor[k], str)
                       or re.fullmatch(r"[0-9a-f]{64}", descriptor[k]) is None
                       for k in ("content_hash", "symbols_sha256"))):
            raise ValueError
    except (OSError, ValueError, TypeError, RecursionError):
        raise ValueError("research_profile:descriptor_invalid") from None
    root = root or Path(__file__).resolve().parents[2]
    symbols = midcap_symbols(root)
    if descriptor["symbols_sha256"] != symbols_digest(symbols):
        raise ValueError("research_profile:universe_drift")
    from algua.data.files import logical_bars_hash
    from algua.data.models import Dataset, Kind
    from algua.data.store import DataStore

    try:
        store = DataStore(data_dir)
        record = store.get_snapshot(SNAPSHOT_ID)
        provenance = decode_research_provenance(record.metadata.source_metadata)
        if (record.dataset != Dataset.BARS or record.kind != Kind.BARS
                or record.storage_format != "parquet_dataset" or record.metadata.timeframe != "1d"
                or record.start != START or record.end != END
                or record.content_hash != descriptor["content_hash"]
                or compute_snapshot_id(record.metadata, record.content_hash) != SNAPSHOT_ID
                or not set(symbols) <= set(record.symbols)
                or provenance is None or provenance.data_tier is not DataTier.PILOT_REAL_PROXY
                or set(provenance.limitations) != PILOT_PROXY_LIMITATIONS):
            raise ValueError
        bars = store.read_bars(SNAPSHOT_ID)
        raw = bars.reset_index().rename(columns={"timestamp": "ts"})
        if (len(raw) != record.row_count or logical_bars_hash(raw) != record.content_hash
                or set(raw["symbol"]) != set(record.symbols)
                or raw["ts"].min().date().isoformat() != START
                or raw["ts"].max().date().isoformat() != "2026-11-06"):
            raise ValueError
    except (OSError, ValueError, LookupError, TypeError):
        raise ValueError("research_profile:payload_invalid") from None
    return {**descriptor, "profile_sha256": hashlib.sha256(canonical(descriptor)).hexdigest(),
            "symbols": symbols, "timeframe": "1d", "universe_mode": "static",
            "data_tier": "pilot_real_proxy", "limitations": sorted(PILOT_PROXY_LIMITATIONS),
            "qualification_eligible": False, "windows": 4, "holdout_frac": 0.2,
            "execution": {"decision_lag_bars": 1, "max_weight_per_symbol": 0.075,
                          "fees": 0.0005, "slippage": 0.0005,
                          "construction": "top_k_equal_weight", "top_k": 20}}
