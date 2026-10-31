from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import pandas as pd
import pytest

from algua.data.files import logical_bars_hash
from algua.data.research_provenance import DataTier, ProvenanceDeclaration
from algua.data.store import DataStore
from scripts.pilot_proxy import (
    DEFAULT_SOURCE_URL,
    Campaign,
    ComponentOutcome,
    RecipeError,
    _run_components,
    build_child_env,
    build_parser,
    discover_git_worktree_roots,
    installed_algua_executable,
    parse_source_csv,
    parse_source_payload,
    request_label,
    run_cli_attempt,
    validate_request,
)
from scripts.pilot_proxy_audit import audit_snapshot


def _csv(*symbols: str) -> bytes:
    rows = ["Symbol,Security"] + [
        f"{symbol},Company {index}" for index, symbol in enumerate(symbols)
    ]
    return ("\n".join(rows) + "\n").encode()


def _html(*symbols: str) -> bytes:
    rows = "".join(
        f"<tr><td>{symbol}</td><td>Company {index}</td></tr>"
        for index, symbol in enumerate(symbols)
    )
    return (
        '<html><table id="constituents"><tr><th>Symbol</th><th>Security</th></tr>'
        f"{rows}</table></html>"
    ).encode()


def _fake_curl(tmp_path: Path, body: str) -> Path:
    executable = tmp_path / "curl"
    executable.write_text(f"#!{sys.executable}\n{body}\n", encoding="utf-8")
    executable.chmod(0o755)
    return executable


def test_default_source_and_batch_are_current_wikipedia_single_campaign() -> None:
    args = build_parser(DEFAULT_SOURCE_URL).parse_args(
        ["--output", "/tmp/pilot", "--start", "2024-01-01", "--end", "2024-02-01"]
    )

    assert DEFAULT_SOURCE_URL == "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"
    assert args.batch_size == 150


def test_wikipedia_html_parser_uses_constituents_table_and_preserves_source_kind() -> None:
    document = parse_source_payload(_html("ZZZ", "BRK.B", "AAA"), count=2)

    assert document.filename == "constituents.html"
    assert document.selection.source_symbols == ("ZZZ", "BRK.B", "AAA")
    assert document.selection.selected == (
        {"source_symbol": "AAA", "yahoo_symbol": "AAA"},
        {"source_symbol": "BRK.B", "yahoo_symbol": "BRK-B"},
    )
    with pytest.raises(RecipeError, match="constituents"):
        parse_source_payload(b"<html><table id='other'></table></html>", count=1)


def test_source_selection_is_sorted_unique_and_accounts_for_every_exclusion() -> None:
    selection = parse_source_csv(_csv("ZZZ", "BRK.B", "AAA", "AAA", "CCC"), count=2)

    assert selection.source_symbols == ("ZZZ", "BRK.B", "AAA", "AAA", "CCC")
    assert selection.selected == (
        {"source_symbol": "AAA", "yahoo_symbol": "AAA"},
        {"source_symbol": "BRK.B", "yahoo_symbol": "BRK-B"},
    )
    assert selection.excluded == (
        {"source_symbol": "AAA", "reason": "duplicate_source_symbol"},
        {"source_symbol": "CCC", "reason": "beyond_first_n"},
        {"source_symbol": "ZZZ", "reason": "beyond_first_n"},
    )


def test_source_selection_rejects_alias_collisions_and_malformed_csv() -> None:
    with pytest.raises(RecipeError, match="alias collision"):
        parse_source_csv(_csv("BRK.B", "BRK-B"), count=2)
    with pytest.raises(RecipeError, match="Symbol"):
        parse_source_csv(b"Ticker,Security\nAAPL,Apple\n", count=1)
    with pytest.raises(RecipeError, match="malformed"):
        parse_source_csv(b'Symbol,Security\nAAPL,"unterminated\n', count=1)
    with pytest.raises(RecipeError, match="requested 3"):
        parse_source_csv(_csv("AAPL", "MSFT"), count=3)


