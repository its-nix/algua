"""Guard: every relative markdown link in the repo resolves to a real file."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_SKIP_DIRS = {"node_modules", ".superpowers", ".venv", ".git"}
_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_FENCE = re.compile(r"^\s*(```|~~~)")
_CODE_SPAN = re.compile(r"`[^`]*`")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


def _markdown_files(repo: Path):
    for md in sorted(repo.rglob("*.md")):
        if _SKIP_DIRS.intersection(md.relative_to(repo).parts):
            continue
        yield md


def _relative_links(repo: Path):
    for md in _markdown_files(repo):
        in_fence = False
        for line in md.read_text(encoding="utf-8", errors="replace").splitlines():
            if _FENCE.match(line):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for target in _LINK.findall(_CODE_SPAN.sub("", line)):
                if _SCHEME.match(target) or target.startswith("#"):
                    continue
                path = target.split("#", 1)[0].split("?", 1)[0]
                if path:
                    yield md, path


def test_relative_markdown_links_resolve():
    broken = [
        (str(md.relative_to(REPO)), target)
        for md, target in _relative_links(REPO)
        if not (md.parent / target).exists()
    ]
    assert broken == []
