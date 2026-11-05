#!/usr/bin/env python3
"""Unprivileged application release builder; output is untrusted until owner adoption."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import sysconfig
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Never

ALIASES = frozenset(
    ".claude/skills/" + name
    for name in (
        "author-a-strategy",
        "forage-inspirations",
        "interpret-results",
        "leap-hypotheses",
        "operating-algua",
        "report-experiments",
        "run-the-research-loop",
    )
)


def require(value: Any, reason: str) -> None:
    if not value:
        raise ValueError(reason)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def command(
    argv: list[str], env: dict[str, str], *, cwd: Path | None = None, data: str | None = None
) -> str:
    result = subprocess.run(
        argv, cwd=cwd, env=env, input=data, text=True, capture_output=True, timeout=900
    )
    require(
        result.returncode == 0, "build_command_failed: " + argv[0] + ": " + result.stderr[-4096:]
    )
    return result.stdout.strip()


def inventory(root: Path) -> dict[str, str]:
    files = {}
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        require(not stat.S_ISLNK(info.st_mode), "unmaterialized_symlink")
        require(stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode), "special_file")
        require(path.name != ".env", "secret_env_file")
        if ".git" not in path.relative_to(root).parts and path.is_file():
            files[path.relative_to(root).as_posix()] = sha(path)
    return files


def build(repository: Path, commit: str, output: Path, descriptor: Path) -> dict[str, Any]:
    require(os.geteuid() != 0, "unprivileged_builder_required")
    require(sys.version_info[:2] == (3, 12), "python_312_required")
    require(not output.exists() and not output.is_symlink(), "output_exists")
    require(not descriptor.exists(), "descriptor_exists")
    require(output.is_absolute() and output.parent.resolve() == output.parent, "output_path")
    require(not descriptor.resolve().is_relative_to(output.resolve()), "descriptor_inside_output")
    require(len(commit) == 40 and all(c in "0123456789abcdef" for c in commit), "exact_commit")
    uv = shutil.which("uv")
    require(uv, "uv_missing")
    with TemporaryDirectory(prefix="algua-application-build-") as private:
        home = Path(private)
        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": private,
            "UV_CACHE_DIR": str(home / "cache"),
            "TMPDIR": private,
            "PYTHONDONTWRITEBYTECODE": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": "core.hooksPath",
            "GIT_CONFIG_VALUE_0": "/dev/null",
            "GIT_CONFIG_KEY_1": "core.fsmonitor",
            "GIT_CONFIG_VALUE_1": "false",
            "GIT_TERMINAL_PROMPT": "0",
        }
        template = home / "template"
        template.mkdir()
        env["GIT_TEMPLATE_DIR"] = str(template)
        require(
            command(["git", "-C", str(repository), "rev-parse", commit + "^{commit}"], env)
            == commit,
            "commit_missing",
        )
        tree = command(["git", "-C", str(repository), "ls-tree", "-r", commit], env)
        links = {line.split("\t", 1)[1] for line in tree.splitlines() if line.startswith("120000 ")}
        require(links == ALIASES, "source_symlink_profile_changed")
        command(["git", "init", "--quiet", "-b", "main", str(output)], env)
        git = ["git", "-C", str(output)]
        command([*git, "fetch", "--quiet", "--depth=1", "--no-tags", str(repository), commit], env)
        command([*git, "sparse-checkout", "init", "--no-cone"], env)
        patterns = "/*\n" + "".join("!/" + path + "\n" for path in sorted(ALIASES))
        command([*git, "sparse-checkout", "set", "--no-cone", "--stdin"], env, data=patterns)
        command([*git, "checkout", "--quiet", "--no-track", "-B", "main", commit], env)
        (output / ".git/FETCH_HEAD").unlink()
        require((output / ".python-version").read_text().strip() == "3.12", "python_pin")
        venv = output / ".venv"
        command(
            [
                str(uv),
                "venv",
                "--relocatable",
                "--no-python-downloads",
                "--python",
                str(Path(getattr(sys, "_base_executable", sys.executable)).resolve()),
                str(venv),
            ],
            env,
        )
        command(
            [
                str(uv),
                "sync",
                "--project",
                str(output),
                "--locked",
                "--no-dev",
                "--no-default-groups",
                "--no-editable",
                "--no-python-downloads",
                "--link-mode",
                "copy",
                "--no-config",
                "--no-progress",
            ],
            env,
        )
        base = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
        interpreters = {}
        for name in ("python", "python3", "python3.12"):
            path = venv / "bin" / name
            require(path.is_symlink() and path.resolve() == base, "interpreter_link_profile")
            interpreters[path] = path.read_bytes()
        for path, content in interpreters.items():
            path.unlink()
            path.write_bytes(content)
            path.chmod(0o755)
        lib64 = venv / "lib64"
        if lib64.is_symlink() and lib64.resolve() == (venv / "lib").resolve():
            lib64.unlink()
        for path in (venv / "bin").glob("activate*"):
            path.unlink()
        library = Path(sysconfig.get_config_var("LIBDIR")) / sysconfig.get_config_var("LDLIBRARY")
        if library.is_file():
            for name in {library.name, library.resolve().name}:
                shutil.copyfile(library.resolve(), venv / "lib" / name)
        # Refuse literal path entries. Executable wheel shims are inventory-bound, not proven
        # statically safe by accepting an import statement; this is not planner certification.
        for path in venv.rglob("*.pth"):
            lines = path.read_text().splitlines()
            require(
                all(
                    not line.strip() or line.startswith("#") or line.startswith("import ")
                    for line in lines
                ),
                "external_pth_path",
            )
        probe = "import algua,json,sys;print(json.dumps([algua.__file__,sys.prefix]))"
        origin, prefix = json.loads(command([str(venv / "bin/python"), "-I", "-c", probe], env))
        require(
            Path(origin).is_relative_to(venv) and Path(prefix) == venv, "installed_package_origin"
        )
        installed = Path(origin).parent
        for path in (output / "algua").rglob("*.py"):
            target = installed / path.relative_to(output / "algua")
            require(target.is_file() and sha(path) == sha(target), "installed_source_mismatch")
        require(
            not command([*git, "status", "--porcelain", "--untracked-files=no"], env),
            "source_dirty",
        )
        stdlib = Path(sysconfig.get_path("stdlib"))
        stdlib_sources = {
            path.relative_to(stdlib).as_posix(): sha(path)
            for path in sorted(stdlib.rglob("*.py"))
            if "site-packages" not in path.relative_to(stdlib).parts
        }
        profile = {
            "profile": "algua-application/v1",
            "commit": commit,
            "builder_sha256": sha(Path(__file__)),
            "omitted_source_aliases": sorted(ALIASES),
            "editable": False,
            "python": sys.version,
            "uv": command([str(uv), "--version"], env),
            "external_base_python": {
                "path": str(base),
                "sha256": sha(base),
                "stdlib": str(stdlib),
                "stdlib_py_digest": hashlib.sha256(canonical(stdlib_sources)).hexdigest(),
            },
            "self_contained_runtime": False,
            "trusted_or_approved": False,
            "pth_shims": "executable wheel code; locked/inventory-bound, not certified safe",
        }
        (output / "application-runtime.json").write_bytes(canonical(profile) + b"\n")
        files = inventory(output)
        payload = {"commit": commit, "lock_sha256": files["uv.lock"], "files": files}
        spec = {
            "path": str(output),
            **payload,
            "digest": hashlib.sha256(canonical(payload)).hexdigest(),
        }
        require(len(canonical(spec)) < 8 * 1024 * 1024, "consumer_descriptor_budget")
        with descriptor.open("x") as stream:
            stream.write(json.dumps(spec, sort_keys=True) + "\n")
        return spec


def main() -> int:
    try:

        class Parser(argparse.ArgumentParser):
            def error(self, message: str) -> Never:
                raise ValueError("invalid_arguments")

        parser = Parser()
        parser.add_argument("--repository", type=Path, required=True)
        parser.add_argument("--commit", required=True)
        parser.add_argument("--output", type=Path, required=True)
        parser.add_argument("--descriptor", type=Path, required=True)
        args = parser.parse_args()
        spec = build(args.repository, args.commit, args.output, args.descriptor)
        print(
            json.dumps(
                {
                    "ok": True,
                    "trusted": False,
                    "descriptor": str(args.descriptor),
                    "digest": spec["digest"],
                }
            )
        )
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "code": str(exc) if isinstance(exc, ValueError) else "application_build_failed",
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