def test_request_bounds_fail_closed(tmp_path: Path) -> None:
    output = tmp_path / "new-campaign"
    validate_request(output, "2024-01-01", "2024-02-01", 150, 25, 2, 300, today=date(2026, 1, 1))
    validate_request(output, "2024-01-01", "2024-02-01", 300, 300, 3, 300, today=date(2026, 1, 1))

    output.mkdir()
    (output / "campaign_manifest.json").write_text("{}")
    with pytest.raises(RecipeError, match="empty"):
        validate_request(
            output, "2024-01-01", "2024-02-01", 150, 25, 2, 300, today=date(2026, 1, 1)
        )
    with pytest.raises(RecipeError, match="count"):
        validate_request(
            tmp_path / "other", "2024-01-01", "2024-02-01", 301, 25, 2, 300, today=date(2026, 1, 1)
        )
    with pytest.raises(RecipeError, match="future"):
        validate_request(
            tmp_path / "other", "2024-01-01", "2026-01-02", 150, 25, 2, 300, today=date(2026, 1, 1)
        )
    with pytest.raises(RecipeError, match="batch-size"):
        validate_request(
            tmp_path / "other",
            "2024-01-01",
            "2024-02-01",
            150,
            301,
            2,
            300,
            today=date(2026, 1, 1),
        )


def test_request_rejects_main_repo_and_every_discovered_worktree() -> None:
    repo = Path(__file__).resolve().parents[1]
    roots = discover_git_worktree_roots(repo)

    assert repo in roots
    assert any(root.name == "algua" for root in roots)
    for root in roots:
        with pytest.raises(RecipeError, match="git worktree"):
            validate_request(
                root / "private-output",
                "2024-01-01",
                "2024-02-01",
                150,
                150,
                2,
                300,
                today=date(2026, 1, 1),
            )


def test_child_environment_is_clean_and_isolated(tmp_path: Path) -> None:
    parent = {
        "PATH": "/untrusted/bin",
        "HOME": "/real/home",
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
        "SSL_CERT_FILE": "/certs/bundle.pem",
        "SECRET_TOKEN": "do-not-copy",
        "ALGUA_DATA_DIR": "/wrong",
    }

    env = build_child_env(tmp_path, Path("/venv/bin/algua"), parent)

    assert env == {
        "PATH": "/venv/bin:/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
        "SSL_CERT_FILE": "/certs/bundle.pem",
        "ALGUA_DATA_DIR": str(tmp_path / "data"),
        "ALGUA_DB_PATH": str(tmp_path / "registry.sqlite"),
    }


def test_installed_algua_executable_stays_beside_venv_symlink(tmp_path: Path) -> None:
    bin_dir = tmp_path / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    python = bin_dir / "python"
    python.symlink_to("/usr/bin/python3.12")
    algua = bin_dir / "algua"
    algua.write_text("#!/bin/sh\n")

    assert installed_algua_executable(str(python)) == algua.absolute()


@pytest.mark.parametrize(
    ("result", "expected_status"),
    [
        (subprocess.CompletedProcess(["algua"], 1, "{}", "failed"), "nonzero"),
        (subprocess.CompletedProcess(["algua"], 0, "not-json", ""), "invalid_json"),
    ],
)
def test_cli_attempt_records_bounded_failure_logs(
    tmp_path: Path,
    result: subprocess.CompletedProcess[str],
    expected_status: str,
) -> None:
    observed: dict[str, datetime] = {}

    def runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        observed["inside"] = datetime.now(UTC)
        time.sleep(0.001)
        return result

    attempt = run_cli_attempt(
        ["/venv/bin/algua", "data", "inspect"],
        env={},
        cwd=tmp_path,
        timeout=5,
        logs_dir=tmp_path / "logs",
        label="inspect",
        attempt=1,
        runner=runner,
    )

    assert attempt["status"] == expected_status
    assert Path(attempt["stdout_log"]).read_text() == result.stdout
    assert Path(attempt["stderr_log"]).read_text() == result.stderr
    assert datetime.fromisoformat(attempt["started_at"]) <= observed["inside"]
    assert datetime.fromisoformat(attempt["finished_at"]) >= observed["inside"]


