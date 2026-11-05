#!/usr/bin/env python3
"""Operator-invoked paper release consumer. No build, merge, intake or live operation."""

from __future__ import annotations

import hashlib
import json
import os
import pwd
import re
import shutil
import signal
import socket
import sqlite3
import stat
import subprocess
import sys
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

SERVICES = ("algua-paper.service", "algua-mergeback-drain.service")
TIMERS = ("algua-paper.timer", "algua-mergeback-drain.timer")
HEX = re.compile(r"[0-9a-f]{64}")


def controlled(path: Path) -> None:
    """Require installed administrative content; never repair ownership into approval."""
    for item in (path, *path.parents):
        info = item.lstat()
        require(
            not stat.S_ISLNK(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
            "runtime_writable_control_path",
        )


def installed() -> None:
    require(
        os.geteuid() == 0 and sys.flags.isolated and sys.flags.no_site,
        "root_isolated_operator_required",
    )
    root = Path(__file__).absolute().parents[2]
    controlled(Path(__file__).absolute())
    controlled(Path(sys.executable).resolve())
    for item in (root / "algua").rglob("*"):
        controlled(item)
        require(item.is_dir() or stat.S_ISREG(item.lstat().st_mode), "release_not_materialized")
    sys.path.insert(0, str(root))


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def require(condition: Any, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def run(args: list[str], **kwargs: Any) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=60, **kwargs)
    require(result.returncode == 0, "command_failed")
    return result.stdout.strip()


def schema(conn: sqlite3.Connection) -> str:
    return digest(
        canonical(
            [
                conn.execute("PRAGMA user_version").fetchone()[0],
                [
                    tuple(row)
                    for row in conn.execute(
                        "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
                    )
                ],
            ]
        )
    )


def compatible(request: dict[str, Any], conn: sqlite3.Connection) -> None:
    require(schema(conn) == request["compatibility"]["schema_sha256"], "schema_not_approved")
    tenants = conn.execute(
        "SELECT a.manifest_digest,a.source_kind FROM strategies s "
        "LEFT JOIN strategy_deployments d ON d.strategy_id=s.id AND d.retired_at IS NULL "
        "LEFT JOIN deployment_artifacts a ON a.id=d.artifact_id "
        "WHERE s.stage IN ('paper','forward_tested')"
    ).fetchall()
    require(
        all(
            row[1] == "frozen" and isinstance(row[0], str) and HEX.fullmatch(row[0])
            for row in tenants
        ),
        "paper_tenant_not_frozen",
    )
    active = {row[0] for row in tenants}
    require(active == set(request["frozen_manifests"]), "active_manifest_set_changed")


def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, "duplicate_descriptor_key")
        result[key] = value
    return result


def release(spec: dict[str, Any], uid: int) -> Path:
    require(set(spec) == {"path", "commit", "lock_sha256", "files", "digest"}, "release_shape")
    root = Path(spec["path"])
    controlled(root)
    require(root.is_absolute() and root.resolve() == root and root.is_dir(), "release_path")
    payload = {key: value for key, value in spec.items() if key not in {"path", "digest"}}
    require(digest(canonical(payload)) == spec["digest"], "release_digest_mismatch")
    require(isinstance(spec["files"], dict) and spec["files"], "release_inventory")
    found = {}
    for item in root.rglob("*"):
        relative = item.relative_to(root)
        if str(relative) in {".git/operator.lock", ".git/merge_back.lock"}:
            info = item.lstat()
            require(
                stat.S_ISREG(info.st_mode)
                and info.st_uid == uid
                and info.st_nlink == 1
                and stat.S_IMODE(info.st_mode) == 0o600,
                "runtime_lock_file_invalid",
            )
            continue
        controlled(item)
        require(item.is_dir() or stat.S_ISREG(item.lstat().st_mode), "release_not_materialized")
        if ".git" in item.relative_to(root).parts:
            continue
        require(item.name != ".env" and not item.is_symlink(), "release_not_materialized")
        if item.is_file():
            with item.open("rb") as stream:
                found[str(item.relative_to(root))] = hashlib.file_digest(
                    stream, "sha256"
                ).hexdigest()
    require(
        found == spec["files"] and found.get("uv.lock") == spec["lock_sha256"],
        "release_inventory_mismatch",
    )
    require(run(["git", "-C", str(root), "rev-parse", "HEAD"]) == spec["commit"], "release_commit")
    require(run(["git", "-C", str(root), "branch", "--show-current"]) == "main", "release_not_main")
    require(
        not run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"]),
        "release_dirty",
    )
    require((root / ".venv/bin/algua").is_file(), "release_cli_missing")
    return root


