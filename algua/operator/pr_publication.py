"""DRAFT, opt-in publication only; PR observations confer no admission authority."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from algua.operator.diff_policy import evaluate_diff
from algua.operator.gitops import GitOps

REPOSITORY = "its-nix/algua"
GIT_URL = f"https://github.com/{REPOSITORY}.git"
_MAIN = "refs/heads/main"


def publish_candidate(git: GitOps, branch: str, tip: str, codeowners_text: str) -> dict | None:
    """Create/reuse one exact-head draft PR; never update an existing ref or publish main."""
    if os.environ.get("ALGUA_MERGEBACK_PUBLISH_PR") != "1":
        return None
    root = getattr(git, "repo_root", None)
    if not isinstance(root, Path) or re.fullmatch(r"[0-9a-f]{40}", tip) is None:
        return None
    environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GH_PROMPT_DISABLED": "1"}

    def run(args: list[str], body: dict | None = None) -> bytes:
        result = subprocess.run(
            args, input=None if body is None else json.dumps(body).encode(),
            capture_output=True, check=True, timeout=20, env=environment)
        if len(result.stdout) > 4 * 1024 * 1024:
            raise ValueError("publication output too large")
        return result.stdout

    def command(*args: str) -> str:
        return run(["git", "-C", str(root), *args]).decode()

    def api(suffix: str, body: dict | None = None) -> Any:
        args = ["gh", "api", f"repos/{REPOSITORY}/{suffix}", "--hostname", "github.com"]
        if body is not None:
            args += ["--method", "POST", "--input", "-"]
        return json.loads(run(args, body))

    def remote(ref: str) -> str | None:
        rows = command("ls-remote", "--heads", GIT_URL, ref).splitlines()
        if not rows:
            return None
        fields = rows[0].split()
        if len(rows) != 1 or len(fields) != 2 or fields[1] != ref:
            raise ValueError("ambiguous publication ref")
        if re.fullmatch(r"[0-9a-f]{40}", fields[0]) is None:
            raise ValueError("invalid publication ref")
        return fields[0]

    try:
        base = remote(_MAIN)
        if base is None:
            return None
        command("fetch", "--no-tags", GIT_URL, _MAIN)
        if git.resolve("FETCH_HEAD") != base:
            return None
        entries = git.changed_entries(git.merge_base(base, tip), tip)
        if not evaluate_diff(entries, codeowners_text).ok:
            return None
        history = command("rev-list", "--parents", "--max-count=129", tip, f"^{base}").splitlines()
        if len(history) > 128:
            return None
        for row in history:
            parents = row.split()
            if len(parents) != 2 or not evaluate_diff(
                    git.changed_entries(parents[1], parents[0]), codeowners_text).ok:
                return None  # Reverted protected edits must not leak through pushed history.
        head = f"algua-research/{tip}"
        ref = f"refs/heads/{head}"

        def stable() -> bool:
            return git.resolve(branch) == tip and remote(_MAIN) == base

        def validate(pr: dict) -> None:
            if (type(pr["number"]) is not int or pr["number"] < 1
                    or pr["head"]["sha"] != tip or pr["head"]["ref"] != head
                    or pr["head"]["repo"]["full_name"] != REPOSITORY
                    or pr["base"]["repo"]["full_name"] != REPOSITORY
                    or pr["base"]["ref"] != "main" or pr["base"]["sha"] != base
                    or pr["state"] not in {"open", "closed"}
                    or pr["state"] == "closed" and pr.get("merged") is not True):
                raise ValueError("PR publication identity mismatch")

        def lookup() -> dict | None:
            query = urlencode({"state": "all", "head": f"its-nix:{head}",
                               "base": "main", "per_page": 100})
            rows = api(f"pulls?{query}")
            if not isinstance(rows, list) or len(rows) > 1:
                raise ValueError("ambiguous PR publication")
            if not rows:
                return None
            number = rows[0]["number"]
            if type(number) is not int or number < 1:
                raise ValueError("invalid PR number")
            pr = api(f"pulls/{number}")
            if not isinstance(pr, dict) or pr.get("number") != number:
                raise ValueError("invalid PR response")
            validate(pr)
            return pr

        current = remote(ref)
        if current is not None and current != tip:
            return None
        if current is None:
            if not stable() or not history or not entries:
                return None
            # Empty expected value means CREATE ONLY, not permission to replace an existing ref.
            command("push", "--no-follow-tags", "--recurse-submodules=no",
                    f"--force-with-lease={ref}:", GIT_URL, f"{tip}:{ref}")
        pr = lookup()
        if pr is None:
            if not history or not entries or not stable() or remote(ref) != tip:
                return None
            created = None
            try:
                created = api("pulls", {
                    "head": head, "base": "main", "draft": True,
                    "title": f"research: review candidate {tip[:12]}",
                    "body": f"Candidate head `{tip}`. Publication only; admission remains pending."
                })
                validate(created)
            except subprocess.SubprocessError:
                pass  # Lost reply / concurrent creation: lookup once, never blindly POST again.
            pr = lookup()
            if pr is None or created is not None and pr["number"] != created["number"]:
                return None
        if not stable() or remote(ref) != tip:
            return None
        return {"repository": REPOSITORY, "base": "main", "head_ref": head, "head_sha": tip,
                "number": pr["number"], "url": f"https://github.com/{REPOSITORY}/pull/{pr['number']}",
                "authority": "none"}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.SubprocessError):
        return None  # No free-form provider error, credential, claim or token reaches stdout.