def test_long_request_label_and_symbols_are_checkpointed_before_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "campaign"
    for name in ("data", "home", "logs", "source", "work"):
        (output / name).mkdir(parents=True, exist_ok=True)
    symbols = [f"S{index:03d}" for index in range(300)]
    label = request_label("batch-1", symbols)
    observed: dict[str, object] = {}

    def runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        manifest = json.loads((output / "campaign_manifest.json").read_text())
        observed["symbols"] = manifest["requests"][-1]["symbols"]
        return subprocess.CompletedProcess(["algua"], 1, "{}", "failed")

    monkeypatch.setattr(subprocess, "run", runner)
    campaign = Campaign(
        output=output,
        executable=Path("/venv/bin/algua"),
        env={},
        start="2024-01-01",
        end="2024-02-01",
        method="method",
        attempts=1,
        timeout=5,
        today=date(2026, 1, 1),
        state={"requests": [], "components": []},
    )
    campaign.save()

    assert campaign.ingest(symbols, designation="batch-1", campaign=True) is None
    assert campaign.ingest(symbols, designation="batch-1", campaign=True) is None
    assert observed["symbols"] == symbols
    logs = list((output / "logs").iterdir())
    assert len(logs) == 4
    assert len({path.name for path in logs}) == 4
    assert all(len(path.name.encode()) <= 255 for path in logs)
    assert label.startswith("batch-1-") and len(label) < 80


def test_source_download_enforces_https_for_initial_and_redirect_urls(tmp_path: Path) -> None:
    from scripts.pilot_proxy_source import download_source

    (tmp_path / "logs").mkdir()
    state: dict[str, Any] = {"requests": []}
    curl = _fake_curl(
        tmp_path,
        """
import sys
required = {
    "--location", "--fail", "--silent", "--show-error",
    "--max-time", "5", "--max-filesize", "8388608",
    "--proto", "=https", "--proto-redir", "=https",
    "--user-agent", "AlguaResearchProxy/1.0",
}
if not required.issubset(sys.argv[1:]):
    raise SystemExit(91)
sys.stdout.buffer.write(b"original source response")
""",
    )

    with pytest.raises(RecipeError, match="HTTPS"):
        download_source(
            "http://example.com/source",
            output=tmp_path,
            attempts=1,
            timeout=5,
            state=state,
            save=lambda: None,
            curl_executable=curl,
        )
    payload = download_source(
        DEFAULT_SOURCE_URL,
        output=tmp_path,
        attempts=1,
        timeout=5,
        state=state,
        save=lambda: None,
        curl_executable=curl,
    )
    assert payload == b"original source response"
    assert state["requests"][1]["status"] == "success"


def test_source_download_ignores_ambient_curl_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from algua.primitives.bounded_subprocess import BoundedCompletion, run_bounded
    from scripts import pilot_proxy_source

    curl = Path("/usr/bin/curl")
    assert curl.is_file()
    marker = b"ambient-curlrc-loaded"
    curl_home = tmp_path / "curl-home"
    curl_home.mkdir()
    (curl_home / ".curlrc").write_text(
        f'write-out = "{marker.decode()}"\n', encoding="utf-8"
    )
    monkeypatch.setenv("CURL_HOME", str(curl_home))
    url = "https://127.0.0.1:1/source"

    control = run_bounded(
        [str(curl), "--max-time", "1", "--proto", "=https", "--url", url],
        env=os.environ,
        timeout=1,
        max_stdout=1024,
        max_stderr=64 * 1024,
    )
    assert control.returncode != 0
    assert marker in control.stdout

    observed_stdout: list[bytes] = []

    def recording_run_bounded(
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        timeout: float,
        max_stdout: int,
        max_stderr: int,
    ) -> BoundedCompletion:
        result = run_bounded(
            argv,
            env=env,
            timeout=timeout,
            max_stdout=max_stdout,
            max_stderr=max_stderr,
        )
        observed_stdout.append(result.stdout)
        return result

    monkeypatch.setattr(pilot_proxy_source, "run_bounded", recording_run_bounded)
    (tmp_path / "logs").mkdir()
    state: dict[str, Any] = {"requests": []}

    with pytest.raises(RecipeError, match="source download failed"):
        pilot_proxy_source.download_source(
            url,
            output=tmp_path,
            attempts=1,
            timeout=1,
            state=state,
            save=lambda: None,
            curl_executable=curl,
        )

    assert len(observed_stdout) == 1
    assert marker not in observed_stdout[0]


