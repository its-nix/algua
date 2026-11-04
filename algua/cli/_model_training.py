"""CLI composition only: capture one vintage, fit once, publish one existing model version."""
from __future__ import annotations

import json
import platform
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from algua import models
from algua.calendar.market_calendar import MarketCalendar
from algua.cli._model_train_identity import capture_identity
from algua.cli._model_train_request import TrainRequest
from algua.cli._model_train_source import capture_source
from algua.config.settings import get_settings
from algua.contracts.model_types import ModelVersion
from algua.data.store import DataStore
from algua.features.price_linear_context import CUTOFF_SEMANTICS, PRODUCER_SCHEMA, PROXY_MODE


def train_linear(name: str, request: TrainRequest) -> tuple[ModelVersion, dict[str, Any]]:
    # Lazy training ingress: model show/list/register/help never import the fitter.
    from algua.training.price_linear import fit_price_linear

    identity = capture_identity()
    source = capture_source(DataStore(get_settings().data_dir), request)
    started = datetime.now(UTC).isoformat()
    result = fit_price_linear(source.prices, train_start=request.train_start,
                              train_end=request.train_end, l2=request.l2)
    finished = datetime.now(UTC).isoformat()
    calendar = MarketCalendar("XNYS")
    max_x, max_y = (pd.Timestamp(value).date()
                    for value in (result.report.max_x_event, result.report.max_y_event))
    x_close, y_close = calendar.session_close(max_x), calendar.session_close(max_y)
    if not (max_x < max_y and y_close < request.train_end):
        raise ValueError("a complete target-session close must precede train_end")
    cutoff = {"semantics": CUTOFF_SEMANTICS, "training_as_of": y_close.isoformat(),
              "max_x_event": result.report.max_x_event, "max_y_event": result.report.max_y_event,
              "max_x_close": x_close.isoformat(), "max_y_close": y_close.isoformat()}
    report = {"schema": PRODUCER_SCHEMA, "mode": PROXY_MODE,
        "historical_source_availability": "UNKNOWN", "request": request.as_dict(),
        "source": {"record": source.record, "provenance": source.provenance},
        "verification": {"source_verified_at": source.verified_at,
            "logical_content_hash": source.record["content_hash"],
            "physical_files": source.physical, "request_raw_sha256": request.raw_sha256,
            "consumed_prices_sha256": source.consumed_sha256,
            "source_acquisition_status": "DECLARED_RECORD_ONLY_HISTORICAL_AVAILABILITY_UNKNOWN"},
        "fit": asdict(result.report), "cutoff": cutoff,
        "clocks": {"fit_started_at": started, "fit_finished_at": finished},
        "reproducibility": {**identity, "python": platform.python_version()}}
    encoded = json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(encoded) > 1024 * 1024:
        raise ValueError("producer provenance report exceeds its1MiB bound")
    report = json.loads(encoded)
    source.revalidate()
    if capture_identity() != identity:
        raise ValueError("producer source or locked dependencies changed during fitting")
    version = models.register(name, result.model.to_json(),
        training_snapshot_id=request.bars_snapshot_id,
        training_as_of=cutoff["training_as_of"], code_hash=identity["code_hash"], seed=None,
        hyperparameters={"recipe": "pooled-return-ridge/v1", "features": ["return_1", "return_5"],
            "l2": request.l2, "scaler": "standard", "ddof": 0, "intercept_penalized": False,
            "target": "next_observed_adjusted_close_return_on_complete_xnys_grid",
            "train_start": request.train_start.isoformat(),
            "train_end": request.train_end.isoformat()},
        eval_report=report)
    public_fit = {key: getattr(result.report, key) for key in (
        "train_start", "train_end", "candidate_observations", "warmup_observations",
        "unlabelled_observations", "fitted_observations", "max_x_event", "max_y_event")}
    public_fit.update(symbol_count=len(request.symbols), target_close=cutoff["max_y_close"])
    return version, {"proxy": {"mode": PROXY_MODE, "cutoff_semantics": CUTOFF_SEMANTICS,
        "historical_source_availability": "UNKNOWN", "data_tier": source.provenance["data_tier"],
        "limitations": source.provenance["limitations"]}, "fit": public_fit}
