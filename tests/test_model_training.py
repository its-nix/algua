"""Source integrity/session split tests on local labelled fixtures, never market acceptance."""
from __future__ import annotations

import json

import pandas as pd
import pytest

from algua.cli._model_train_request import parse_request
from algua.cli._model_train_source import capture_source
from algua.data.store import DataStore
from tests.test_cli_model_training import invoke, make_source


def request_at(path):
    return parse_request(path.read_bytes())


def test_consumed_slice_partition_and_future_vintage_invariance(tmp_path, monkeypatch):
    from algua.models import get_version_with_bytes

    def future_changed(frame):
        frame.loc[frame["timestamp"] >= dates[16], "adj_close"] *= 1.5
        return frame

    first_dir = tmp_path / "first"
    first_dir.mkdir()
    data, path, _, _, dates, _ = make_source(first_dir, monkeypatch)
    assert invoke("train-linear", "vintage", "--request", str(path))[0] == 0
    version1, bytes1 = get_version_with_bytes("vintage", 1, root=data / "models")
    other = tmp_path / "second"
    other.mkdir()
    data2, path2, *_ = make_source(other, monkeypatch, mutate=future_changed)
    assert invoke("train-linear", "vintage", "--request", str(path2))[0] == 0
    version2, bytes2 = get_version_with_bytes("vintage", 1, root=data2 / "models")
    assert bytes1 == bytes2
    assert version1.training_snapshot_id != version2.training_snapshot_id
    assert version1.provenance_digest != version2.provenance_digest
    assert version1.eval_report["verification"]["consumed_prices_sha256"] == (
        version2.eval_report["verification"]["consumed_prices_sha256"])
    fit = version1.eval_report["fit"]
    assert (fit["candidate_observations"], fit["warmup_observations"],
            fit["unlabelled_observations"], fit["fitted_observations"]) == (32, 10, 2, 20)


@pytest.mark.parametrize("fault", ["missing_one", "missing_date", "weekend", "zero", "infinite"])
def test_bad_consumed_grid_or_prices_refuse_without_registration(tmp_path, monkeypatch, fault):
    def broken(frame):
        stamp = frame["timestamp"].unique()[7]
        if fault == "missing_one":
            return frame[~((frame["timestamp"] == stamp) & (frame["symbol"] == "AAA"))]
        if fault == "missing_date":
            return frame[frame["timestamp"] != stamp]
        if fault == "weekend":
            frame.loc[frame["timestamp"] == stamp, "timestamp"] = pd.Timestamp(
                "2024-01-13T00:00:00Z")
        else:
            frame.loc[frame["timestamp"] == stamp, "adj_close"] = (
                0.0 if fault == "zero" else float("inf"))
        return frame

    data, path, *_ = make_source(tmp_path, monkeypatch, mutate=broken)
    code, payload = invoke("train-linear", "bad", "--request", str(path))
    assert code == 1 and payload["ok"] is False
    assert not (data / "models").exists()


def test_physical_readable_payload_rewrite_is_not_accepted_as_same_hash(tmp_path, monkeypatch):
    import pyarrow as pa
    import pyarrow.parquet as pq

    data, path, _, record, *_ = make_source(tmp_path, monkeypatch)
    parquet = next((data / record.data_path).rglob("*.parquet"))
    table = pq.ParquetFile(parquet).read()
    values = table["adj_close"].to_pylist()
    values[0] += 0.125
    table = table.set_column(table.schema.get_field_index("adj_close"),
                             "adj_close", pa.array(values))
    pq.write_table(table, parquet)
    store = DataStore(data)
    store.verify_snapshot(record)  # Readability/row count passes; logical identity must still fail.
    with pytest.raises(ValueError, match="content identity"):
        capture_source(store, request_at(path))


def test_legacy_provenance_or_future_source_clock_is_not_relabelled(tmp_path, monkeypatch):
    data, path, *_ = make_source(tmp_path, monkeypatch)
    manifest = data / "manifest.jsonl"
    original = json.loads(manifest.read_text())
    for fault in ("unknown", "future"):
        record = dict(original)
        if fault == "unknown":
            record["source_metadata"] = {}
        else:
            record["as_of"] = "2100-01-01T00:00:00Z"
        manifest.write_text(json.dumps(record) + "\n")
        code, payload = invoke("train-linear", "bad", "--request", str(path))
        assert code == 1 and payload["ok"] is False
        assert not (data / "models").exists()


def test_source_capture_is_read_only_and_revalidates_metadata(tmp_path, monkeypatch):
    data, path, *_ = make_source(tmp_path, monkeypatch)
    manifest = data / "manifest.jsonl"
    before = manifest.read_bytes()
    captured = capture_source(DataStore(data), request_at(path))
    assert manifest.read_bytes() == before
    changed = json.loads(before)
    changed["created_at"] = "2000-01-01T00:00:00Z"
    manifest.write_text(json.dumps(changed) + "\n")
    with pytest.raises(ValueError, match="changed"):
        captured.revalidate()
    assert not (data / "models").exists()