def test_source_download_rejects_oversized_response_during_streaming(tmp_path: Path) -> None:
    from scripts.pilot_proxy_source import download_source

    (tmp_path / "logs").mkdir()
    state: dict[str, Any] = {"requests": []}
    curl = _fake_curl(
        tmp_path,
        """
import os
chunk = b"x" * 65536
for _ in range(129):
    os.write(1, chunk)
""",
    )

    with pytest.raises(RecipeError, match="source download failed"):
        download_source(
            DEFAULT_SOURCE_URL,
            output=tmp_path,
            attempts=1,
            timeout=5,
            state=state,
            save=lambda: None,
            curl_executable=curl,
        )

    assert state["requests"][0]["attempts"][0]["status"] == "network_error"
    assert "byte bound" in (tmp_path / "logs/source-download.attempt-1.stderr.log").read_text()


def test_source_download_stops_slow_stream_at_total_deadline(tmp_path: Path) -> None:
    from scripts.pilot_proxy_source import download_source

    (tmp_path / "logs").mkdir()
    state: dict[str, Any] = {"requests": []}
    curl = _fake_curl(
        tmp_path,
        """
import os
import time
while True:
    os.write(1, b"x")
    time.sleep(0.2)
""",
    )
    started = time.monotonic()

    with pytest.raises(RecipeError, match="source download failed"):
        download_source(
            DEFAULT_SOURCE_URL,
            output=tmp_path,
            attempts=1,
            timeout=1,
            state=state,
            save=lambda: None,
            curl_executable=curl,
        )

    elapsed = time.monotonic() - started
    assert 0.8 <= elapsed < 1.8
    assert state["requests"][0]["attempts"][0]["status"] == "network_error"
    assert "timed out" in (tmp_path / "logs/source-download.attempt-1.stderr.log").read_text()


