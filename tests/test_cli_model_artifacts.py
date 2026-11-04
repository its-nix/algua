"""Local opaque fixture artifacts only; never model training, loading or qualification."""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys

import pytest

from algua.cli.main import main
from algua.models import get_version


def invoke(*args):
    output = io.StringIO()
    with contextlib.redirect_stdout(output), pytest.raises(SystemExit) as stopped:
        main(["model", *args])
    return stopped.value.code, json.loads(output.getvalue()), output.getvalue()


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("ALGUA_DATA_DIR", str(data))
    monkeypatch.setenv("ALGUA_DB_PATH", str(data / "algua.db"))
    monkeypatch.setenv("ALGUA_MLFLOW_TRACKING_URI", f"sqlite:///{data / 'tracking.db'}")
    artifact = tmp_path / "opaque.bin"
    artifact.write_bytes(b"SYNTHETIC_FIXTURE opaque bytes\x00\x01")
    metadata = {
        "training_snapshot_id": "declared-snapshot", "training_as_of": "2026-01-02",
        "code_hash": None, "hyperparameters": {"PRIVATE_INPUT": "DO_NOT_PRINT"},
        "seed": 0, "eval_report": {"PRIVATE_DIAGNOSTIC": "DO_NOT_PRINT"},
    }
    path = tmp_path / "metadata.json"
    path.write_text(json.dumps(metadata), encoding="utf-8")
    return data, artifact, path, metadata


def register(inputs, name="fixture"):
    _, artifact, metadata, _ = inputs
    return invoke("register", name, "--artifact", str(artifact), "--metadata", str(metadata))


def child_register(artifact, metadata):
    bootstrap = ("from algua.config.settings import Settings; "
                 "Settings.model_config['env_file']=None; "
                 "from algua.cli.main import main; main()")
    return subprocess.run([sys.executable, "-c", bootstrap, "model", "register", "fixture",
        "--artifact", str(artifact), "--metadata", str(metadata)],
        capture_output=True, text=True, timeout=10, env=os.environ.copy())


def test_actual_main_local_model_route_and_exact_roundtrip(inputs):
    data, artifact, _, metadata = inputs
    code, payload, output = register(inputs)
    assert code == 0, output
    version = get_version("fixture", 1, root=data / "models")
    expected = version.as_ref().as_dict() | {key: getattr(version, key) for key in (
        "created_at", "training_snapshot_id", "code_hash", "seed")}
    assert payload == {"ok": True, **expected}
    assert len(payload["digest"]) == len(payload["provenance_digest"]) == 16
    assert version.hyperparameters == metadata["hyperparameters"]
    assert version.eval_report == metadata["eval_report"]
    assert (data / "models/fixture/v1/artifact.bin").read_bytes() == artifact.read_bytes()
    assert "DO_NOT_PRINT" not in output and "artifact_path" not in output
    assert invoke("show", "fixture", "--version", "1")[:2] == (0, payload)
    assert invoke("list", "fixture")[:2] == (0, {"ok": True, "versions": [expected]})
    assert sorted(p.name for p in data.iterdir()) == ["models"]


def test_missing_list_is_read_only(inputs):
    data, _, _, _ = inputs
    assert invoke("list", "absent")[:2] == (0, {"ok": True, "versions": []})
    assert not data.exists()


@pytest.mark.parametrize("field,value", [
    ("training_snapshot_id", False), ("code_hash", 9), ("training_as_of", None),
    ("training_as_of", "NaT"), ("training_as_of", ""), ("training_as_of", "not-a-date"),
    ("hyperparameters", []), ("eval_report", "private"), ("seed", True),
    ("seed", 1.5), ("seed", "1"),
])
def test_metadata_types_refuse_before_store_mutation(inputs, field, value):
    data, _, path, metadata = inputs
    metadata[field] = value
    path.write_text(json.dumps(metadata), encoding="utf-8")
    code, payload, _ = register(inputs)
    assert code == 1 and payload["code"] == "invalid_input"
    assert not data.exists()


