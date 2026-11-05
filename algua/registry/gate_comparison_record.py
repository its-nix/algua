"""Detached comparison capture at the existing post-burn gate writer; no authority of its own."""

from __future__ import annotations

import copy
from typing import Any

from algua.registry.gate_comparison_context import GATE_METRICS as METRICS
from algua.registry.gate_comparison_context import RECORD_SCHEMA as SCHEMA
from algua.registry.research_record import capture_public_record
from algua.registry.runs import _sample, provenance_of, run_provenance_config, walk_forward_metrics
from algua.registry.store.public_windows import number


def capture_gate_comparison(
    wf: Any,
    strategy_id: int,
    wf_run_id: int,
    evaluation_id: int | None,
    series_id: int | None,
    research_inputs: dict[str, Any] | None,
) -> dict[str, Any]:
    """Legacy/direct callers without actual captured inputs do not mint comparison evidence.

    The caller has already persisted the committed burn and its vector. The atomic gate writer
    supplies the gate evaluation ID; ordinary readers independently resolve every reference.
    """
    if evaluation_id is None or series_id is None or research_inputs is None:
        return {}
    public = capture_public_record(
        wf,
        strategy_id,
        provenance_of(wf),
        walk_forward_metrics(wf),
        run_provenance_config(wf)["run_provenance"],
        research_inputs,
    )
    if public is None:
        return {}
    h = wf.holdout_metrics
    context = {k: v for k, v in public["context"].items() if k != "public_interval"}
    context.update(
        schema_version="research-comparison/v1",
        protocol="continuous_portfolio_tail_holdout",
        metrics="net_daily_returns_252_rf0_ddof1_compounded_floored_drawdown/v1",
        oos={k: h[k] for k in ("start", "end", "n_bars")},
    )
    metrics = _sample(h, "_oos") | {"n_obs_oos": h["n_bars"]}
    if not all(number(metrics[k]) for k in METRICS):
        return {}
    return {
        "gate_comparison_record": copy.deepcopy(
            {
                "schema_version": SCHEMA,
                "strategy_id": strategy_id,
                "wf_run_id": wf_run_id,
                "holdout_evaluation_id": evaluation_id,
                "series_holdout_id": series_id,
                "context": context,
                "public_record": public,
                "metrics": {k: metrics[k] for k in METRICS},
            }
        )
    }