def load(path: Path) -> tuple[dict[str, Any], str]:
    controlled(path)
    info = path.lstat()
    require(
        stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
        "descriptor_not_root_owned",
    )
    require(info.st_size <= 16 * 1024 * 1024, "descriptor_too_large")
    raw = path.read_bytes()
    request = json.loads(raw, object_pairs_hook=no_duplicates)
    require(
        set(request)
        == {
            "schema",
            "approval_ref",
            "current",
            "database",
            "data_dir",
            "authority_checkout",
            "runtime_user",
            "systemd_scope",
            "target",
            "previous",
            "compatibility",
            "frozen_manifests",
            "evidence",
        },
        "descriptor_shape",
    )
    require(
        request["schema"] == "algua-paper-release/v1"
        and request["systemd_scope"] in {"user", "system"}
        and isinstance(request["approval_ref"], str)
        and 1 <= len(request["approval_ref"]) <= 200,
        "descriptor_approval",
    )
    for key in ("current", "database", "data_dir", "evidence", "authority_checkout"):
        require(
            isinstance(request[key], str) and re.fullmatch(r"/[A-Za-z0-9/._-]+", request[key]),
            "descriptor_path",
        )
    require(
        isinstance(request["frozen_manifests"], list)
        and request["frozen_manifests"]
        and all(
            isinstance(item, str) and HEX.fullmatch(item) for item in request["frozen_manifests"]
        ),
        "frozen_manifest_list",
    )
    compat = request["compatibility"]
    require(
        set(compat)
        == {
            "schema_sha256",
            "target_digest",
            "previous_digest",
            "rollback_approved",
            "approval_ref",
        },
        "compatibility_shape",
    )
    require(
        isinstance(compat["schema_sha256"], str)
        and HEX.fullmatch(compat["schema_sha256"])
        and type(compat["rollback_approved"]) is bool
        and isinstance(compat["approval_ref"], str)
        and 1 <= len(compat["approval_ref"]) <= 200
        and compat["target_digest"] == request["target"]["digest"]
        and compat["previous_digest"] == request["previous"]["digest"],
        "compatibility_binding",
    )
    return request, digest(raw)


def write(path: Path, record: dict[str, Any], phase: str) -> None:
    record["phase"] = phase
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    with temporary.open("x") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def select(current: Path, target: Path) -> None:
    temporary = current.with_name(current.name + f".{os.getpid()}.next")
    temporary.symlink_to(target, target_is_directory=True)
    os.replace(temporary, current)
    fd = os.open(current.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def control(request: dict[str, Any], *args: str) -> str:
    binary = Path(shutil.which("systemctl") or "/usr/bin/systemctl")
    controlled(binary)
    return run([str(binary), "--" + request["systemd_scope"], *args])


def show(request: dict[str, Any], unit: str) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in control(
            request,
            "show",
            unit,
            "--property=LoadState,ActiveState,WorkingDirectory,ExecStart,User",
        ).splitlines()
        if "=" in line
    )


def unit_contract(request: dict[str, Any]) -> dict[str, bool]:
    current = request["current"]
    for unit in SERVICES:
        state = show(request, unit)
        base = current if unit == SERVICES[0] else request["authority_checkout"]
        suffix = (
            ".venv/bin/algua"
            if unit == SERVICES[0]
            else ".opencode/scripts/drain-mergeback-queue.sh"
        )
        command = base + "/" + suffix
        argv = command + (
            " operator run --job paper -- algua paper run-all --refresh"
            if unit == SERVICES[0]
            else ""
        )
        require(
            state.get("LoadState") == "loaded"
            and state.get("User") == request["runtime_user"]
            and state.get("WorkingDirectory") == base
            and state.get("ExecStart", "").startswith(f"{{ path={command} ; argv[]={argv} ;")
            and state["ExecStart"].count("{ path=") == 1,
            "unit_paths_must_follow_current_symlink",
        )
    timers = {unit: show(request, unit) for unit in TIMERS}
    require(
        all(
            value.get("LoadState") == "loaded"
            and value.get("ActiveState") in {"active", "inactive"}
            for value in timers.values()
        ),
        "timer_state_unknown",
    )
    return {unit: value["ActiveState"] == "active" for unit, value in timers.items()}


