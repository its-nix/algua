"""Bounded current-S&P-400/yfinance pilot proxy recipe."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from scripts.pilot_proxy_audit import (
    ComponentOutcome,
    audit_snapshot,
    build_child_env,
    initial_state,
    run_cli_attempt,
    validate_cli_surface,
    validate_request,
)
from scripts.pilot_proxy_audit import (
    run_components as _run_components,
)
from scripts.pilot_proxy_source import (
    RecipeError,
    build_parser,
    download_source,
    installed_algua_executable,
    prepare_source,
)
from scripts.pilot_proxy_source import (
    discover_git_worktree_roots as discover_git_worktree_roots,
)
from scripts.pilot_proxy_source import (
    parse_source_csv as parse_source_csv,
)
from scripts.pilot_proxy_source import (
    parse_source_payload as parse_source_payload,
)

DEFAULT_SOURCE_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"
__all__ = [
    "RecipeError",
    "ComponentOutcome",
    "discover_git_worktree_roots",
    "installed_algua_executable",
    "parse_source_csv",
    "parse_source_payload",
]


def request_label(designation: str, symbols: list[str]) -> str:
    """Build a bounded filesystem label while retaining symbols in the manifest."""
    safe = "".join(char if char.isalnum() or char in "-_" else "-" for char in designation)
    digest = hashlib.sha256("\0".join(symbols).encode()).hexdigest()[:12]
    return f"{safe[:40]}-{digest}"


def _checkpoint(path: Path, state: dict[str, Any]) -> None:
    staged = path.with_suffix(".tmp")
    staged.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    staged.replace(path)


@dataclass
class Campaign:
    output: Path
    executable: Path
    env: dict[str, str]
    start: str
    end: str
    method: str
    attempts: int
    timeout: int
    today: date
    state: dict[str, Any]

    @property
    def manifest(self) -> Path:
        return self.output / "campaign_manifest.json"

    def save(self) -> None:
        _checkpoint(self.manifest, self.state)

    def invoke(
        self,
        command: list[str],
        label: str,
        *,
        attempts: int | None = None,
        expect_json: bool = True,
        request_metadata: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        request: dict[str, Any] = {"label": label, "attempts": [], **(request_metadata or {})}
        self.state["requests"].append(request)
        self.save()
        log_label = f"{len(self.state['requests']):04d}-{label}"
        limit = attempts or self.attempts
        for number in range(1, limit + 1):
            if "--as-of" in command:
                command[command.index("--as-of") + 1] = datetime.now(UTC).isoformat()
            result = run_cli_attempt(
                command,
                env=self.env,
                cwd=self.output / "work",
                timeout=self.timeout,
                logs_dir=self.output / "logs",
                label=log_label,
                attempt=number,
                expect_json=expect_json,
            )
            request["attempts"].append(
                {key: value for key, value in result.items() if key != "payload"}
            )
            self.save()
            if result["status"] == "success":
                request["status"] = "success"
                self.save()
                return result["payload"], request
            if number < limit:
                time.sleep(0.25 * number)
        request["status"] = "failed"
        self.save()
        return None, request

    def ingest(
        self,
        symbols: list[str],
        *,
        designation: str,
        campaign: bool,
    ) -> dict[str, Any] | None:
        label = request_label(designation, symbols)
        command = [str(self.executable), "data", "ingest-bars"]
        command += ["--provider", "yfinance", "--symbols", ",".join(symbols)]
        command += ["--start", self.start, "--end", self.end, "--timeframe", "1d"]
        command += ["--adjustment", "none", "--as-of", "pending"]
        command += ["--data-tier", "pilot_real_proxy", "--universe-method", self.method]
        metadata = {"symbols": symbols, "designation": designation, "campaign": campaign}
        payload, request = self.invoke(command, label, request_metadata=metadata)
        if not isinstance(payload, dict) or not isinstance(payload.get("snapshot"), dict):
            request["status"] = "failed"
            self.save()
            return None
        snapshot = payload["snapshot"]
        snapshot_id = str(snapshot.get("snapshot_id", ""))
        inspected, _ = self.invoke(
            [str(self.executable), "data", "inspect", "--snapshot-id", snapshot_id],
            f"inspect-{snapshot_id}",
        )
        verified, _ = self.invoke(
            [str(self.executable), "data", "verify", "--snapshot-id", snapshot_id],
            f"verify-{snapshot_id}",
        )
        if not isinstance(inspected, dict) or not isinstance(verified, dict):
            return None
        retrieved_at = datetime.fromisoformat(str(snapshot["as_of"]))
        audit = audit_snapshot(
            data_dir=self.output / "data",
            snapshot=snapshot,
            inspected=inspected,
            verified=verified,
            requested_symbols=symbols,
            start=self.start,
            end=self.end,
            today=self.today,
            retrieved_at=retrieved_at,
        )
        component = {
            "designation": designation,
            "campaign": campaign,
            "snapshot": snapshot,
            "audit": audit,
        }
        self.state["components"].append(component)
        self.save()
        return component

    def download_source(self, url: str) -> bytes:
        return download_source(
            url,
            output=self.output,
            attempts=self.attempts,
            timeout=self.timeout,
            state=self.state,
            save=self.save,
        )


def _record_source(campaign: Campaign, args: argparse.Namespace, payload: bytes) -> list[str]:
    download_attempt = campaign.state["requests"][-1]["attempts"][-1]
    prepared = prepare_source(
        payload,
        url=args.source_url,
        count=args.count,
        retrieved_at=download_attempt["finished_at"],
    )
    (campaign.output / "source" / prepared.filename).write_bytes(payload)
    campaign.method = prepared.method
    campaign.state.update(
        {
            "source": prepared.manifest,
            "requested": {
                "start": args.start,
                "end": args.end,
                "count": args.count,
                "batch_size": args.batch_size,
            },
            "status": "running",
        }
    )
    campaign.save()
    return list(prepared.selected)


def run(args: argparse.Namespace) -> int:
    output = Path(args.output).expanduser().absolute()
    today = datetime.now(UTC).date()
    validate_request(
        output,
        args.start,
        args.end,
        args.count,
        args.batch_size,
        args.attempts,
        args.timeout,
        today=today,
    )
    output.mkdir(parents=True, exist_ok=True)
    for name in ("data", "home", "logs", "source", "work"):
        (output / name).mkdir()
    executable = installed_algua_executable(sys.executable)
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise RecipeError(f"installed algua executable not found beside interpreter: {executable}")
    campaign = Campaign(
        output,
        executable,
        build_child_env(output, executable, os.environ),
        args.start,
        args.end,
        "pending",
        args.attempts,
        args.timeout,
        today,
        initial_state(),
    )
    campaign.save()
    validate_cli_surface(campaign)
    selected = _record_source(campaign, args, campaign.download_source(args.source_url))
    outcome = _run_components(campaign, selected, args.batch_size)
    succeeded, missing = outcome.successful, list(outcome.missing)
    campaign.state.update(
        {
            "status": "complete" if not missing else "failed",
            "successful_symbols": sorted(succeeded),
            "missing_symbols": missing,
            "row_total": sum(
                item["audit"]["row_count"]
                for item in campaign.state["components"]
                if item["campaign"]
            ),
        }
    )
    campaign.save()
    print(
        json.dumps(
            {
                "ok": not missing,
                "manifest": str(campaign.manifest),
                "selected": len(selected),
                "successful": len(succeeded),
                "missing": missing,
            },
            sort_keys=True,
        )
    )
    return 0 if not missing else 1


def main() -> None:
    try:
        raise SystemExit(run(build_parser(DEFAULT_SOURCE_URL).parse_args()))
    except (RecipeError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
