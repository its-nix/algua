"""Execute hostile fixture Python through the authoritative frozen dispatch, not authoring.

Only fake credentials, disposable SQLite/files and a local listener are used. Kernel tests
skip explicitly where bubblewrap/user namespaces are unavailable; refusal tests never skip.
This does not license working-tree research Python or activate any runtime/deployment.
"""
from __future__ import annotations

import json
import shutil
import socket
import sqlite3
import subprocess
from pathlib import Path

import pytest

from algua.live import frozen_invocation
from algua.live.frozen_dispatch import FrozenTenantFailure
from algua.live.planner import phase_a
from algua.live.planner_contract import PlannerRiskFailure
from algua.primitives.contained_process import run_contained
from tests._frozen_harness import (
    BUNDLES,
    STAMP,
    STRATEGY,
    early_input,
    frozen_store,
    in_process,
    late_input,
    overlaid,
    recorded,
    strategy_source,
)
from tests.test_frozen_dispatch import _target, frozen_port


def _kernel_available() -> None:
    bwrap = shutil.which("bwrap")
    if bwrap is None:
        pytest.skip("kernel containment unavailable: bubblewrap missing")
    # Include the dynamic loader and libc: a missing /bin/true loader is NOT a kernel verdict.
    probe = subprocess.run(
        [bwrap, "--unshare-all", "--die-with-parent", "--new-session",
         "--ro-bind", "/usr", "/usr", "--ro-bind", "/lib", "/lib",
         "--ro-bind", "/lib64", "/lib64", "--clearenv", "--", "/usr/bin/true"],
        capture_output=True, timeout=10, check=False,
    )
    if probe.returncode:
        pytest.skip(f"kernel containment unavailable: {probe.stderr.decode(errors='replace')}")


def _hostile_port(tmp_path, monkeypatch, code):
    source = strategy_source(STRATEGY) + "\n" + code + "\n"
    monkeypatch.setitem(BUNDLES, "good", ({STRATEGY: source}, recorded(in_process()), STAMP))
    return frozen_store(tmp_path / "store")


@pytest.mark.parametrize("attack", [
    "environment", "read", "write", "bundle_write", "request_write", "registry", "network",
])
def test_hostile_import_has_no_ambient_authority(tmp_path, monkeypatch, attack):
    _kernel_available()
    fake_token = "FAKE-ONLY-TASK4-NOT-A-CREDENTIAL"
    monkeypatch.setenv("ALGUA_BROKER_TOKEN", fake_token)
    private = tmp_path / "parent-secret.txt"
    private.write_text(fake_token)
    private.chmod(0o444)
    database = tmp_path / "fixture-registry.db"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE authority (value TEXT)")
        conn.execute("INSERT INTO authority VALUES ('unchanged')")
    before_db = database.read_bytes()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(0.1)
        port = listener.getsockname()[1]
        actions = {
            "environment": "assert 'ALGUA_BROKER_TOKEN' not in os.environ",
            "read": f"Path({str(private)!r}).read_text()",
            # Mode bits alone are not isolation: an owner can chmod their own sealed file.
            "write": f"p = Path({str(private)!r}); p.chmod(0o644); p.write_text('owned')",
            "bundle_write": ("p = Path(__file__); assert p.is_file(); "
                             "p.chmod(0o644); p.write_text('owned')"),
            "request_write": ("p = Path(sys.argv[-1]) / 'request.json'; assert p.is_file(); "
                              "p.chmod(0o644); p.write_text('owned')"),
            "registry": (f"sqlite3.connect({str(database)!r}).execute("
                         "\"UPDATE authority SET value='owned'\").connection.commit()"),
            "network": f"socket.create_connection(('127.0.0.1', {port}), timeout=0.2).close()",
        }
        code = (
            "import importlib, json, sys\n"
            "os = importlib.import_module('os')\n"
            "from pathlib import Path\nimport socket, sqlite3\n"
            "_denied = False\ntry:\n    " + actions[attack] + "\n"
            "except (OSError, sqlite3.Error):\n    _denied = True\n"
            + ("_denied = 'ALGUA_BROKER_TOKEN' not in os.environ\n"
               if attack == "environment" else "")
            + "sys.stderr.write('CONTAINMENT ' + json.dumps({'denied': _denied}) + '\\n')\n"
        )
        ended = []

        def capture(argv, **kwargs):
            result = run_contained(argv, **kwargs)
            ended.append(result)
            return result

        with _hostile_port(tmp_path, monkeypatch, code) as store:
            target = _target(store.bundle("good"), store.environment)
            result = frozen_port(target, tmp_path / "invocations", run=capture).phase_a(
                early_input(in_process()))
        assert result == phase_a(overlaid(in_process()), early_input(in_process()))
        report = ended[0].stderr.decode().split("CONTAINMENT ")[1].splitlines()[0]
        assert json.loads(report) == {"denied": True}, attack
        assert private.read_text() == fake_token
        assert database.read_bytes() == before_db
        with pytest.raises(TimeoutError):
            listener.accept()


