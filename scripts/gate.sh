#!/usr/bin/env bash
set -euo pipefail
uv run pytest -q -o addopts=
uv run ruff check .
uv run mypy algua
uv run lint-imports
