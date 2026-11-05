"""Actual local CLI on labelled synthetic bars; no market or autonomous-cycle evidence."""
from __future__ import annotations

import contextlib
import io
import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from algua.calendar.market_calendar import MarketCalendar
from algua.config.settings import Settings
from algua.data.research_provenance import DataTier, ProvenanceDeclaration
from algua.data.store import DataStore


def invoke(*args):
    from algua.cli.main import main

    output = io.StringIO()
    with contextlib.redirect_stdout(output), pytest.raises(SystemExit) as stopped:
        main(["model", *args])
    return stopped.value.code, json.loads(output.getvalue())


@pytest.fixture
def source(tmp_path, monkeypatch):
    return make_source(tmp_path, monkeypatch)


def make_source(tmp_path, monkeypatch, *, count=24, mutate=None):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    data = tmp_path / "data"
    monkeypatch.setenv("ALGUA_DATA_DIR", str(data))
    monkeypatch.setenv("ALGUA_DB_PATH", str(data / "algua.db"))
    monkeypatch.setenv("ALGUA_MLFLOW_TRACKING_URI", f"sqlite:///{data / 'tracking.db'}")
    calendar = MarketCalendar("XNYS")
    sessions = calendar.sessions_in_range(date(2024, 1, 2), date(2024, 3, 1))[:count]
    dates = pd.DatetimeIndex(sessions, tz="UTC", name="timestamp")
    rows = []
    for i, stamp in enumerate(dates):
        for j, symbol in enumerate(("AAA", "BBB")):
            price = 100.0 + i * (0.2 + j * 0.1) + np.sin(i * 0.7 + j)
            rows.append({"timestamp": stamp, "symbol": symbol, "open": price * 0.999,
                         "high": price * 1.01, "low": price * 0.99, "close": price,
                         "adj_close": price, "volume": 1_000_000.0})
    frame = pd.DataFrame(rows)
    if mutate is not None:
        frame = mutate(frame)
    store = DataStore(data)
    record = store.ingest_bars(
        provider="fixture", symbols=["AAA", "BBB"], start=sessions[0].isoformat(),
        end=(sessions[-1] + timedelta(days=1)).isoformat(), as_of="2025-03-01T00:00:00Z",
        source="SYNTHETIC_FIXTURE", frame=frame, timeframe="1d", adjustment="none",
        source_metadata={"PRIVATE_SOURCE_NOTE": "do-not-print-source-note"},
        provenance=ProvenanceDeclaration(DataTier.SYNTHETIC_FIXTURE, "linear-producer-fixture/v1",
                                        ("synthetic_not_market_data",)))
    request = {"schema": "price-linear-proxy-train/v1", "bars_snapshot_id": record.snapshot_id,
               "symbols": ["BBB", "AAA"], "train_start": dates[0].isoformat(),
               "train_end": dates[16].isoformat(), "l2": 0.001}
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    return data, path, request, record, dates, calendar


def test_actual_cli_trains_registers_and_emits_pinned_proxy_model(source):
    from algua.features.price_linear import FrozenPriceLinear
    from algua.models import get_version_with_bytes

    data, path, request, record, dates, calendar = source
    code, payload = invoke("train-linear", "synthetic-linear", "--request", str(path))
    assert code == 0, payload
    version, raw = get_version_with_bytes("synthetic-linear", 1, root=data / "models")
    assert {key: payload[key] for key in version.as_ref().as_dict()} == version.as_ref().as_dict()
    assert payload["training_snapshot_id"] == record.snapshot_id
    assert payload["seed"] is None
    assert payload["training_as_of"] == calendar.session_close(dates[15].date()).isoformat()
    assert payload["proxy"] == {
        "mode": "fixed_vintage_historical_proxy",
        "cutoff_semantics": "complete_target_xnys_close/v1",
        "historical_source_availability": "UNKNOWN", "data_tier": "synthetic_fixture",
        "limitations": ["synthetic_not_market_data"],
    }
    assert payload["fit"]["fitted_observations"] == 20
    assert version.eval_report["request"] == request
    assert version.eval_report["source"]["record"] == record.to_dict()
    assert FrozenPriceLinear.from_json(raw).max_y_event == dates[15].isoformat()
    assert not (data / "algua.db").exists() and not (data / "tracking.db").exists()
    assert "artifact_path" not in payload and "eval_report" not in payload
    assert "do-not-print-source-note" not in json.dumps(payload)


