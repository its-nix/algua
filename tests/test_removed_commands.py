"""Guard: references to removed surfaces must not creep back into the operational tree."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

REPO_ROOT = Path(__file__).resolve().parent.parent
ROOTS = ["deploy", "scripts", ".opencode", ".claude/skills", ".github"]
SKIP_DIRS = {".superpowers", "web", "node_modules", "__pycache__", ".git"}
REMOVED = [
    "algua-web",
    "--project web",
    "research campaign-menu",
    "backtest replay",
    "governance record",
    "governance list",
    "governance overdue",
    "eval gate",
    "ingest-fundamentals",
    "query-fundamentals",
    "ingest-news",
    "query-news",
    "fetch-fundamentals",
    "fetch-news",
]


def _scan(roots: list[str]) -> Iterator[Path]:
    for root in roots:
        base = REPO_ROOT / root
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or SKIP_DIRS & set(path.relative_to(REPO_ROOT).parts):
                continue
            try:
                head = path.read_bytes()[:8192]
            except OSError:
                continue
            if b"\0" in head:
                continue
            yield path


@pytest.mark.parametrize("needle", REMOVED)
def test_removed_reference_absent(needle: str) -> None:
    hits = [
        str(p.relative_to(REPO_ROOT))
        for p in _scan(ROOTS)
        if p.name != "test_removed_commands.py" and needle in p.read_text(errors="ignore")
    ]
    assert hits == []


@pytest.mark.parametrize(
    "argv",
    [
        ["research", "campaign-menu"],
        ["backtest", "replay"],
        ["governance", "list"],
        ["eval", "gate"],
        ["data", "ingest-fundamentals"],
        ["data", "query-fundamentals"],
        ["data", "ingest-news"],
        ["data", "query-news"],
        ["data", "fetch-fundamentals"],
        ["data", "fetch-news"],
    ],
)
def test_removed_command_is_gone(argv: list[str]) -> None:
    from algua.cli.main import app

    assert CliRunner().invoke(app, [*argv, "--help"]).exit_code != 0
