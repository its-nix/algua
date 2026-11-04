"""Apply the explicitly declared proxy producer profile to an existing verified context."""
from __future__ import annotations

import json
import math

import pandas as pd

from algua.contracts.model_types import ModelHandle, normalize_as_of
from algua.contracts.strategy_context import AsOfContext
from algua.features.price_linear import FrozenPriceLinear, return_features
from algua.features.scaling import assert_fit_before

PRODUCER_SCHEMA = "price-linear-proxy-producer/v1"
PROXY_MODE = "fixed_vintage_historical_proxy"
CUTOFF_SEMANTICS = "complete_target_xnys_close/v1"
REPORT_KEYS = {"schema", "mode", "historical_source_availability", "request", "source",
               "verification", "fit", "clocks", "reproducibility", "cutoff"}


def _closed(value: object, fields: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("proxy producer profile has an unsupported shape")


def _report_shapes(report: dict) -> None:
    _closed(report["request"], {"schema", "bars_snapshot_id", "symbols", "train_start",
                                 "train_end", "l2"})
    _closed(report["fit"], {"train_start", "train_end", "symbols", "l2", "consumed_events",
        "window_events", "candidate_observations", "warmup_observations",
        "unlabelled_observations", "fitted_observations", "max_x_event", "max_y_event"})
    _closed(report["cutoff"], {"semantics", "training_as_of", "max_x_event", "max_y_event",
                              "max_x_close", "max_y_close"})
    # The original snapshot record/provenance remain their existing declarations, not a new schema.
    _closed(report["source"], {"record", "provenance"})
    _closed(report["verification"], {"source_verified_at", "logical_content_hash",
        "physical_files", "request_raw_sha256", "consumed_prices_sha256",
        "source_acquisition_status"})
    _closed(report["clocks"], {"fit_started_at", "fit_finished_at"})
    _closed(report["reproducibility"], {"scope", "files", "dependency_hash", "code_hash", "python"})


def _fit_report(report: dict, symbols: list[str]) -> None:
    fit, request = report["fit"], report["request"]
    counts = ["consumed_events", "window_events", "candidate_observations", "warmup_observations",
              "unlabelled_observations", "fitted_observations"]
    if any(type(fit[key]) is not int or fit[key] < 0 for key in counts):
        raise ValueError("fit counts must be nonnegative integers")
    if (fit["candidate_observations"] != fit["window_events"] * len(symbols)
            or fit["candidate_observations"] != sum(fit[key] for key in counts[-3:])
            or not 3 <= fit["fitted_observations"] <= 2_000_000
            or not 0 < fit["window_events"] <= fit["consumed_events"] <= 100_000
            or fit["unlabelled_observations"] != len(symbols)
            or any(fit[key] % len(symbols) for key in counts[-3:])):
        raise ValueError("fit report partition is inconsistent")
    penalty = request["l2"]
    if (type(penalty) not in (int, float) or not math.isfinite(penalty) or penalty <= 0
            or type(fit["l2"]) not in (int, float) or fit["l2"] != penalty):
        raise ValueError("fit penalty does not match the request")
    start, end = (_stamp(request[key]) for key in ("train_start", "train_end"))
    if (start >= end or start != start.normalize() or end != end.normalize()
            or _stamp(fit["train_start"]) != start or _stamp(fit["train_end"]) != end):
        raise ValueError("fit event bounds do not match the request")
    verified = _stamp(report["verification"]["source_verified_at"])
    started, finished = (_stamp(report["clocks"][key])
                         for key in ("fit_started_at", "fit_finished_at"))
    if not verified <= started <= finished:
        raise ValueError("actual verification and fit clocks are inconsistent")


def _stamp(value: object) -> pd.Timestamp:
    if not isinstance(value, str):
        raise ValueError("proxy profile requires an aware event timestamp")
    result = pd.Timestamp(value)
    if pd.isna(result) or result.tzinfo is None:
        raise ValueError("proxy profile requires a finite aware timestamp")
    return result.tz_convert("UTC")


def validate_proxy_model(handle: ModelHandle) -> tuple[FrozenPriceLinear, tuple[str, ...]]:
    """This profile is specific to this producer; other ModelRefs retain their own semantics."""
    report = handle.version.eval_report
    if (not isinstance(report, dict) or set(report) != REPORT_KEYS
            or report["schema"] != PRODUCER_SCHEMA or report["mode"] != PROXY_MODE
            or report["historical_source_availability"] != "UNKNOWN"):
        raise ValueError("a declared price-linear proxy producer profile is required")
    try:
        if len(json.dumps(report, allow_nan=False).encode("utf-8")) > 1024 * 1024:
            raise ValueError("proxy producer report exceeds its bound")
        _report_shapes(report)
        request, fit, source, cutoff = (
            report[key] for key in ("request", "fit", "source", "cutoff"))
        symbols = request["symbols"]
        if (request["schema"] != "price-linear-proxy-train/v1"
                or not isinstance(symbols, list) or not symbols
                or any(not isinstance(s, str) or not s or s != s.strip() for s in symbols)
                or len(set(symbols)) != len(symbols) or len(symbols) > 512
                or tuple(fit["symbols"]) != tuple(symbols)
                or request["bars_snapshot_id"] != handle.version.training_snapshot_id
                or source["record"]["snapshot_id"] != handle.version.training_snapshot_id
                or cutoff["semantics"] != CUTOFF_SEMANTICS):
            raise ValueError("proxy profile source/request binding is inconsistent")
        _fit_report(report, symbols)
        if report["reproducibility"]["code_hash"] != handle.version.code_hash:
            raise ValueError("producer source declaration does not match its committed version")
        model = FrozenPriceLinear.from_json(handle.artifact_bytes)
        pin = _stamp(handle.version.training_as_of)
        if (normalize_as_of(model.max_y_event) > pin
                or _stamp(cutoff["training_as_of"]) != pin
                or _stamp(cutoff["max_y_close"]) != pin
                or _stamp(cutoff["max_x_event"]) != _stamp(model.max_x_event)
                or _stamp(cutoff["max_y_event"]) != _stamp(model.max_y_event)
                or _stamp(fit["max_x_event"]) != _stamp(model.max_x_event)
                or _stamp(fit["max_y_event"]) != _stamp(model.max_y_event)
                or _stamp(model.max_x_event) < _stamp(request["train_start"])
                or _stamp(cutoff["max_x_close"]) >= pin
                or _stamp(model.max_x_event) > _stamp(cutoff["max_x_close"])
                or _stamp(cutoff["max_x_close"]).date() != _stamp(model.max_x_event).date()
                or pin.date() != _stamp(model.max_y_event).date()
                or pin >= _stamp(request["train_end"])):
            raise ValueError("proxy profile observation cutoff does not match its exact pin")
        assert_fit_before(model.scaler, handle.version.training_as_of)
        return model, tuple(symbols)
    except (KeyError, TypeError, OverflowError, RecursionError) as exc:
        raise ValueError("malformed price-linear proxy producer profile") from exc


def score_price_linear(context: AsOfContext, *, model_key: str) -> pd.Series:
    """Pure frozen scoring; the authored execution contract separately skips5 warmup decisions."""
    if model_key not in context.models or "bars" not in context.features:
        raise ValueError("required proxy model and bars must be present")
    model, trained_symbols = validate_proxy_model(context.models[model_key])
    if not set(context.universe) <= set(trained_symbols):
        raise ValueError("scoring universe must be a subset of explicitly trained symbols")
    bars = context.features["bars"].frame
    wide = bars.reset_index().pivot(index="timestamp", columns="symbol", values="adj_close")
    if set(wide.columns) != set(context.universe):
        raise ValueError("required scoring symbols have no bars")
    wide = wide.reindex(columns=list(context.universe)).iloc[-6:]
    features = return_features(wide)  # Validates every consumed price, including early warmup.
    if len(wide) < 6:
        return pd.Series(0.0, index=list(context.universe), dtype="float64")
    latest = features.xs(wide.index[-1], level="event_label")
    predicted = model.predict(latest)
    return pd.Series(predicted.to_numpy(), index=list(context.universe), dtype="float64")
