"""Synthetic apply/codec checks; no registered model, data source or inference runtime."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from dataclasses import FrozenInstanceError

import numpy as np
import pandas as pd
import pytest

from algua.features.price_linear import FEATURE_ORDER, FrozenPriceLinear, return_features
from algua.features.scaling import STANDARD, FrozenScaler


def scaler():
    return FrozenScaler(kind=STANDARD, columns=FEATURE_ORDER,
        params={"return_1": {"mean": 0.1, "std": 0.2},
                "return_5": {"mean": 0.3, "std": 0.4}},
        fit_max_timestamp="2024-02-01T00:00:00+00:00")


def model():
    return FrozenPriceLinear(scaler(), [2.0, -1.0], 0.5,
                             max_y_event="2024-02-02T00:00:00+00:00")


def prices():
    return pd.DataFrame({"BBB": [2., 4., 8., 16., 32., 64., 128.],
                         "AAA": [3., 9., 27., 81., 243., 729., 2187.]},
                        index=pd.date_range("2024-01-01", periods=7, tz="UTC"))


def test_observed_return_features_keep_explicit_warmup_and_symbol_order():
    frame = prices()
    result = return_features(frame)
    assert tuple(result.columns) == FEATURE_ORDER
    assert result.index.names == ["event_label", "symbol"]
    assert result.index[:4].tolist() == [(frame.index[0], "BBB"), (frame.index[0], "AAA"),
                                       (frame.index[1], "BBB"), (frame.index[1], "AAA")]
    assert result.iloc[:2].isna().all().all()
    assert result.iloc[:10]["return_5"].isna().all()
    np.testing.assert_array_equal(result.iloc[10:].to_numpy(), [[1., 31.], [2., 242.]] * 2)
    np.testing.assert_array_equal(result.iloc[2:]["return_1"], [1., 2.] * 6)


def test_apply_uses_fixed_standard_scaler_and_preserves_input_order():
    features = pd.DataFrame([[0.1, 0.3], [0.3, 0.7]], columns=FEATURE_ORDER,
                            index=["later", "earlier"])
    actual = model().predict(features)
    pd.testing.assert_series_equal(actual, pd.Series([0.5, 1.5], index=features.index,
                                                    name="prediction", dtype="float64"))


def test_frozen_boundary_detaches_all_mutable_inputs_and_outputs():
    source, coefficients = scaler(), [2., -1.]
    frozen = FrozenPriceLinear(source, coefficients, 0.5,
                               max_y_event="2024-02-02T00:00:00Z")
    before = frozen.to_json()
    source.params["return_1"]["mean"] = 123
    coefficients[0] = 123
    frozen.scaler.params["return_5"]["std"] = 123
    exported = frozen.to_dict()
    exported["scaler"]["params"]["return_1"]["mean"] = 123
    exported["coefficients"][0] = 123
    assert frozen.to_json() == before
    assert isinstance(frozen.coefficients, tuple)
    with pytest.raises(FrozenInstanceError):
        frozen.intercept = 2


def test_codec_is_canonical_and_roundtrip_deterministic():
    frozen = model()
    raw = frozen.to_json()
    assert raw == json.dumps(frozen.to_dict(), sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()
    assert FrozenPriceLinear.from_json(raw).to_json() == raw
    assert set(json.loads(raw)) == {"schema", "recipe", "features", "scaler", "coefficients",
                                    "intercept", "observed_events"}
    assert b"training_as_of" not in raw and b"known_at" not in raw


@pytest.mark.parametrize("path,value", [
    (("schema",), "price-linear/v2"), (("recipe",), "other"),
    (("features",), ["return_5", "return_1"]),
    (("features",), ["return_1", "return_1"]),
    (("coefficients",), [1]), (("coefficients",), [True, 2]),
    (("coefficients",), [1, float("inf")]), (("intercept",), True),
    (("intercept",), "1"), (("intercept",), None),
    (("scaler", "kind"), "robust"),
    (("scaler", "columns"), ["return_5", "return_1"]),
    (("scaler", "params", "return_1", "mean"), True),
    (("scaler", "params", "return_5", "std"), 0),
    (("scaler", "params", "return_5", "std"), -1),
    (("scaler", "params", "return_5", "std"), float("nan")),
    (("scaler", "fit_max_timestamp"), "NaT"),
    (("scaler", "fit_max_timestamp"), "2024-02-01"),
    (("observed_events", "max_x_event"), "2024-01-31T00:00:00Z"),
    (("observed_events", "max_y_event"), "2024-02-01T00:00:00Z"),
    (("observed_events", "max_y_event"), "NaT"),
    (("observed_events", "max_y_event"), False),
])
def test_codec_rejects_invalid_fields(path, value):
    blob = model().to_dict()
    target = blob
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        FrozenPriceLinear.from_json(json.dumps(blob).encode())


@pytest.mark.parametrize("path", [(), ("scaler",), ("scaler", "params"),
                                  ("scaler", "params", "return_1"), ("observed_events",)])
def test_codec_is_closed_at_every_mapping(path):
    blob = model().to_dict()
    target = blob
    for key in path:
        target = target[key]
    target["unexpected"] = 1
    with pytest.raises(ValueError):
        FrozenPriceLinear.from_json(json.dumps(blob).encode())


@pytest.mark.parametrize("raw", [b'{}', b'[]', b'null', b'"text"', b'\xff',
    b'{"schema":"x","schema":"x"}', b'{"outer":{"mean":0,"mean":0}}'])
def test_malformed_json_and_duplicate_keys_at_any_depth_refuse(raw):
    with pytest.raises(ValueError):
        FrozenPriceLinear.from_json(raw)


def test_overflow_duplicate_in_valid_envelope_and_fixed_decode_cap():
    raw = model().to_json()
    for bad in [raw.replace(b'"intercept":0.5', b'"intercept":1e400'),
                raw.replace(b'"mean":0.1', b'"mean":0.1,"mean":0.2'),
                raw + b' ' * (64 * 1024 - len(raw) + 1), bytearray(raw), raw.decode()]:
        with pytest.raises(ValueError):
            FrozenPriceLinear.from_json(bad)
    padded = raw + b' ' * (64 * 1024 - len(raw))
    assert FrozenPriceLinear.from_json(padded).to_json() == raw


@pytest.mark.parametrize("value", [True, "1", None, np.nan, np.inf, 1 + 0j, 1 + 2j])
def test_apply_requires_finite_real_numeric_features(value):
    frame = pd.DataFrame([[value, 0.3]], columns=FEATURE_ORDER)
    with pytest.raises(ValueError):
        model().predict(frame)


@pytest.mark.parametrize("columns", [["return_5", "return_1"], ["return_1", "return_1"],
                                    ["return_1"], ["return_1", "return_5", "extra"]])
def test_apply_never_silently_reorders_or_drops_columns(columns):
    with pytest.raises(ValueError):
        model().predict(pd.DataFrame([[1.] * len(columns)], columns=columns))


def test_apply_refuses_empty_or_numerical_overflow():
    with pytest.raises(ValueError):
        model().predict(pd.DataFrame(columns=FEATURE_ORDER))
    with pytest.raises(ValueError):
        model().predict(pd.DataFrame([[1e308, 0.3]], columns=FEATURE_ORDER))


@pytest.mark.parametrize("kind", ["naive", "nonutc", "duplicate", "reverse", "nat", "plain",
                                 "symbol_duplicate", "symbol_empty", "symbol_numeric", "empty"])
def test_price_geometry_refuses_ambiguous_event_or_symbol_shape(kind):
    frame = prices()
    if kind == "naive":
        frame.index = frame.index.tz_localize(None)
    elif kind == "nonutc":
        frame.index = frame.index.tz_convert("America/New_York")
    elif kind == "duplicate":
        frame.index = pd.DatetimeIndex([frame.index[0]] * len(frame))
    elif kind == "reverse":
        frame = frame.iloc[::-1]
    elif kind == "nat":
        frame.index = pd.DatetimeIndex([pd.NaT, *frame.index[1:]])
    elif kind == "plain":
        frame.index = range(len(frame))
    elif kind == "symbol_duplicate":
        frame.columns = ["AAA", "AAA"]
    elif kind == "symbol_empty":
        frame.columns = ["AAA", " "]
    elif kind == "symbol_numeric":
        frame.columns = ["AAA", 1]
    else:
        frame = frame.iloc[:0]
    with pytest.raises(ValueError):
        return_features(frame)


def test_consumed_price_caps_refuse_before_feature_materialization():
    for rows, columns in [(100_001, 1), (1, 513), (4000, 501)]:
        frame = pd.DataFrame(np.ones((rows, columns)),
            index=pd.date_range("2024-01-01", periods=rows, freq="s", tz="UTC"),
            columns=[f"S{i}" for i in range(columns)])
        with pytest.raises(ValueError):
            return_features(frame)


def test_explicit_zero_imaginary_price_representation_is_value_preserving():
    frame = prices()
    pd.testing.assert_frame_equal(return_features(frame.astype(complex)), return_features(frame))
    frame.iloc[1, 0] = np.finfo(float).tiny
    frame.iloc[2, 0] = np.finfo(float).max
    with pytest.raises(ValueError):
        return_features(frame)


def test_apply_codec_and_features_do_not_call_io(monkeypatch):
    from pathlib import Path

    frozen, frame = model(), prices()
    features = return_features(frame).iloc[10:]
    expected = frozen.predict(features)

    def forbidden(*args, **kwargs):
        pytest.fail("pure numerical component attempted IO")

    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(pd, "read_csv", forbidden)
    monkeypatch.setattr(pd, "read_pickle", forbidden)
    restored = FrozenPriceLinear.from_json(frozen.to_json())
    pd.testing.assert_series_equal(restored.predict(return_features(frame).iloc[10:]), expected)


def test_cold_serve_import_has_no_fit_or_higher_layer_imports():
    code = '''
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("algua.training", "algua.features.scaling_fit", "algua.models",
            "algua.registry", "algua.strategies", "algua.data", "algua.cli", "mlflow")):
            raise AssertionError(fullname)
sys.meta_path.insert(0, Block())
from algua.features.price_linear import FrozenPriceLinear, return_features
assert callable(return_features) and callable(FrozenPriceLinear.from_json)
'''
    result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True,
                            text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_constructor_rejects_unknown_nested_scaler_declarations():
    source = scaler()
    source.params["return_1"]["unknown"] = 1
    with pytest.raises(ValueError):
        FrozenPriceLinear(source, [1., 2.], 0., max_y_event="2024-02-02T00:00:00Z")
    source = scaler()
    source.params["unknown"] = copy.deepcopy(source.params["return_1"])
    with pytest.raises(ValueError):
        FrozenPriceLinear(source, [1., 2.], 0., max_y_event="2024-02-02T00:00:00Z")