@pytest.mark.parametrize("field,value", [
    ("schema", "other"), ("bars_snapshot_id", False), ("bars_snapshot_id", ""),
    ("bars_snapshot_id", "x" * 129), ("symbols", []), ("symbols", ["AAA", "AAA"]),
    ("symbols", ["AAA", False]), ("symbols", [" "]), ("symbols", "AAA"),
    ("train_start", "2024-01-02"), ("train_end", "NaT"), ("train_start", False),
    ("train_start", "2024-01-02T12:00:00Z"), ("l2", True), ("l2", "0.1"),
    ("l2", None), ("l2", 0), ("l2", -1), ("l2", float("inf")), ("l2", 10 ** 1000),
])
def test_invalid_request_refuses_before_source_or_model_mutation(source, monkeypatch, field, value):
    import algua.cli._model_training as producer

    data, path, request, *_ = source
    request[field] = value
    path.write_text(json.dumps(request), encoding="utf-8")

    def forbidden(*args, **kwargs):
        pytest.fail("invalid request reached source capture")

    monkeypatch.setattr(producer, "capture_source", forbidden)
    code, payload = invoke("train-linear", "synthetic-linear", "--request", str(path))
    assert code == 1 and payload["code"] == "invalid_input"
    assert not (data / "models").exists()


@pytest.mark.parametrize("fault", ["extra", "missing", "duplicate", "nested_duplicate",
                                  "overflow", "encoding", "too_big", "directory"])
def test_closed_bounded_request_json_errors(source, fault):
    data, path, request, *_ = source
    raw = json.dumps(request).encode()
    if fault == "extra":
        request["training_as_of"] = "2000-01-01T00:00:00Z"
        raw = json.dumps(request).encode()
    elif fault == "missing":
        request.pop("l2")
        raw = json.dumps(request).encode()
    elif fault == "duplicate":
        raw = b'{"l2":2,' + raw[1:]
    elif fault == "nested_duplicate":
        raw = raw.replace(b'"l2": 0.001', b'"l2":{"x":1,"x":2}')
    elif fault == "overflow":
        raw = raw.replace(b'"l2": 0.001', b'"l2":1e400')
    elif fault == "encoding":
        raw = b'\xff'
    elif fault == "too_big":
        raw += b' ' * (64 * 1024 + 1)
    elif fault == "directory":
        path = path.parent
    if fault != "directory":
        path.write_bytes(raw)
    code, payload = invoke("train-linear", "synthetic-linear", "--request", str(path))
    assert code == 1 and payload["code"] == "invalid_input"
    assert not (data / "models").exists()


def test_repeated_fit_is_same_numerical_artifact_new_version_and_true_clocks(source):
    from algua.models import get_version_with_bytes

    data, path, *_ = source
    assert invoke("train-linear", "same", "--request", str(path))[0] == 0
    assert invoke("train-linear", "same", "--request", str(path))[0] == 0
    first, raw1 = get_version_with_bytes("same", 1, root=data / "models")
    second, raw2 = get_version_with_bytes("same", 2, root=data / "models")
    assert raw1 == raw2 and first.digest == second.digest
    assert first.provenance_digest != second.provenance_digest
    assert first.seed is second.seed is None
    assert first.training_as_of < first.eval_report["clocks"]["fit_started_at"]
    assert first.eval_report["verification"]["consumed_prices_sha256"] == (
        second.eval_report["verification"]["consumed_prices_sha256"])
    assert invoke("show", "same", "--version", "1")[1]["digest"] == first.digest
    assert len(invoke("list", "same")[1]["versions"]) == 2


def test_source_drift_after_fit_retains_source_and_publishes_no_model(source, monkeypatch):
    import algua.training.price_linear as numerical

    data, path, _, record, *_ = source
    original = numerical.fit_price_linear

    def changing(*args, **kwargs):
        result = original(*args, **kwargs)
        (data / record.data_path / "changed-during-fit").write_text("fixture")
        return result

    monkeypatch.setattr(numerical, "fit_price_linear", changing)
    code, payload = invoke("train-linear", "drift", "--request", str(path))
    assert code == 1 and "changed" in payload["error"]
    assert (data / record.data_path).exists() and not (data / "models").exists()


def test_registration_failure_is_reported_without_retry(source, monkeypatch):
    from algua import models

    data, path, *_ = source
    calls = []

    def unavailable(*args, **kwargs):
        calls.append(args)
        raise models.ModelRegistryError("fixture registration failure")

    monkeypatch.setattr(models, "register", unavailable)
    code, payload = invoke("train-linear", "unavailable", "--request", str(path))
    assert code == 1 and payload["ok"] is False and len(calls) == 1
    assert not (data / "models").exists()
