"""Paper-only adapter and existing signed account-risk assessment for the mechanics smoke."""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from algua.execution.alpaca_broker import AlpacaPaperBroker
from algua.execution.drawdown_cycle import _observe
from algua.primitives.bounded_file import read_relative_regular
from algua.provenance.lockfile import dependency_hash
from algua.registry.drawdown_store import account_state, policy_for
from algua.risk import global_halt
from algua.risk.layered import DrawdownPolicy, decimal

SYMBOL = "CSL"  # Owner-selected member of the approved 300-symbol midcap CONFIG.
PAPER_URL = "https://paper-api.alpaca.markets"
_SOURCE_ROOT = Path(__file__).resolve().parents[2]


class MechanicsBroker(AlpacaPaperBroker):
    def mechanics_readiness(self, symbol: str) -> dict:
        account = self._read(self._get("/v2/account"), "/v2/account")
        asset_path = "/v2/assets/" + quote(symbol, safe="")
        asset = self._read(self._get(asset_path), asset_path)
        if not isinstance(account, dict) or not isinstance(asset, dict):
            raise ValueError("paper account/asset response is malformed")
        return {key: account.get(key) for key in (
            "id", "status", "currency", "trading_blocked", "account_blocked"
        )} | {"asset": asset}


def readiness(broker, expected_account: str | None, symbol: str = SYMBOL) -> dict:
    if (not isinstance(broker, MechanicsBroker) or broker.base_url != PAPER_URL
            or (expected_account is not None and not expected_account.strip()) or symbol != SYMBOL):
        raise ValueError("exact paper host, expected account and permitted CSL symbol required")
    raw = broker.mechanics_readiness(symbol)
    asset = raw["asset"]
    if (not isinstance(raw.get("id"), str) or not raw["id"]
            or (expected_account is not None and raw.get("id") != expected_account)
            or raw.get("status") != "ACTIVE"
            or raw.get("currency") != "USD" or raw.get("trading_blocked") is not False
            or raw.get("account_blocked") is not False
            or asset.get("symbol") != symbol or asset.get("status") != "active"
            or asset.get("class") != "us_equity" or asset.get("tradable") is not True
            or asset.get("fractionable") is not True):
        raise ValueError("paper account mismatch/blocked or asset not active/tradable/fractionable")
    return raw


def risk_guard(
    conn, broker, expected_account: str, *, opening: bool,
) -> tuple[dict, DrawdownPolicy]:
    """Reuse the risk controller's real persisted assessment; never manufacture a cycle grant."""
    prior = account_state(conn, "paper")
    if prior is None or prior["account_id"] != expected_account:
        raise ValueError("matching signed paper risk policy is required")
    policy = policy_for(conn, prior)
    row = conn.execute("SELECT * FROM drawdown_policies WHERE id=?", (prior["policy_id"],)
                       ).fetchone()
    if (not row["principal"] or not prior.get("last_human_action", {}).get("principal")
            or decimal(policy.normal_capital) > 5
            or decimal(prior["baseline_nav"]) > 5
            or tuple(policy.permitted_symbols) != (SYMBOL,)
            or decimal(policy.reduce_at) > decimal(".10")
            or decimal(policy.halt_at) > decimal(".20")
            or decimal(policy.reduced_fraction) > decimal(".50")
            or prior.get("blocked_reason")):
        raise ValueError("signed paper policy is missing, blocked or exceeds smoke limits")
    for table in ("strategies", "paper_orders", "paper_venue_orders", "live_orders",
                  "tick_snapshots"):
        if conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
            raise ValueError("mechanics requires an isolated risk registry without trading records")
    observed, policy = _observe(conn, broker, prior)
    if opening and (observed["severity"] != 0 or global_halt.is_engaged(conn)):
        raise ValueError("account risk guard blocks opening purchases")
    if broker.account().account_id != expected_account:
        raise ValueError("paper account identity changed")
    if not 0 <= (datetime.now(UTC) - datetime.fromisoformat(observed["observed_at"])
                 ).total_seconds() <= 60:
        raise ValueError("fresh paper risk assessment required")
    return observed, policy


def opening_coid(conn, state: dict) -> str:
    row = conn.execute("SELECT created_at FROM drawdown_policies WHERE id=?",
                       (state["policy_id"],)).fetchone()
    identity = f'{state["account_id"]}:{state["policy_id"]}:{row[0]}:{SYMBOL}'
    return "pm-open-" + hashlib.sha256(identity.encode()).hexdigest()[:32]


def source_identity() -> dict:
    """The actual immutable release receipt, without asserting qualification or a sandbox."""
    root = _SOURCE_ROOT

    def git(*args):
        output = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                                text=True).stdout
        return output if "-z" in args else output.strip()

    if (Path(git("rev-parse", "--show-toplevel")) != root
            or git("status", "--porcelain", "--untracked-files=no")):
        raise ValueError("paper mechanics requires a clean committed source checkout")
    commit = git("rev-parse", "HEAD")
    names = git("ls-files", "--others", "--exclude-standard", "-z")
    untracked = set(filter(None, names.split("\0")))
    if untracked - {"application-runtime.json"}:
        raise ValueError("paper mechanics refuses unexpected untracked source files")
    runtime_digest = None
    marker = root / "application-runtime.json"
    if marker.exists() or marker.is_symlink():
        raw = read_relative_regular(root, "application-runtime.json", 64 * 1024)
        profile = json.loads(raw)
        builder = root / "deploy/scripts/build-paper-release.py"
        builder_digest = hashlib.sha256(builder.read_bytes()).hexdigest()
        if (not isinstance(profile, dict) or profile.get("profile") != "algua-application/v1"
                or profile.get("commit") != commit or profile.get("editable") is not False
                or profile.get("self_contained_runtime") is not False
                or profile.get("builder_sha256") != builder_digest):
            raise ValueError("paper application runtime metadata is not bound to this source")
        runtime_digest = hashlib.sha256(raw).hexdigest()
    digest = dependency_hash()
    if digest is None:
        raise ValueError("paper mechanics requires a locked dependency identity")
    return {"commit": commit, "dependency_hash": digest, "runtime_metadata_hash": runtime_digest}