def test_source_download_failure_is_bounded_checkpointed_and_never_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "campaign"
    for name in ("data", "home", "logs", "source", "work"):
        (output / name).mkdir(parents=True, exist_ok=True)
    calls = 0

    def failing_download(*_args: object, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        raise OSError("offline")

    monkeypatch.setattr("scripts.pilot_proxy_source.run_bounded", failing_download, raising=False)
    campaign = Campaign(
        output=output,
        executable=Path("/venv/bin/algua"),
        env={},
        start="2024-01-01",
        end="2024-02-01",
        method="pending",
        attempts=2,
        timeout=5,
        today=date(2026, 1, 1),
        state={"status": "initializing", "requests": [], "components": []},
    )
    campaign.save()

    with pytest.raises(RecipeError, match="source download failed"):
        campaign.download_source("https://example.invalid/source")

    saved = json.loads(campaign.manifest.read_text())
    assert calls == 2
    assert saved["status"] == "failed"
    assert saved["failure"] == "source_download_failed"
    assert [item["status"] for item in saved["requests"][-1]["attempts"]] == [
        "network_error",
        "network_error",
    ]
    assert saved["components"] == []


def test_cli_attempt_records_timeout(tmp_path: Path) -> None:
    def runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(["algua"], 5, output="partial", stderr="late")

    attempt = run_cli_attempt(
        ["/venv/bin/algua"],
        env={},
        cwd=tmp_path,
        timeout=5,
        logs_dir=tmp_path / "logs",
        label="timeout",
        attempt=2,
        runner=runner,
    )

    assert attempt["status"] == "timeout"
    assert Path(attempt["stdout_log"]).read_text() == "partial"
    assert Path(attempt["stderr_log"]).read_text() == "late"


def test_failed_batch_falls_back_individually_without_replacement() -> None:
    class FakeCampaign:
        def __init__(self) -> None:
            self.state: dict[str, object] = {}
            self.calls: list[tuple[list[str], str, bool]] = []

        def ingest(
            self, symbols: list[str], *, designation: str, campaign: bool
        ) -> dict[str, object] | None:
            self.calls.append((symbols, designation, campaign))
            if not campaign or symbols == ["AAA"]:
                return {"snapshot": {"snapshot_id": designation}}
            return None

        def save(self) -> None:
            pass

    fake = FakeCampaign()
    outcome = _run_components(cast(Campaign, fake), ["AAA", "BBB"], 2)

    assert outcome == ComponentOutcome(True, frozenset({"AAA"}), ("BBB",))
    assert fake.calls == [
        (["AAA", "BBB"], "probe", False),
        (["AAA", "BBB"], "batch-1", True),
        (["AAA"], "fallback-AAA", True),
        (["BBB"], "fallback-BBB", True),
    ]


def test_successful_first_150_is_one_campaign_component() -> None:
    selected = [f"S{index:03d}" for index in range(150)]

    class FakeCampaign:
        def __init__(self) -> None:
            self.state: dict[str, object] = {}
            self.calls: list[tuple[list[str], str, bool]] = []

        def ingest(
            self, symbols: list[str], *, designation: str, campaign: bool
        ) -> dict[str, object]:
            self.calls.append((symbols, designation, campaign))
            return {"snapshot": {"snapshot_id": designation}}

        def save(self) -> None:
            pass

    fake = FakeCampaign()
    outcome = _run_components(cast(Campaign, fake), selected, 150)

    assert outcome == ComponentOutcome(True, frozenset(selected), ())
    assert fake.calls == [
        (selected[:2], "probe", False),
        (selected, "batch-1", True),
    ]


def test_probe_refusal_stops_before_campaign_requests() -> None:
    class RefusingCampaign:
        def __init__(self) -> None:
            self.state: dict[str, object] = {}
            self.calls = 0

        def ingest(self, *_args: object, **_kwargs: object) -> None:
            self.calls += 1

        def save(self) -> None:
            pass

    fake = RefusingCampaign()
    outcome = _run_components(cast(Campaign, fake), ["AAA", "BBB"], 150)

    assert outcome == ComponentOutcome(False, frozenset(), ("AAA", "BBB"))
    assert fake.calls == 1
    assert fake.state == {"status": "failed", "failure": "probe_failed"}


def test_ingest_retry_is_bounded_and_never_replaces_failed_symbol(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "campaign"
    for name in ("data", "home", "logs", "source", "work"):
        (output / name).mkdir(parents=True, exist_ok=True)
    commands: list[list[str]] = []

    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command.copy())
        return subprocess.CompletedProcess(command, 1, "{}", "failed")

    monkeypatch.setattr(subprocess, "run", runner)
    campaign = Campaign(
        output=output,
        executable=Path("/venv/bin/algua"),
        env={},
        start="2024-01-01",
        end="2024-02-01",
        method="method",
        attempts=2,
        timeout=5,
        today=date(2026, 1, 1),
        state={"requests": [], "components": []},
    )
    campaign.save()

    assert campaign.ingest(["FAILED"], designation="batch-1", campaign=True) is None
    assert len(commands) == 2
    assert all(command[command.index("--symbols") + 1] == "FAILED" for command in commands)
    assert campaign.state["components"] == []


def test_audit_recomputes_identity_coverage_and_physical_hashes(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    frame = pd.DataFrame(
        {
            "ts": pd.to_datetime(["2024-01-02", "2024-01-03"], utc=True),
            "symbol": ["AAPL", "AAPL"],
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
            "adj_close": [101.0, 102.0],
            "volume": [1000.0, 1100.0],
        }
    )
    rec = DataStore(data_dir).ingest_bars(
        provider="yfinance",
        symbols=["AAPL"],
        start="2024-01-02",
        end="2024-01-04",
        as_of="2024-01-05T00:00:00+00:00",
        source="yfinance",
        frame=frame,
        provenance=ProvenanceDeclaration(DataTier.PILOT_REAL_PROXY, "test-current/v1"),
    )
    inspected = rec.to_dict()
    verified = {
        "ok": True,
        "verified": 1,
        "failed": 0,
        "snapshots": [
            {
                "snapshot_id": rec.snapshot_id,
                "dataset": "bars",
                "storage_format": "parquet_dataset",
                "ok": True,
                "error": None,
            }
        ],
    }

    audit = audit_snapshot(
        data_dir=data_dir,
        snapshot=inspected,
        inspected=inspected,
        verified=verified,
        requested_symbols=["AAPL"],
        start="2024-01-02",
        end="2024-01-04",
        today=date(2026, 1, 1),
        retrieved_at=datetime(2024, 1, 5, tzinfo=UTC),
    )

    assert audit["logical_bars_hash"] == logical_bars_hash(frame)
    assert audit["repeated_readback_hash"] == audit["logical_bars_hash"]
    assert audit["symbols"] == ["AAPL"]
    assert audit["coverage"]["AAPL"]["row_count"] == 2
    assert audit["coverage"]["AAPL"]["missing_sessions"] == []
    assert len(audit["physical_files"]) == 1
    assert len(audit["physical_files"][0]["sha256"]) == 64


def test_audit_rejects_inspect_mismatch_and_tampered_payload(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    frame = pd.DataFrame(
        {
            "ts": pd.to_datetime(["2024-01-02"], utc=True),
            "symbol": ["AAPL"],
            "open": [1.0],
            "high": [1.0],
            "low": [1.0],
            "close": [1.0],
            "adj_close": [1.0],
            "volume": [1.0],
        }
    )
    rec = DataStore(data_dir).ingest_bars(
        provider="yfinance",
        symbols=["AAPL"],
        start="2024-01-02",
        end="2024-01-03",
        as_of="2024-01-03T00:00:00+00:00",
        source="yfinance",
        frame=frame,
        provenance=ProvenanceDeclaration(DataTier.PILOT_REAL_PROXY, "test-current/v1"),
    )
    verified = {
        "ok": True,
        "verified": 1,
        "failed": 0,
        "snapshots": [{"snapshot_id": rec.snapshot_id, "ok": True}],
    }
    with pytest.raises(RecipeError, match="inspect"):
        audit_snapshot(
            data_dir=data_dir,
            snapshot=rec.to_dict(),
            inspected={**rec.to_dict(), "row_count": 99},
            verified=verified,
            requested_symbols=["AAPL"],
            start="2024-01-02",
            end="2024-01-03",
            today=date(2026, 1, 1),
            retrieved_at=datetime.now(UTC),
        )

    parquet = next((data_dir / rec.data_path).rglob("*.parquet"))
    tampered = pd.read_parquet(parquet)
    tampered.loc[0, "close"] += 0.5
    tampered.to_parquet(parquet, index=False)
    with pytest.raises(RecipeError, match="logical bars hash"):
        audit_snapshot(
            data_dir=data_dir,
            snapshot=rec.to_dict(),
            inspected=rec.to_dict(),
            verified=verified,
            requested_symbols=["AAPL"],
            start="2024-01-02",
            end="2024-01-03",
            today=date(2026, 1, 1),
            retrieved_at=datetime.now(UTC),
        )


def test_audit_rejects_unlabeled_yfinance_snapshot(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    frame = pd.DataFrame(
        {
            "ts": pd.to_datetime(["2024-01-02"], utc=True),
            "symbol": ["AAPL"],
            "open": [1.0],
            "high": [1.0],
            "low": [1.0],
            "close": [1.0],
            "adj_close": [1.0],
            "volume": [1.0],
        }
    )
    rec = DataStore(data_dir).ingest_bars(
        provider="yfinance",
        symbols=["AAPL"],
        start="2024-01-02",
        end="2024-01-03",
        as_of="2024-01-03T00:00:00+00:00",
        source="yfinance",
        frame=frame,
    )
    verified = {
        "ok": True,
        "verified": 1,
        "failed": 0,
        "snapshots": [{"snapshot_id": rec.snapshot_id, "ok": True}],
    }

    with pytest.raises(RecipeError, match="pilot_real_proxy"):
        audit_snapshot(
            data_dir=data_dir,
            snapshot=rec.to_dict(),
            inspected=rec.to_dict(),
            verified=verified,
            requested_symbols=["AAPL"],
            start="2024-01-02",
            end="2024-01-03",
            today=date(2026, 1, 1),
            retrieved_at=datetime.now(UTC),
        )
