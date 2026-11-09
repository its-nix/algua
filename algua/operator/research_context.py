"""Complete source/data identity for the existing research controller context."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from algua.operator.research_cycle import file_hash
from algua.operator.research_profile import load_research_profile


def cycle_context(data_dir: Path, *, root: Path | None = None) -> dict:
    root = root.resolve() if root is not None else Path(__file__).resolve().parents[2]
    required = {
        "dependency_hash": "uv.lock",
        "project_sha256": "pyproject.toml",
        "runtime_seam_sha256": ".opencode/scripts/run_agent.sh",
        "runtime_config_sha256": ".opencode/opencode.json",
        "controller_sha256": "algua/operator/research_cycle.py",
        "supervisor_sha256": "algua/operator/research_cycle_worker.py",
        "outcome_parser_sha256": "algua/operator/research_cycle_results.py",
        "driver_sha256": ".opencode/scripts/run-research-loop.sh",
    }
    sources = {key: file_hash(root / path) for key, path in required.items()}
    if any(value is None for value in sources.values()):
        raise ValueError("missing required cycle source identity")
    # Pin checkout Python/runtime content independently of Git refs and the caller's cwd.
    paths = sorted({*required.values(), *(
        str(path.relative_to(root)) for directory in ("algua", ".opencode")
        for path in (root / directory).rglob("*") if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix in {".py", ".sh", ".md", ".json", ".txt"})})
    manifest = {path: file_hash(root / path) for path in paths}
    if any(value is None for value in manifest.values()):
        raise ValueError("missing cycle baseline source")
    baseline = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    context: dict = {"data_dir": str(data_dir.resolve()),
            "data_manifest_sha256": file_hash(data_dir / "manifest.jsonl"),
            "source_baseline_sha256": baseline, **sources}
    profile = load_research_profile(data_dir, root=root)
    if profile is not None:
        context["research_profile"] = profile
    return context
