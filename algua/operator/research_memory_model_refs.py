"""Pure model-pin metadata compatibility, independent of model registry or execution."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import pandas as pd

from algua.contracts.model_types import normalize_as_of

_KEYS = {"name", "version", "digest", "training_as_of", "provenance_digest"}


def _cutoff(value: Any, *, legacy: bool) -> bool:
    if not isinstance(value, str) or len(value) > 128:
        return False
    # Existing 64-hex archives admitted aware ISO week dates that pandas may not parse.
    if legacy:
        try:
            if datetime.fromisoformat(value).tzinfo is not None:
                return True
        except ValueError:
            pass
    try:
        return not pd.isna(normalize_as_of(value))
    except (TypeError, ValueError, OverflowError):
        return False


def public_model_refs(value: Any, *, kind: str) -> list[dict[str, Any]]:
    """Validate producer 16/16 or legacy 64/64 pins without rewriting text or resolving bytes."""
    if not isinstance(value, list) or len(value) > 16:
        raise ValueError("research memory model references are malformed")
    if kind != "backtest" and value:
        raise ValueError("model-backed windowed research is unsupported")
    for ref in value:
        if (not isinstance(ref, dict) or set(ref) != _KEYS
                or not isinstance(ref["name"], str)
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", ref["name"]) is None
                or type(ref["version"]) is not int or ref["version"] < 1
                or not all(isinstance(ref[k], str) for k in ("digest", "provenance_digest"))):
            raise ValueError("research memory model reference is malformed")
        width = len(ref["digest"])
        if (width not in (16, 64) or any(re.fullmatch(rf"[0-9a-f]{{{width}}}", ref[k]) is None
                for k in ("digest", "provenance_digest"))
                or not _cutoff(ref["training_as_of"], legacy=width == 64)):
            raise ValueError("research memory model reference is malformed")
    return value
