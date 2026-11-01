"""Producer binding for read-only WF scalars. Detects independent metadata drift, not tampering."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any


def record_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def bind_research_record(
    strategy_id: int | None, provenance: dict[str, Any], metrics: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any] | None:
    try:
        return {
            "schema_version": "recorded-wf-scalars/v1", "strategy_id": strategy_id,
            "provenance": provenance,
            "metrics": {k: v if v is None or math.isfinite(v) else None
                        for k, v in metrics.items()},
            "context_sha256": record_digest(config["comparison_context"]),
            "inputs_sha256": record_digest({"run_provenance": config["run_provenance"],
                                             "research_inputs": config.get("research_inputs")}),
        }
    except (ValueError, TypeError, OverflowError):
        return None