@pytest.mark.parametrize("fault", ["missing", "extra", "array", "syntax", "encoding"])
def test_closed_utf8_metadata_refuses_before_mutation(inputs, fault):
    data, _, path, metadata = inputs
    if fault == "missing":
        metadata.pop("seed")
    elif fault == "extra":
        metadata["version"] = 7
    if fault in {"missing", "extra"}:
        raw = json.dumps(metadata).encode()
    else:
        raw = {"array": b"[]", "syntax": b"{broken", "encoding": b"\xff"}[fault]
    path.write_bytes(raw)
    code, payload, _ = register(inputs)
    assert code == 1 and payload["code"] == "invalid_input"
    assert not data.exists()


@pytest.mark.parametrize("nested", [False, True])
def test_duplicate_fields_at_any_depth_refuse_before_mutation(inputs, nested):
    data, _, path, metadata = inputs
    raw = json.dumps(metadata)
    if nested:
        raw = raw.replace('"hyperparameters": {', '"hyperparameters": {"x":1,"x":2,')
    else:
        raw = '{"seed":999,' + raw[1:]
    path.write_text(raw, encoding="utf-8")
    code, payload, _ = register(inputs)
    assert code == 1 and payload["code"] == "invalid_input"
    assert not data.exists()


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e400", "-1e400"])
def test_recursive_nonfinite_values_refuse_before_mutation(inputs, number):
    data, _, path, metadata = inputs
    metadata["eval_report"] = {"opaque": [{"number": "REPLACE"}]}
    path.write_text(json.dumps(metadata).replace('"REPLACE"', number), encoding="utf-8")
    code, payload, _ = register(inputs)
    assert code == 1 and payload["code"] == "invalid_input"
    assert not data.exists()


@pytest.mark.parametrize("cutoff", ["2026-01-02", "2026-01-02T12:34:56",
    "2026-01-02T12:34:56-05:00", "2100-01-01"])
def test_original_cutoff_and_nullable_api_values_survive(inputs, cutoff):
    data, _, path, metadata = inputs
    metadata.update(training_as_of=cutoff, training_snapshot_id=None, code_hash=None,
                    hyperparameters=None, eval_report=None, seed=None)
    path.write_text(json.dumps(metadata), encoding="utf-8")
    code, payload, _ = register(inputs)
    assert code == 0 and payload["training_as_of"] == cutoff
    version = get_version("fixture", 1, root=data / "models")
    assert version.hyperparameters == version.eval_report == {}
    assert version.seed is None and version.training_as_of == cutoff


def test_finite_integer_seed_is_not_silently_limited_to_float_range(inputs):
    _, _, path, metadata = inputs
    metadata["seed"] = 10 ** 400
    path.write_text(json.dumps(metadata), encoding="utf-8")
    code, payload, _ = register(inputs)
    assert code == 0 and payload["seed"] == 10 ** 400


def test_exact_metadata_and_artifact_materialization_boundaries(inputs):
    data, artifact, path, metadata = inputs
    metadata["hyperparameters"] = {"unicode": "雪", "padding": ""}
    raw = json.dumps(metadata, ensure_ascii=False).encode()
    metadata["hyperparameters"]["padding"] = "x" * (1024 * 1024 - len(raw))
    raw = json.dumps(metadata, ensure_ascii=False).encode()
    assert len(raw) == 1024 * 1024
    path.write_bytes(raw)
    with artifact.open("wb") as stream:
        stream.truncate(64 * 1024 * 1024)
    code, payload, output = register(inputs)
    assert code == 0 and payload["version"] == 1 and len(output.encode()) < 2048
    assert (data / "models/fixture/v1/artifact.bin").stat().st_size == 64 * 1024 * 1024


@pytest.mark.parametrize("which,limit", [("metadata", 1024 * 1024),
                                       ("artifact", 64 * 1024 * 1024)])