@pytest.mark.parametrize("payload", [b'NaN\n', None])
def test_hostile_child_output_is_rejected(tmp_path, monkeypatch, payload):
    _kernel_available()
    code = ("import algua.live.frozen_child as child\n"
            f"child.encode_result = lambda *args: {payload!r}\n")
    if payload is None:
        code = (
            "import algua.live.frozen_child as child\nimport json\n"
            "_encode = child.encode_result\n"
            "def _wrong_version(*args):\n"
            "    payload = json.loads(_encode(*args))\n"
            "    payload['wire']['version'] = 2\n"
            "    return json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()\n"
            "child.encode_result = _wrong_version\n"
        )
    with _hostile_port(tmp_path, monkeypatch, code) as store:
        target = _target(store.bundle("good"), store.environment)
        with pytest.raises(FrozenTenantFailure) as failure:
            frozen_port(target, tmp_path / "invocations").phase_a(early_input(in_process()))
    assert failure.value.code == "frozen_result_invalid"


@pytest.mark.parametrize("weight", ["nan", "inf", "-inf", "0x1.0p+9"])
def test_hostile_late_weights_cannot_escape_supervisor_risk(tmp_path, monkeypatch, weight):
    _kernel_available()
    weight = float.fromhex(weight).hex()
    code = (
        "import algua.live.frozen_child as child\nimport json\n"
        "_encode = child.encode_result\n"
        "def _malicious(phase, request_id, result):\n"
        "    payload = json.loads(_encode(phase, request_id, result))\n"
        "    if phase == 'b':\n"
        f"        payload['result']['state']['target_weights'][0][1] = {weight!r}\n"
        "        for intent in payload['result']['intents']:\n"
        "            if intent['symbol'] == payload['result']['state']['target_weights'][0][0]:\n"
        f"                intent['target_weight'] = {weight!r}\n"
        "    return (json.dumps(payload, sort_keys=True, separators=(',', ':')) + '\\n').encode()\n"
        "child.encode_result = _malicious\n"
    )
    with _hostile_port(tmp_path, monkeypatch, code) as store:
        target = _target(store.bundle("good"), store.environment)
        port = frozen_port(target, tmp_path / "invocations")
        strategy = in_process()
        early = early_input(strategy)
        port.phase_a(early)
        if weight in {"inf", "0x1.0000000000000p+9"}:
            result = port.phase_b(late_input(strategy, early, "disabled"))
            assert isinstance(result, PlannerRiskFailure)
            expected = "non_finite_weight" if weight == "inf" else "max_weight_per_symbol"
            assert result.kind == expected
        else:
            with pytest.raises(FrozenTenantFailure) as failure:
                port.phase_b(late_input(strategy, early, "disabled"))
            assert failure.value.code == "frozen_result_invalid"
            assert port.final_invocation_id is None


def test_tmp_scratch_is_created_before_permitted_content_mounts(tmp_path, monkeypatch):
    """Relocate destinations under sandbox /tmp; host fixtures remain in approved scratch."""
    _kernel_available()
    with _hostile_port(tmp_path, monkeypatch, "") as store:
        bundle = store.bundle("good")
        environment = store.environment

        def relocate(argv, **kwargs):
            argv = list(argv)
            invocation = Path(argv[-1])
            paths = {str(bundle): f"/tmp/bundles/{bundle.name}",
                     str(environment): f"/tmp/environments/{environment.name}",
                     str(invocation): f"/tmp/invocations/{invocation.name}"}
            # Keep read-only bind SOURCES in host scratch, only relocate their DESTINATIONS.
            for index, value in enumerate(argv):
                if index and argv[index - 1] == "--ro-bind":
                    continue
                argv[index] = paths.get(value, value)
            argv[-7] = paths[str(environment)] + "/bin/python"
            return run_contained(argv, **kwargs)

        target = _target(bundle, environment)
        early = early_input(in_process())
        result = frozen_port(target, tmp_path / "invocations", run=relocate).phase_a(early)
        assert result == phase_a(overlaid(in_process()), early)


def test_missing_isolator_refuses_before_strategy_execution(tmp_path, monkeypatch):
    # Even an otherwise valid result must never be accepted without kernel isolation.
    marker = tmp_path / "executed"
    code = f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')"
    monkeypatch.setattr(frozen_invocation, "BWRAP", tmp_path / "missing-bwrap")
    with _hostile_port(tmp_path, monkeypatch, code) as store:
        target = _target(store.bundle("good"), store.environment)
        with pytest.raises(FrozenTenantFailure) as failure:
            frozen_port(target, tmp_path / "invocations").phase_a(early_input(in_process()))
    assert failure.value.code == "frozen_launch_failed"
    assert not marker.exists()


def test_kernel_denial_is_not_retried_without_isolation(tmp_path, monkeypatch):
    calls = []

    def denied(argv, **kwargs):
        calls.append(argv)
        from algua.primitives.contained_process import ContainedResult
        return ContainedResult(1, None, False, b"", False, b"bwrap: namespace denied", False)

    with _hostile_port(tmp_path, monkeypatch, "") as store:
        target = _target(store.bundle("good"), store.environment)
        with pytest.raises(FrozenTenantFailure) as failure:
            frozen_port(target, tmp_path / "invocations", run=denied).phase_a(
                early_input(in_process()))
    assert failure.value.code == "frozen_exit_abnormal"
    assert len(calls) == 1
    assert Path(calls[0][0]).name == "bwrap"
