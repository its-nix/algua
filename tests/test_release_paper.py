"""Disposable release trees and fake systemd/CLI; never operate the host deployment."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy/scripts/release-paper.py"
pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or os.geteuid() != 0,
    reason="isolated Linux administrative fixture requires root for real UID/GID drops",
)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _schema(conn):
    return _sha(
        json.dumps(
            [
                conn.execute("PRAGMA user_version").fetchone()[0],
                conn.execute(
                    "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
                ).fetchall(),
            ],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )


@pytest.fixture(scope="session")
def fixture_root():
    with tempfile.TemporaryDirectory(prefix="algua-paper-release-test-", dir="/run") as directory:
        root = Path(directory)
        root.chmod(0o755)
        yield root


@pytest.fixture(scope="session")
def trusted_install(fixture_root):
    root = fixture_root / "operator-install"
    (root / "deploy/scripts").mkdir(parents=True)
    shutil.copyfile(SCRIPT, root / "deploy/scripts/release-paper.py")
    shutil.copytree(
        SCRIPT.parents[2] / "algua", root / "algua", ignore=shutil.ignore_patterns("__pycache__")
    )
    return root / "deploy/scripts/release-paper.py"


@pytest.fixture
def world(fixture_root, monkeypatch, trusted_install, request):
    tmp_path = Path(tempfile.mkdtemp(prefix="case-", dir=fixture_root))
    request.addfinalizer(lambda: shutil.rmtree(tmp_path))
    tmp_path.chmod(0o755)
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps(
            {
                "timers": {"algua-paper.timer": True, "algua-mergeback-drain.timer": True},
                "calls": [],
                "bad": [],
            }
        )
    )
    state.chmod(0o600)
    os.chown(state, 65534, 65534)
    monkeypatch.setenv("RELEASE_FIXTURE_STATE", str(state))
    current = tmp_path / "current"
    binary = tmp_path / "bin"
    binary.mkdir()
    systemctl = binary / "systemctl"
    systemctl.write_text("""#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
p=Path(os.environ['RELEASE_FIXTURE_STATE']); s=json.loads(p.read_text()); args=sys.argv[2:]
s['calls'].append(['systemctl',*args]); p.write_text(json.dumps(s))
if args[0]=='show':
 u=args[1]; current=p.parent/('current' if u=='algua-paper.service' else 'authority')
 if u.endswith('.timer'):
  print('LoadState=loaded\\nActiveState='+('active' if s['timers'][u] else 'inactive'))
 else:
  paper=u=='algua-paper.service'
  suffix='.venv/bin/algua' if paper else '.opencode/scripts/drain-mergeback-queue.sh'
  exe=str(current/suffix)
  argv=exe+(' operator run --job paper -- algua paper run-all --refresh' if paper else '')
  print('LoadState=loaded\\nActiveState='+s.get('service_state','inactive'))
  print('User='+s.get('runtime_user','nobody'))
  print('WorkingDirectory='+s.get('working_directory',str(current)))
  print('ExecStart={ path='+exe+' ; argv[]='+argv+' ; ignore_errors=no ; }')
else:
 for u in args[1:]: s['timers'][u]=args[0]=='start'
 p.write_text(json.dumps(s))
""")
    systemctl.chmod(0o755)
    monkeypatch.setenv("PATH", str(binary) + os.pathsep + os.environ["PATH"])
    releases = []
    for name in ("previous", "target"):
        root = tmp_path / name
        (root / ".venv/bin").mkdir(parents=True)
        cli = root / ".venv/bin/algua"
        cli.write_text(
            (
                """#!/usr/bin/env python3
import json,os,sqlite3,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
p=Path(STATE_PATH); s=json.loads(p.read_text())
s['calls'].append(['algua',str(Path.cwd()),*sys.argv[1:],os.environ['ALGUA_DB_PATH']])
s.setdefault('runtime_uids',[]).append(os.getuid())
s['runtime_env_keys']=sorted(os.environ)
p.write_text(json.dumps(s))
if s.get('interrupt') and Path.cwd().name=='target' and (p.parent/'current').resolve()==Path.cwd():
 s['waiting']=True; p.write_text(json.dumps(s))
 for _ in range(100):
  if not json.loads(p.read_text()).get('interrupt'): break
  time.sleep(.05)
 sys.exit(1)
with sqlite3.connect(os.environ['ALGUA_DB_PATH']) as c:
 c.execute('UPDATE fixture SET value=value')