def quiesce(request: dict[str, Any]) -> None:
    control(request, "stop", *TIMERS)
    require(
        all(show(request, unit).get("ActiveState") in {"inactive", "failed"} for unit in SERVICES),
        "paper_or_drainer_busy",
    )


def checks(request: dict[str, Any], root: Path) -> None:
    from algua.registry.read_snapshot import registry_snapshot

    # These existing CLI views migrate their DB. Only a private copy may see that write path.
    with TemporaryDirectory(prefix="algua-paper-release-") as directory:
        copy = Path(directory) / "registry.db"
        with (
            registry_snapshot(Path(request["database"])) as captured,
            sqlite3.connect(copy) as conn,
        ):
            captured.connection.backup(conn)
        with sqlite3.connect(copy) as conn:
            compatible(request, conn)
            expected = schema(conn)
        require(expected == request["compatibility"]["schema_sha256"], "schema_not_approved")
        account = pwd.getpwnam(request["runtime_user"])
        os.chown(directory, account.pw_uid, account.pw_gid)
        os.chown(copy, account.pw_uid, account.pw_gid)
        env = {
            "PATH": str(root / ".venv/bin") + ":/usr/local/bin:/usr/bin:/bin",
            "HOME": directory,
            "XDG_CACHE_HOME": directory + "/cache",
            "XDG_CONFIG_HOME": directory + "/config",
            "XDG_DATA_HOME": directory + "/data",
            "ALGUA_DB_PATH": str(copy),
            "ALGUA_DATA_DIR": request["data_dir"],
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "safe.directory",
            "GIT_CONFIG_VALUE_0": str(root),
            "MLFLOW_DISABLE_TELEMETRY": "true",
            "TMPDIR": directory,
            "NUMBA_CACHE_DIR": directory + "/numba",
            "MPLCONFIGDIR": directory + "/matplotlib",
        }
        for args in [["deployment", "verify", item] for item in request["frozen_manifests"]] + [
            ["fleet", "health"],
            ["ops", "machine-health"],
        ]:
            result = subprocess.run(
                [str(root / ".venv/bin/algua"), *args],
                cwd=root,
                env=env,
                user=account.pw_uid,
                group=account.pw_gid,
                extra_groups=[],
                capture_output=True,
                text=True,
                timeout=60,
            )
            paper_view = args == ["ops", "machine-health"]
            require(result.returncode in ({0, 1} if paper_view else {0}), "command_failed")
            response = json.loads(result.stdout)
            if paper_view:
                require(
                    isinstance(response, dict)
                    and response.get("schema") == "machine-health/v1"
                    and response.get("evidence_mode") == "OBSERVED"
                    and isinstance(response.get("loops"), dict)
                    and response["loops"].get("paper") in {"ok", "idle"},
                    "paper_unhealthy",
                )
                continue
            require(
                isinstance(response, dict) and response.get("ok") is True, "release_health_failed"
            )
            if args[:2] == ["deployment", "verify"]:
                require(
                    response.get("verified") is True and response.get("manifest_digest") == args[2],
                    "frozen_verification_mismatch",
                )
        with sqlite3.connect(copy) as conn:
            require(schema(conn) == expected, "verification_required_schema_change")


