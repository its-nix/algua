"""Local opaque artifact registration/inspection; training metadata remains declared."""
from __future__ import annotations

import json
import math
import os
import stat
from pathlib import Path
from typing import Any

import typer

from algua import models
from algua.cli._common import ok
from algua.cli.app import emit
from algua.cli.errors import json_errors
from algua.contracts.model_types import ModelVersion, normalize_as_of

model_app = typer.Typer(help="Local declared model artifacts; no training or qualification",
                        no_args_is_help=False)
_METADATA_BYTES = 1024 * 1024
_ARTIFACT_BYTES = 64 * 1024 * 1024
_FIELDS = {"training_snapshot_id", "training_as_of", "code_hash", "hyperparameters",
           "seed", "eval_report"}


def _read_input(path: Path, limit: int, label: str) -> bytes:
    """Cap CLI inputs; registry operations retain their existing I/O semantics."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"{label} must be a regular file")
        if info.st_size > limit:
            raise ValueError(f"{label} exceeds its {limit}-byte input limit")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ValueError(f"{label} exceeds its {limit}-byte input limit")
        return raw
    finally:
        os.close(descriptor)


def _unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("model metadata contains a duplicate field")
        value[key] = item
    return value


def _nonfinite(value: str) -> None:
    raise ValueError("model metadata contains a nonfinite number")


def _metadata(path: Path) -> dict[str, Any]:
    raw = _read_input(path, _METADATA_BYTES, "metadata")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_fields,
                           parse_constant=_nonfinite)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("model metadata must be finite UTF-8 JSON") from exc
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise ValueError("model metadata requires exactly the six declared training fields")
    if any(value[key] is not None and not isinstance(value[key], str)
           for key in ("training_snapshot_id", "code_hash")):
        raise ValueError("model snapshot and code declarations must be strings or null")
    if (not isinstance(value["training_as_of"], str)
            or any(value[key] is not None and not isinstance(value[key], dict)
                   for key in ("hyperparameters", "eval_report"))
            or value["seed"] is not None and type(value["seed"]) is not int):
        raise ValueError("model metadata has invalid declared training field types")
    try:
        cutoff = normalize_as_of(value["training_as_of"])
        if cutoff != cutoff:  # NaT parses without raising; preserve all valid original text.
            raise ValueError("nonfinite training cutoff")
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("model training_as_of must be a valid finite timestamp") from exc
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, float) and not math.isfinite(item):
            # json's exponent overflow (1e400) does not invoke parse_constant.
            raise ValueError("model metadata contains a nonfinite number")
    return value


def _public(version: ModelVersion) -> dict[str, Any]:
    return version.as_ref().as_dict() | {key: getattr(version, key) for key in (
        "created_at", "training_snapshot_id", "code_hash", "seed")}


@model_app.callback(invoke_without_command=True)
def require_command(ctx: typer.Context) -> None:
    # Leave UsageError to the existing main() parser handler, rather than the body decorator.
    if ctx.invoked_subcommand is None:
        raise typer.BadParameter("model requires register, show or list")


@model_app.command("register")
@json_errors
def register_model(name: str, artifact: Path = typer.Option(..., "--artifact"),
                   metadata: Path = typer.Option(..., "--metadata")) -> None:
    """Register prepared opaque local bytes with six explicit declared training fields."""
    declaration = _metadata(metadata)
    raw = _read_input(artifact, _ARTIFACT_BYTES, "artifact")
    emit(ok(_public(models.register(name, raw, **declaration))))


@model_app.command("show")
@json_errors
def show_model(name: str, version: int = typer.Option(..., "--version", min=1)) -> None:
    """Verify one explicit local version; registration is not PIT or predictive qualification."""
    emit(ok(_public(models.get_version(name, version))))


@model_app.command("list")
@json_errors
def list_models(name: str) -> None:
    """Verify all manifested versions of NAME, ascending; missing names return an empty list."""
    emit(ok({"versions": [_public(v) for v in models.list_versions(name)]}))