bad=Path.cwd().name in s['bad']
response={'ok':not bad,'verified':True}
if sys.argv[1:3]==['fleet','health']:
 branch=subprocess.run(['git','branch','--show-current'],capture_output=True,text=True)
 clean=subprocess.run(['git','status','--porcelain','--untracked-files=no'],
                      capture_output=True,text=True)
 response['ok']=response['ok'] and branch.returncode==clean.returncode==0
 response['ok']=response['ok'] and branch.stdout.strip()=='main' and not clean.stdout.strip()
if sys.argv[1:3]==['deployment','verify']: response['manifest_digest']=sys.argv[-1]
if sys.argv[1:3]==['ops','machine-health']:
 paper=s.get('paper_health','ok'); bad=bad or paper not in ('ok','idle')
 response={'ok':not bad and not s.get('unrelated_failure'), 'schema':'machine-health/v1',
  'checked_at':datetime.now(timezone.utc).isoformat(), 'evidence_mode':'OBSERVED',
  'loops':{'research':'failing' if s.get('unrelated_failure') else 'ok',
           'paper':paper,'mergeback':'idle'},'incidents':[]}
print(json.dumps(response))
sys.exit(int(not response['ok']))
"""
            ).replace("STATE_PATH", repr(str(state)))
        )
        cli.chmod(0o755)
        (root / "uv.lock").write_text("fixture locked dependencies\n")
        subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-qm",
                name,
            ],
            check=True,
        )
        files = {
            str(p.relative_to(root)): _sha(p.read_bytes())
            for p in root.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(root).parts
        }
        release = {
            "path": str(root),
            "files": files,
            "commit": subprocess.check_output(
                ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
            ).strip(),
            "lock_sha256": files["uv.lock"],
        }
        release["digest"] = _sha(
            json.dumps(
                {k: v for k, v in release.items() if k != "path"},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )
        releases.append(release)
    current.symlink_to(releases[0]["path"], target_is_directory=True)
    authority = tmp_path / "authority"
    (authority / ".git").mkdir(parents=True)
    os.chown(authority, 65534, 65534)
    os.chown(authority / ".git", 65534, 65534)
    data = tmp_path / "data"
    data.mkdir()
    db = data / "registry.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE fixture(value TEXT)")
        conn.execute("INSERT INTO fixture VALUES ('original')")
        conn.execute("CREATE TABLE strategies(id INTEGER,stage TEXT)")
        conn.execute(
            "CREATE TABLE deployment_artifacts(id INTEGER,manifest_digest TEXT,source_kind TEXT)"
        )
        conn.execute(
            "CREATE TABLE strategy_deployments(strategy_id INTEGER,artifact_id INTEGER,"
            "retired_at TEXT)"
        )
        conn.execute("INSERT INTO strategies VALUES (1,'paper')")
        conn.execute("INSERT INTO deployment_artifacts VALUES (1,?,'frozen')", ("a" * 64,))
        conn.execute("INSERT INTO strategy_deployments VALUES (1,1,NULL)")
        schema = _schema(conn)
    request = {
        "schema": "algua-paper-release/v1",
        "approval_ref": "OWNER_FIXTURE_ONLY",
        "current": str(current),
        "database": str(db),
        "data_dir": str(data),
        "systemd_scope": "user",
        "runtime_user": "nobody",
        "authority_checkout": str(authority),
        "target": releases[1],
        "previous": releases[0],
        "compatibility": {
            "schema_sha256": schema,
            "target_digest": releases[1]["digest"],
            "previous_digest": releases[0]["digest"],
            "rollback_approved": True,
            "approval_ref": "OWNER_SCHEMA_FIXTURE",
        },
        "frozen_manifests": ["a" * 64],
        "evidence": str(tmp_path / "evidence.json"),
    }
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request))
    path.chmod(0o644)
    monkeypatch.setenv("RELEASE_FIXTURE_ENTRY", str(trusted_install))
    return path, request, state


def _run(world, *, recover=False, interrupt=False):
    path, request, state = world
    path.write_text(json.dumps(request))
    args = [
        "/usr/local/bin/python3",
        "-I",
        "-S",
        os.environ["RELEASE_FIXTURE_ENTRY"],
        str(path),
        *(["--recover"] if recover else []),
    ]
    if not interrupt:
        return subprocess.run(args, capture_output=True, text=True, timeout=30)
    child = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if json.loads(state.read_text()).get("waiting"):
                child.kill()
                _state(world, interrupt=False)
                break
            time.sleep(0.02)
        out, err = child.communicate(timeout=10)
        return subprocess.CompletedProcess(args, child.returncode, out, err)
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=5)


def test_release_selects_exact_tree_and_verifies_without_writing_authority(world):
    _, request, state = world
    before = Path(request["database"]).read_bytes()
    run = _run(world)
    assert run.returncode == 0, (run.stdout, run.stderr)
    assert Path(request["current"]).resolve() == Path(request["target"]["path"])
    payload = json.loads(run.stdout)
    assert payload["phase"] == "released"
    assert Path(request["database"]).read_bytes() == before
    calls = json.loads(state.read_text())["calls"]
    cli = [c for c in calls if c[0] == "algua"]
    assert [c[2:-1] for c in cli] == [
        ["deployment", "verify", "a" * 64],
        ["fleet", "health"],
        ["ops", "machine-health"],
    ]
    assert all(c[-1] != request["database"] for c in cli)
    assert all(json.loads(state.read_text())["timers"].values())


def _state(world, **changes):
    path = world[2]
    state = json.loads(path.read_text())
    state.update(changes)
    path.write_text(json.dumps(state))
    return state


def test_wrong_digest_does_nothing(world):
    _, request, state = world
    request["target"]["digest"] = "0" * 64
    request["compatibility"]["target_digest"] = "0" * 64
    result = _run(world)
    assert result.returncode == 1
    assert json.loads(result.stdout)["code"] == "release_digest_mismatch"
    assert json.loads(state.read_text())["calls"] == []
    assert Path(request["current"]).resolve() == Path(request["previous"]["path"])


def test_physical_unit_paths_refuse_without_rewriting_units(world):
    _, request, state = world
    _state(world, working_directory=request["previous"]["path"])
    result = _run(world)
    assert result.returncode == 1
    assert json.loads(result.stdout)["code"] == "unit_paths_must_follow_current_symlink"
    assert all(c[1] == "show" for c in json.loads(state.read_text())["calls"])


@pytest.mark.parametrize("name", ["operator.lock", "merge_back.lock"])
def test_existing_tick_or_drain_lock_prevents_selection(world, name):
    _, request, state = world
    lock = Path(request["previous"]["path"]) / ".git" / name
    code = (
        'import fcntl,sys; f=open(sys.argv[1],"w"); fcntl.flock(f,fcntl.LOCK_EX); '
        'print("held",flush=True); sys.stdin.read()'
    )
    child = subprocess.Popen(
        [sys.executable, "-c", code, str(lock)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout.readline().strip() == "held"
        os.chown(lock, 65534, 65534)
        lock.chmod(0o600)
        result = _run(world)
        assert result.returncode == 1
        assert Path(request["current"]).resolve() == Path(request["previous"]["path"])
        assert all(json.loads(state.read_text())["timers"].values())
    finally:
        child.communicate(timeout=5)
        assert child.returncode == 0


def test_busy_service_stops_future_firings_without_killing_it(world):
    _, request, state = world
    _state(world, service_state="active")
    result = _run(world)
    assert result.returncode == 1
    assert Path(request["current"]).resolve() == Path(request["previous"]["path"])
    saved = json.loads(state.read_text())
    assert not any(saved["timers"].values())
    assert all(
        not any(arg.endswith(".service") for arg in c[2:])
        for c in saved["calls"]
        if c[0] == "systemctl" and c[1] in {"stop", "start"}
    )
    assert Path(request["evidence"]).exists()


def test_failed_target_recovers_only_verified_compatible_previous_release(world):
    _, request, state = world
    _state(world, bad=["target"])
    result = _run(world)
    assert result.returncode == 1  # requested release failed even though recovery succeeded
    assert json.loads(result.stdout)["recovered"] is True
    assert json.loads(result.stdout)["phase"] == "rolled_back"
    assert Path(request["current"]).resolve() == Path(request["previous"]["path"])
    assert all(json.loads(state.read_text())["timers"].values())


@pytest.mark.parametrize("bad,approved", [(["target"], False), (["target", "previous"], True)])
def test_unknown_compatibility_or_failed_recovery_retains_stopped_lane(world, bad, approved):
    _, request, state = world
    _state(world, bad=bad)
    request["compatibility"]["rollback_approved"] = approved
    result = _run(world)
    assert result.returncode == 1
    assert json.loads(result.stdout)["phase"] == "halted"
    assert not any(json.loads(state.read_text())["timers"].values())
    assert Path(request["current"]).resolve() == Path(request["target"]["path"])
    assert json.loads(Path(request["evidence"]).read_text())["recovered"] is False


def test_schema_attestation_must_match_before_selection_not_just_user_version(world):
    _, request, state = world
    with sqlite3.connect(request["database"]) as conn:
        conn.execute("CREATE TABLE later_schema(value TEXT)")  # user_version remains identical
    result = _run(world)
    assert result.returncode == 1
    assert json.loads(result.stdout)["phase"] == "halted"
    assert not any(json.loads(state.read_text())["timers"].values())
    assert Path(request["current"]).resolve() == Path(request["previous"]["path"])
    assert not any(c[0] == "algua" for c in json.loads(state.read_text())["calls"])


def test_release_never_enables_previously_inactive_timers(world):
    _, request, state = world
    _state(world, timers={"algua-paper.timer": False, "algua-mergeback-drain.timer": False})
    result = _run(world)
    assert result.returncode == 0, result.stdout
    assert not any(json.loads(state.read_text())["timers"].values())
    assert not any(
        c[0] == "systemctl" and c[1] == "start" for c in json.loads(state.read_text())["calls"]
    )


def test_explicit_recovery_after_killed_selection_uses_original_approval_and_timer_state(world):
    _, request, state = world
    _state(world, interrupt=True)
    interrupted = _run(world, interrupt=True)
    assert interrupted.returncode == -9
    assert json.loads(Path(request["evidence"]).read_text())["phase"] == "selected"
    assert Path(request["current"]).resolve() == Path(request["target"]["path"])
    assert not any(json.loads(state.read_text())["timers"].values())
    recovered = _run(world, recover=True)
    assert recovered.returncode == 0, recovered.stdout
    assert json.loads(recovered.stdout)["phase"] == "rolled_back"
    assert Path(request["current"]).resolve() == Path(request["previous"]["path"])
    assert all(json.loads(state.read_text())["timers"].values())


def test_runtime_writable_descriptor_cannot_authorize_release(world):
    path, _, state = world
    path.chmod(0o666)
    result = _run(world)
    assert result.returncode == 1
    assert json.loads(result.stdout)["code"] == "runtime_writable_control_path"
    assert json.loads(state.read_text())["calls"] == []


@pytest.mark.parametrize("relative", [".venv/bin/algua", ".git/config"])
def test_runtime_owned_release_or_git_metadata_refuses_before_execution(world, relative):
    _, request, state = world
    os.chown(Path(request["target"]["path"]) / relative, 65534, 65534)
    result = _run(world)
    assert result.returncode == 1
    assert json.loads(result.stdout)["code"] == "runtime_writable_control_path"
    assert json.loads(state.read_text())["calls"] == []


def test_verification_is_nonroot_and_does_not_inherit_credentials(world, monkeypatch):
    monkeypatch.setenv("SSH_AUTH_SOCK", "/fixture/do-not-forward")
    monkeypatch.setenv("ALGUA_ALPACA_API_SECRET", "DO_NOT_FORWARD")
    result = _run(world)
    assert result.returncode == 0, result.stdout
    state = json.loads(world[2].read_text())
    assert set(state["runtime_uids"]) == {65534}
    assert "SSH_AUTH_SOCK" not in state["runtime_env_keys"]
    assert "ALGUA_ALPACA_API_SECRET" not in state["runtime_env_keys"]
    assert "RELEASE_FIXTURE_STATE" not in state["runtime_env_keys"]


def test_unrelated_research_incidents_do_not_block_healthy_paper_release(world):
    _state(world, unrelated_failure=True)
    result = _run(world)
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize("health", ["unknown", "failing"])
def test_unknown_or_unhealthy_paper_does_not_resume(world, health):
    _state(world, paper_health=health)
    result = _run(world)
    assert result.returncode == 1
    assert json.loads(result.stdout)["phase"] == "halted"
    assert not any(json.loads(world[2].read_text())["timers"].values())


def test_mutable_operator_install_refuses_before_importing_release_helpers(world):
    entry = Path(os.environ["RELEASE_FIXTURE_ENTRY"])
    mode = entry.stat().st_mode
    try:
        entry.chmod(0o666)
        result = _run(world)
        assert result.returncode == 1
        assert json.loads(result.stdout)["code"] == "runtime_writable_control_path"
        assert json.loads(world[2].read_text())["calls"] == []
    finally:
        entry.chmod(mode)


def test_materialized_release_rejects_fifo_before_hashing(world):
    _, request, state = world
    os.mkfifo(Path(request["target"]["path"]) / ".git/fixture-fifo")
    result = _run(world)
    assert result.returncode == 1
    assert json.loads(result.stdout)["code"] == "release_not_materialized"
    assert json.loads(state.read_text())["calls"] == []


def test_unmigrated_paper_tenant_is_not_silently_ignored(world):
    _, request, state = world
    with sqlite3.connect(request["database"]) as conn:
        conn.execute("INSERT INTO strategies VALUES (2,'paper')")
    result = _run(world)
    assert result.returncode == 1
    assert json.loads(result.stdout)["phase"] == "halted"
    assert not any(json.loads(state.read_text())["timers"].values())
    assert Path(request["current"]).resolve() == Path(request["previous"]["path"])
