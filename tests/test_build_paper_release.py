"""Real uv/Git/nonroot build, then real administrative consumer without activation."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "deploy/scripts/build-paper-release.py"
ALIASES = (
    "author-a-strategy",
    "forage-inspirations",
    "interpret-results",
    "leap-hypotheses",
    "operating-algua",
    "report-experiments",
    "run-the-research-loop",
)
BACKEND = """
import base64,hashlib,pathlib,zipfile

def build_wheel(wheel_directory,config_settings=None,metadata_directory=None):
    files={str(p):p.read_bytes() for p in pathlib.Path('algua').rglob('*.py')}
    prefix='algua-0.0.1.dist-info/'
    files[prefix+'METADATA']=b'Metadata-Version: 2.1\\nName: algua\\nVersion: 0.0.1\\n'
    files[prefix+'WHEEL']=(b'Wheel-Version: 1.0\\nGenerator: fixture\\n'
                           b'Root-Is-Purelib: true\\nTag: py3-none-any\\n')
    files[prefix+'entry_points.txt']=b'[console_scripts]\\nalgua = algua.cli.main:main\\n'
    records=[]
    for name,data in files.items():
        value=base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
        records.append(f'{name},sha256={value},{len(data)}')
    records.append(prefix+'RECORD,,')
    files[prefix+'RECORD']=('\\n'.join(records)+'\\n').encode()
    name='algua-0.0.1-py3-none-any.whl'
    with zipfile.ZipFile(pathlib.Path(wheel_directory)/name,'w') as wheel:
        for path,data in files.items():wheel.writestr(path,data)
    return name
"""


def run(argv, **kwargs):
    return subprocess.run(argv, capture_output=True, text=True, timeout=180, **kwargs)


@pytest.mark.skipif(
    sys.platform != "linux" or os.geteuid() != 0,
    reason="isolated Linux admin fixture; builder itself runs as UID501",
)
def test_actual_unprivileged_build_relocation_and_existing_consumer():
    directory = Path("/application-builder-fixture-" + uuid4().hex)
    directory.mkdir(mode=0o755)
    try:
        source, work = directory / "source", directory / "work"
        source.mkdir()
        work.mkdir()
        (source / "algua/cli").mkdir(parents=True)
        (source / "algua/__init__.py").write_text('MARKER = "fixture"\n')
        (source / "algua/cli/__init__.py").write_text("")
        (source / "algua/cli/main.py").write_text(
            'def main():\n import json,algua\n print(json.dumps({"origin":algua.__file__}))\n'
        )
        (source / "_backend.py").write_text(BACKEND)
        (source / "pyproject.toml").write_text(
            '[project]\nname="algua"\nversion="0.0.1"\nrequires-python=">=3.12"\n'
            '[project.scripts]\nalgua="algua.cli.main:main"\n'
            '[build-system]\nrequires=[]\nbuild-backend="_backend"\nbackend-path=["."]\n'
        )
        (source / ".python-version").write_text("3.12\n")
        (source / ".gitignore").write_text(".venv/\n__pycache__/\n")
        (source / ".claude/skills").mkdir(parents=True)
        for name in ALIASES:
            (source / ".claude/skills" / name).symlink_to("../../.opencode/skills/" + name)
        assert run(["uv", "lock", "--offline", "--project", str(source)]).returncode == 0
        assert run(["git", "init", "-q", "-b", "main", str(source)]).returncode == 0
        assert run(["git", "-C", str(source), "add", "."]).returncode == 0
        result = run(
            [
                "git",
                "-C",
                str(source),
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-qm",
                "fixture",
            ]
        )
        assert result.returncode == 0, result.stderr
        commit = run(["git", "-C", str(source), "rev-parse", "HEAD"]).stdout.strip()
        # The source's untracked secrets must never enter the independent checkout.
        (source / ".env").write_text("FIXTURE_ONLY=must_not_copy\n")
        for root, dirs, files in os.walk(directory):
            for name in dirs + files:
                os.chown(Path(root) / name, 501, 20, follow_symlinks=False)
        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "PYTHONPATH": str(ROOT),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        output, descriptor = work / "release", work / "spec.json"
        refused = run(
            [
                sys.executable,
                str(BUILDER),
                "--repository",
                str(source),
                "--commit",
                commit,
                "--output",
                str(output),
                "--descriptor",
                str(output / "nested/spec.json"),
            ],
            user=501,
            group=20,
            extra_groups=[],
            env=env,
        )
        assert refused.returncode == 1
        assert json.loads(refused.stdout)["code"] == "descriptor_inside_output"
        assert not output.exists()
        result = run(
            [
                sys.executable,
                str(BUILDER),
                "--repository",
                str(source),
                "--commit",
                commit,
                "--output",
                str(output),
                "--descriptor",
                str(descriptor),
            ],
            user=501,
            group=20,
            extra_groups=[],
            env=env,
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        spec = json.loads(descriptor.read_text())
        assert set(spec) == {"path", "commit", "lock_sha256", "files", "digest"}
        assert not (output / ".env").exists()
        assert all(not p.is_symlink() for p in output.rglob("*"))
        assert (
            run(
                ["git", "-C", str(output), "status", "--porcelain", "--untracked-files=no"],
                user=501,
                group=20,
            ).stdout
            == ""
        )
        # Actual relocation: remove the entire original prefix before invoking the copied CLI.
        adopted = directory / "adopted"
        shutil.copytree(output, adopted)
        shutil.rmtree(output)
        for root, dirs, files in os.walk(adopted):
            for name in dirs + files:
                path = Path(root) / name
                os.chown(path, 0, 0)
                path.chmod(0o555 if path.is_dir() or path.stat().st_mode & 0o111 else 0o444)
        os.chown(adopted, 0, 0)
        adopted.chmod(0o555)
        spec["path"] = str(adopted)
        module_spec = importlib.util.spec_from_file_location(
            "paper_consumer", ROOT / "deploy/scripts/release-paper.py"
        )
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        assert module.release(spec, 501) == adopted
        relocated = run(
            [str(adopted / ".venv/bin/algua")],
            user=501,
            group=20,
            extra_groups=[],
            cwd=directory,
            env={key: value for key, value in env.items() if key != "PYTHONPATH"},
        )
        assert relocated.returncode == 0, relocated.stderr
        origin = Path(json.loads(relocated.stdout)["origin"])
        assert origin.is_relative_to(adopted / ".venv")
    finally:
        shutil.rmtree(directory)
