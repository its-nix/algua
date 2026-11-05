"""Hand-computed frozen inference fixtures, not trained-model or economic evidence."""
from __future__ import annotations

import copy
import json
from dataclasses import FrozenInstanceError

import numpy as np
import pandas as pd
import pytest

from algua.features.dense_network import DenseNetworkError, FrozenDenseNetwork


def payload():
    return {
        "schema": "frozen-dense/v1",
        "features": ["a", "b"],
        "layers": [
            {"weights": [[1, 0], [0, 1]], "bias": [1, -1]},
            {"weights": [[1, -1], [-1, 1]], "bias": [-1, 0.5]},
            {"weights": [[2, -3]], "bias": [0.25]},
        ],
    }


def encode(value):
    return json.dumps(value, allow_nan=False).encode()


def features():
    return pd.DataFrame([[0, 0], [-2, 3], [2, 0]], columns=["a", "b"],
                        index=["CCC", "AAA", "BBB"])


def test_two_relu_hidden_layers_match_hand_computed_values_and_are_nonlinear():
    model = FrozenDenseNetwork.from_json(encode(payload()))
    expected = pd.Series([0.25, -7.25, 4.25], index=features().index,
                         name="prediction", dtype="float64")
    pd.testing.assert_series_equal(model.predict(features()), expected)
    # The second ReLU changes this output: its negative first preactivation must be zero.
    assert model.predict(pd.DataFrame([[-2, 0]], columns=["a", "b"])).iloc[0] == -1.25
    endpoints = pd.DataFrame([[-2, 0], [2, 0]], columns=["a", "b"])
    assert model.predict(endpoints).mean() != expected.iloc[0]


def test_roundtrip_determinism_and_no_mutable_parameter_aliases():
    source = payload()
    model = FrozenDenseNetwork(source["features"], source["layers"])
    before = model.to_json()
    source["layers"][0]["weights"][0][0] = 999
    source["features"][0] = "changed"
    detached = json.loads(model.to_json())
    detached["layers"][0]["bias"][0] = 999
    assert model.to_json() == before
    restored = FrozenDenseNetwork.from_json(before)
    assert restored.to_json() == before
    pd.testing.assert_series_equal(model.predict(features()), restored.predict(features()))
    pd.testing.assert_series_equal(model.predict(features()), model.predict(features()))
    with pytest.raises(FrozenInstanceError):
        model.features = ("changed",)


@pytest.mark.parametrize("change", [
    lambda p: p.update(extra="private"),
    lambda p: p.update(schema="unknown"),
    lambda p: p.update(features=[]),
    lambda p: p.update(features=["a", "a"]),
    lambda p: p.update(features=["a", True]),
    lambda p: p.update(features=[" a", "b"]),
    lambda p: p.update(features=["a"] * 33),
    lambda p: p.update(layers=p["layers"][:2]),
    lambda p: p.update(layers=p["layers"] + p["layers"][:1]),
    lambda p: p["layers"][0].update(extra=0),
    lambda p: p["layers"][0].update(weights=[[1]]),
    lambda p: p["layers"][0].update(weights=[]),
    lambda p: p["layers"][0].update(bias=[0]),
    lambda p: p["layers"][0].update(weights=[[True, 0], [0, 1]]),
    lambda p: p["layers"][0].update(bias=["1", 0]),
    lambda p: p["layers"][1].update(weights=[[1, 0]] * 33, bias=[0] * 33),
    lambda p: p["layers"][2].update(weights=[[1, 0], [0, 1]], bias=[0, 0]),
])
def test_closed_model_shape_and_dimensions_refuse(change):
    value = copy.deepcopy(payload())
    change(value)
    with pytest.raises(DenseNetworkError):
        FrozenDenseNetwork.from_json(encode(value))


@pytest.mark.parametrize("raw", [
    b"[]", b"null", b"not json", b"\xff", b" " * (64 * 1024 + 1),
    b'{"schema":"frozen-dense/v1","schema":"frozen-dense/v1"}',
    b'{"layers":[{"weights":[],"weights":[]}]}',
])
def test_invalid_ambiguous_or_oversized_json_refuses(raw):
    with pytest.raises(DenseNetworkError):
        FrozenDenseNetwork.from_json(raw)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 10**400])
def test_nonfinite_or_unrepresentable_parameters_refuse(value):
    source = payload()
    source["layers"][0]["bias"][0] = value
    with pytest.raises(DenseNetworkError):
        FrozenDenseNetwork.from_json(json.dumps(source).encode())


@pytest.mark.parametrize("value", [True, "1", None, float("nan"), float("inf"), 1 + 0j])
def test_nonreal_or_nonfinite_features_refuse(value):
    frame = features().astype(object)
    frame.iloc[0, 0] = value
    with pytest.raises(DenseNetworkError):
        FrozenDenseNetwork.from_json(encode(payload())).predict(frame)


@pytest.mark.parametrize("frame", [
    pd.DataFrame([[1, 2]], columns=["b", "a"]),
    pd.DataFrame([[1, 2]], columns=["a", "a"]),
    pd.DataFrame([[1]], columns=["a"]),
    pd.DataFrame(columns=["a", "b"]),
    pd.DataFrame([[1, 2], [2, 3]], columns=["a", "b"], index=["same", "same"]),
    pd.DataFrame(np.zeros((4097, 2)), columns=["a", "b"]),
])
def test_feature_geometry_and_order_refuse(frame):
    with pytest.raises(DenseNetworkError):
        FrozenDenseNetwork.from_json(encode(payload())).predict(frame)


def test_finite_inputs_that_overflow_a_layer_refuse():
    value = payload()
    value["layers"][0]["weights"][0][0] = 1e308
    model = FrozenDenseNetwork.from_json(encode(value))
    with pytest.raises(DenseNetworkError):
        model.predict(pd.DataFrame([[1e308, 0]], columns=["a", "b"]))


def test_apply_and_codec_do_not_access_files(monkeypatch):
    model = FrozenDenseNetwork.from_json(encode(payload()))
    frame = features()

    def forbidden(*args, **kwargs):
        raise AssertionError("frozen inference must not read or write files")

    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr(np, "load", forbidden)
    model.predict(frame)
    FrozenDenseNetwork.from_json(model.to_json()).predict(frame)