def test_oversized_input_refuses_before_store_mutation(inputs, which, limit):
    data, artifact, metadata, declaration = inputs
    if which == "metadata":
        declaration["hyperparameters"] = {"padding": ""}
        size = len(json.dumps(declaration).encode())
        declaration["hyperparameters"]["padding"] = "x" * (limit + 1 - size)
        raw = json.dumps(declaration).encode()
        assert len(raw) == limit + 1
        metadata.write_bytes(raw)
    else:
        with artifact.open("wb") as stream:
            stream.truncate(limit + 1)
    code, payload, _ = register(inputs)
    assert code == 1 and payload["code"] == "invalid_input"
    assert not data.exists()


@pytest.mark.parametrize("which", ["metadata", "artifact"])
@pytest.mark.parametrize("kind", ["directory", "fifo"])
def test_nonregular_input_refuses_without_fifo_hang(inputs, which, kind):
    data, artifact, metadata, _ = inputs
    path = artifact if which == "artifact" else metadata
    path.unlink()
    path.mkdir() if kind == "directory" else os.mkfifo(path)
    result = child_register(artifact, metadata)
    assert result.returncode == 1 and json.loads(result.stdout)["ok"] is False
    assert not data.exists()


@pytest.mark.parametrize("which", ["metadata", "artifact"])
def test_fifo_with_valid_input_bytes_is_still_refused(inputs, which):
    data, artifact, metadata, _ = inputs
    path = artifact if which == "artifact" else metadata
    raw = path.read_bytes()
    path.unlink()
    os.mkfifo(path)
    writer_code = """import os, sys
fd = os.open(sys.argv[1], os.O_WRONLY)
try:
    os.write(fd, bytes.fromhex(sys.argv[2]))
except BrokenPipeError:
    pass
finally:
    os.close(fd)
"""
    writer = subprocess.Popen([sys.executable, "-c", writer_code, str(path), raw.hex()],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        result = child_register(artifact, metadata)
    finally:
        if writer.poll() is None:
            writer.kill()
        writer.wait(timeout=5)
    assert writer.returncode is not None
    assert result.returncode == 1 and json.loads(result.stdout)["ok"] is False
    assert not data.exists()


def test_regular_input_symlinks_preserve_ordinary_local_file_semantics(inputs, tmp_path):
    _, artifact, metadata, _ = inputs
    linked = tmp_path / "linked.bin"
    linked.symlink_to(artifact)
    assert invoke("register", "fixture", "--artifact", str(linked),
                  "--metadata", str(metadata))[0] == 0


@pytest.mark.parametrize("name", ["", ".hidden", " name ", "a/b", "a\\b"])
def test_existing_registry_name_refusal_is_preserved(inputs, name):
    data, _, _, _ = inputs
    code, payload, _ = register(inputs, name)
    assert code == 1 and payload["code"] == "internal"
    assert not data.exists()


def test_existing_broader_name_policy_is_preserved(inputs):
    code, payload, _ = register(inputs, "Mödel with spaces")
    assert code == 0 and payload["name"] == "Mödel with spaces"


@pytest.mark.parametrize("fault", ["missing-artifact", "missing-metadata", "empty"])
def test_file_and_empty_artifact_errors_are_json_without_store_mutation(inputs, fault):
    data, artifact, metadata, _ = inputs
    if fault == "empty":
        artifact.write_bytes(b"")
    else:
        (artifact if fault == "missing-artifact" else metadata).unlink()
    code, payload, _ = register(inputs)
    assert code == 1 and payload["ok"] is False
    assert payload["code"] == ("internal" if fault == "empty" else "file_not_found")
    assert not data.exists()


def test_identical_registration_and_torn_gaps_keep_existing_version_semantics(inputs):
    data, _, _, _ = inputs
    assert register(inputs)[1]["version"] == 1
    assert register(inputs)[1]["version"] == 2
    dangling = data / "models/fixture/v7"
    dangling.mkdir()
    (dangling / "artifact.bin").write_bytes(b"SYNTHETIC_FIXTURE torn opaque bytes")
    assert register(inputs)[1]["version"] == 8
    code, payload, _ = invoke("list", "fixture")
    assert code == 0 and [v["version"] for v in payload["versions"]] == [1, 2, 8]
    assert (dangling / "artifact.bin").read_bytes() == b"SYNTHETIC_FIXTURE torn opaque bytes"
    assert invoke("show", "fixture", "--version", "7")[1]["code"] == "internal"


@pytest.mark.parametrize("fault", ["artifact", "metadata", "duplicate", "missing"])
def test_corruption_fails_closed_for_show_and_whole_list(inputs, fault):
    data, _, _, _ = inputs
    assert register(inputs)[0] == 0
    root = data / "models/fixture"
    artifact = root / "v1/artifact.bin"
    if fault == "artifact":
        artifact.write_bytes(b"SYNTHETIC_FIXTURE changed")
    elif fault == "missing":
        artifact.unlink()
    else:
        path = root / "manifest.jsonl"
        raw = path.read_text()
        if fault == "duplicate":
            path.write_text(raw + raw)
        else:
            row = json.loads(raw)
            row["eval_report"] = {"changed": True}
            path.write_text(json.dumps(row) + "\n")
    for args in [("show", "fixture", "--version", "1"), ("list", "fixture")]:
        code, payload, _ = invoke(*args)
        assert code == 1 and payload["ok"] is False and payload["code"] == "internal"
        assert "versions" not in payload and "digest" not in payload


@pytest.mark.parametrize("args", [(), ("register",), ("register", "fixture"),
    ("register", "fixture", "--artifact", "/unused"),
    ("register", "fixture", "--metadata", "/unused"),
    ("show", "fixture", "--version", "1.5"),
    ("show", "fixture"), ("show", "fixture", "--version", "0"),
    ("show", "fixture", "--version", "-1"), ("show", "fixture", "--version", "true"),
    ("list",), ("list", "fixture", "--root", "/unused"),
    ("show", "fixture", "--latest"), ("delete", "fixture")])
def test_argument_errors_use_actual_main_json_contract(inputs, args):
    data, _, _, _ = inputs
    code, payload, _ = invoke(*args)
    assert code == 1 and payload["code"] == "usage_error" and not data.exists()


def test_explicit_help_preserves_normal_help_without_creating_store(inputs):
    data, _, _, _ = inputs
    output = io.StringIO()
    with contextlib.redirect_stdout(output), pytest.raises(SystemExit) as stopped:
        main(["model", "--help"])
    assert stopped.value.code == 0
    assert "register" in output.getvalue() and "show" in output.getvalue()
    assert not data.exists()


def test_cli_never_deserializes_infers_loads_strategy_or_contacts_tracking(inputs, monkeypatch):
    import pickle

    import joblib
    import requests
    from mlflow.tracking import MlflowClient

    from algua.strategies import loader
    from algua.tracking import factory

    def forbidden(*args, **kwargs):
        pytest.fail("local artifact CLI performed inference/strategy/tracking/network work")

    monkeypatch.setattr(pickle, "load", forbidden)
    monkeypatch.setattr(pickle, "loads", forbidden)
    monkeypatch.setattr(joblib, "load", forbidden)
    monkeypatch.setattr(loader, "load_strategy", forbidden)
    monkeypatch.setattr(loader, "_resolve_model_handle", forbidden)
    monkeypatch.setattr(factory, "get_tracker", forbidden)
    monkeypatch.setattr(MlflowClient, "__init__", forbidden)
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    data, _, _, _ = inputs
    assert register(inputs)[0] == 0
    assert invoke("show", "fixture", "--version", "1")[0] == 0
    assert invoke("list", "fixture")[0] == 0
    assert sorted(p.name for p in data.iterdir()) == ["models"]