def execute(request: dict[str, Any], request_hash: str, *, recover: bool) -> dict[str, Any]:
    from algua.primitives.flock import file_lock
    from algua.registry.read_snapshot import registry_snapshot

    account = pwd.getpwnam(request["runtime_user"])
    require(account.pw_uid != 0, "nonroot_runtime_required")
    current, evidence = Path(request["current"]), Path(request["evidence"])
    controlled(current.parent)
    controlled(evidence.parent)
    require(current.lstat().st_uid == 0, "selector_not_root_owned")
    target = release(request["target"], account.pw_uid)
    previous = release(request["previous"], account.pw_uid)
    authority = Path(request["authority_checkout"])
    controlled(authority.parent)
    require(
        authority.is_dir()
        and not authority.is_symlink()
        and authority.resolve() == authority
        and authority not in {target, previous}
        and (authority / ".git").is_dir()
        and not (authority / ".git").is_symlink(),
        "authority_checkout_invalid",
    )
    require(current.is_symlink() and current.resolve() in {previous, target}, "current_selection")
    require(target != previous, "release_same_as_previous")
    for path in (Path(request["database"]), Path(request["data_dir"]), evidence):
        require(
            not any(path.resolve().is_relative_to(root) for root in (target, previous)),
            "state_must_be_outside_releases",
        )
    require(evidence.parent.is_dir() and not evidence.is_symlink(), "evidence_path")
    timers = unit_contract(request)
    if recover:
        controlled(evidence)
        record = json.loads(evidence.read_text())
        require(
            record["request_sha256"] == request_hash
            and record["phase"] not in {"released", "rolled_back"},
            "recovery_receipt_mismatch",
        )
        timers = record["timers"]
    else:
        require(not evidence.exists() and current.resolve() == previous, "release_already_started")
        record = {
            "request_sha256": request_hash,
            "timers": timers,
            "ok": False,
            "target_digest": request["target"]["digest"],
            "recovered": False,
        }
    with ExitStack() as locks:
        for root in sorted({target, previous, authority}):
            git_dir = root / ".git"
            require(git_dir.is_dir() and not git_dir.is_symlink(), "release_git_metadata")
            if root != authority:
                for name in ("operator.lock", "merge_back.lock"):
                    path = git_dir / name
                    if not path.exists():
                        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                        os.fchown(fd, account.pw_uid, account.pw_gid)
                        os.close(fd)
            # Open mutable authority/operational lock paths without administrative privilege.
            groups = os.getgroups()
            original_gid = os.getegid()
            os.setgroups([])
            os.setegid(account.pw_gid)
            os.seteuid(account.pw_uid)
            try:
                locks.enter_context(
                    file_lock(
                        git_dir / "operator.lock",
                        blocking=False,
                        metadata={
                            "job": "paper-release",
                            "host": socket.gethostname(),
                            "pid": os.getpid(),
                            "started_at": datetime.now(UTC).isoformat(),
                        },
                    )
                )
                locks.enter_context(file_lock(git_dir / "merge_back.lock", blocking=False))
            finally:
                os.seteuid(0)
                os.setegid(original_gid)
                os.setgroups(groups)
        write(evidence, record, "quiescing")
        try:
            quiesce(request)
            write(evidence, record, "quiesced")
            require(
                recover is False or request["compatibility"]["rollback_approved"],
                "recovery_not_approved",
            )
            with registry_snapshot(Path(request["database"])) as captured:
                compatible(request, captured.connection)
            chosen = previous if recover else target
            # Record BEFORE the atomic selection so a killed process can be explicitly recovered.
            write(evidence, record, "selecting")
            select(current, chosen)
            write(evidence, record, "selected")
            checks(request, chosen)
            release(request["previous"] if recover else request["target"], account.pw_uid)
            write(evidence, record, "verified")
            for unit, active in timers.items():
                if active:
                    control(request, "start", unit)
            record.update(ok=True, recovered=recover)
            write(evidence, record, "rolled_back" if recover else "released")
        except Exception:
            quiesce(request)  # never recover or resume across an active paper/drainer operation
            if not recover and request["compatibility"]["rollback_approved"]:
                try:
                    release(request["previous"], account.pw_uid)
                    # Verify compatibility and health before switching back, then again after.
                    checks(request, previous)
                    select(current, previous)
                    checks(request, previous)
                    for unit, active in timers.items():
                        if active:
                            control(request, "start", unit)
                    record.update(ok=False, recovered=True)
                    write(evidence, record, "rolled_back")
                    return record
                except Exception:
                    quiesce(request)
            record.update(ok=False, recovered=False)
            write(evidence, record, "halted")
    return record


def main() -> int:
    try:
        installed()
        require(
            len(sys.argv) in {2, 3} and (len(sys.argv) == 2 or sys.argv[2] == "--recover"),
            "usage_request_file_optional_recover",
        )
        request, request_hash = load(Path(sys.argv[1]))
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(InterruptedError()))
        result = execute(request, request_hash, recover=len(sys.argv) == 3)
        print(json.dumps(result))
        return 0 if result["ok"] else 1
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ValueError) else "release_operation_failed"
        print(json.dumps({"ok": False, "phase": "refused", "code": reason}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
