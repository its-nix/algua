"""Release-shaped Git fixtures with the builder's sole generated application marker."""
import hashlib
import json
import subprocess

import pytest

from algua.execution import paper_mechanics_broker as mechanics


@pytest.fixture
def release(tmp_path, monkeypatch):
    root = tmp_path / "release"
    root.mkdir()
    builder = root / "deploy/scripts/build-paper-release.py"
    builder.parent.mkdir(parents=True)
    builder.write_text("# SYNTHETIC_FIXTURE builder source\n")
    (root / "runtime.py").write_text("# SYNTHETIC_FIXTURE application source\n")
    (root / "uv.lock").write_text("SYNTHETIC_FIXTURE_LOCK\n")

    def git(*args):
        return subprocess.run(["git", *args], cwd=root, check=True,
                              capture_output=True, text=True).stdout.strip()

    git("init", "-q")
    git("add", ".")
    git("-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "-qm", "synthetic isolated source fixture")
    commit = git("rev-parse", "HEAD")
    monkeypatch.setattr(mechanics, "_SOURCE_ROOT", root)
    monkeypatch.setattr(mechanics, "dependency_hash", lambda: hashlib.sha256(
        (root / "uv.lock").read_bytes()).hexdigest())
    # Same generated fields and untracked path as build-paper-release.py; no adoption claim.
    profile = {"profile": "algua-application/v1", "commit": commit,
               "builder_sha256": hashlib.sha256(builder.read_bytes()).hexdigest(),
               "editable": False, "self_contained_runtime": False,
               "external_base_python": {"path": "/fixture/base", "sha256": "fixture"},
               "trusted_or_approved": False}
    (root / "application-runtime.json").write_text(json.dumps(profile))
    return root, commit


def test_exact_generated_marker_preserves_honest_source_receipt(release):
    root, commit = release
    receipt = mechanics.source_identity()
    assert receipt["commit"] == commit
    assert receipt["runtime_metadata_hash"] == hashlib.sha256(
        (root / "application-runtime.json").read_bytes()).hexdigest()


@pytest.mark.parametrize("change", ["tracked", "untracked", "marker_commit", "marker_builder"])
def test_dirty_or_unbound_release_refuses(release, change):
    root, _ = release
    if change == "tracked":
        (root / "runtime.py").write_text("changed source\n")
    elif change == "untracked":
        (root / "unreviewed_strategy.py").write_text("untracked code\n")
    else:
        path = root / "application-runtime.json"
        profile = json.loads(path.read_text())
        profile["commit" if change == "marker_commit" else "builder_sha256"] = "different"
        path.write_text(json.dumps(profile))
    with pytest.raises(ValueError):
        mechanics.source_identity()
