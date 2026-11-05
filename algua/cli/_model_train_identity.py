"""Declared source-set evidence for this producer; no global artifact identity reinterpretation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from algua.data.files import sha256_file
from algua.provenance import dependency_hash

# Material producer, numerical, source-validation and serve dependencies, explicitly scoped.
_PATHS = (
    "cli/model_cmd.py", "cli/_model_train_request.py", "cli/_model_train_source.py",
    "cli/_model_train_identity.py", "cli/_model_training.py", "training/price_linear.py",
    "features/price_linear.py", "features/price_linear_context.py", "features/scaling.py",
    "features/scaling_fit.py", "calendar/market_calendar.py", "data/files.py", "data/schema.py",
    "data/timeframes.py", "data/manifest.py", "data/verify.py", "data/board_provenance.py",
    "data/store/__init__.py", "data/store/bars.py", "data/store/identity.py",
    "provenance/snapshot.py", "provenance/snapshot_evidence.py", "provenance/research.py",
    "provenance/lockfile.py", "contracts/model_types.py", "contracts/strategy_context.py",
)


def capture_identity() -> dict[str, Any]:
    package = Path(__file__).resolve().parents[1]
    dependency = dependency_hash()
    if not dependency:
        raise ValueError("locked dependency identity is required for the producer")
    files = {"algua/" + path: sha256_file(package / path) for path in _PATHS}
    evidence = {"scope": "price-linear-declared-source-set/v1", "files": files,
                "dependency_hash": dependency}
    raw = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {**evidence, "code_hash": hashlib.sha256(raw).hexdigest()}
