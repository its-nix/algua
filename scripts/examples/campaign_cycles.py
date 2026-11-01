"""Two persisted SYNTHETIC_FIXTURE controller cycles; no strategy Python or runtime invocation.

Run with the prepared repository interpreter and --output-dir NEW_DIRECTORY. The example
exercises cycle-start --menu-only, explicit fixture choices, cycle-start --campaign and
cycle-finish. Real OpenCode chooser output uses the same {menu, selection} JSON boundary.
For the shell driver, capture the menu with the intended ALGUA_RESEARCH_CYCLE_ID as --run,
match its resource/category/TTL/source context, then pass --campaign FILE. The caller's
existing flock must cover capture, choice, claim and completion. A stale capture refuses;
no chooser response ever silently selects a top pick. This example proves fixture mechanics,
not OpenCode autonomy, containment, market economics, PIT, qualification or trial breadth.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from algua.contracts.idea import DataCapability, Horizon, IdeaStatus, Market, SourceType
from algua.registry.db import connect, migrate
from algua.registry.idea_scorecard import campaign_scorecard
from algua.registry.ideas import IdeaRepository

ROOT = Path(__file__).resolve().parents[2]


def run_example(directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=False)
    database = directory / "SYNTHETIC_FIXTURE.db"
    conn = connect(database)
    try:
        migrate(conn)
        for title, family in [("opening auction pressure persistence", "a"),
                              ("quarterly dividend seasonal drift", "a"),
                              ("overnight earnings dispersion reversal", "b"),
                              ("analyst forecast disagreement turnover", "b"),
                              ("weekly liquidity squeeze unwind", "c")]:
            IdeaRepository(conn).add(
                title=title, hypothesis=title, family=family, category=family,
                tags=["SYNTHETIC_FIXTURE"], source_type=SourceType.MANUAL,
                source_ref="SYNTHETIC_FIXTURE", source_date=None, source_note=None,
                required_data=[DataCapability.OHLCV], status=IdeaStatus.OPEN,
                market=Market.US_EQUITIES, horizon=Horizon.DAILY,
                falsification="SYNTHETIC_FIXTURE: no economic assertion")
    finally:
        conn.close()
    commands = []

    def cli(label: str, args: list[str]) -> dict:
        command = [sys.executable, "-c", "from algua.cli.main import main; main()",
                   "research", "idea", *args]
        # Fresh child, controlled fixture registry; never consumes the operator's configured DB.
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, env={
            **os.environ, "ALGUA_DB_PATH": str(database), "ALGUA_DATA_DIR": str(directory),
            "ALGUA_IDEA_CLAIM_TTL_MINUTES": "180", "ALGUA_IDEA_PREVIEW_HOLD_HOURS": "72"})
        commands.append({"command": command, "cwd": str(ROOT), "exit": result.returncode})
        (directory / f"{label}.json").write_text(result.stdout)
        if result.returncode not in (0, 1):
            raise RuntimeError(result.stderr or result.stdout)
        return json.loads(result.stdout)

    projection: dict = {"menus": [], "claims": [], "choices": [], "reasons": []}
    for name, ids, outcomes in [
        ("fixture-one", [1, 3], [(1, "holdout_negative"), (3, "run_error")]),
        ("fixture-two", [4, 2], [(4, "integrity_fail")]),
    ]:
        args = ["cycle-start", "--run", name, "--limit", "3"]
        menu = cli(f"{name}-menu", [*args, "--menu-only"])["menu"]
        assert menu == cli(f"{name}-repeat-menu", [*args, "--menu-only"])["menu"]
        choices = []
        for idea_id in ids:
            option = next(c for c in menu["choices"] if c["hypothesis_id"] == idea_id)
            reason = ("SYNTHETIC_FIXTURE chooser: test admitted mechanism" if name == "fixture-one"
                      else "SYNTHETIC_FIXTURE chooser: use ledger evidence; " + option["reason"])
            choices.append({**option, "reason": reason})
        campaign = {"menu": menu, "selection": {"menu_id": menu["menu_id"], "choices": choices}}
        choice_path = directory / f"{name}-choice.json"
        choice_path.write_text(json.dumps(campaign, indent=2) + "\n")
        started = cli(f"{name}-claims", [*args, "--campaign", str(choice_path)])
        assert started["ok"] and [i["id"] for i in started["claimed"]] == ids
        assert started["unfinished_count"] == len(ids)
        report = directory / f"{name}-trusted-worker.md"
        report.write_text("```json\n" + json.dumps({"hypotheses": [
            {"title": "Trusted fixture worker", "idea_id": i, "outcome": o,
             "reason": "SYNTHETIC_FIXTURE controlled outcome"} for i, o in outcomes]}) + "\n```\n")
        done = cli(f"{name}-results", ["cycle-finish", "--run", name, "--phase", "completed",
                   "--worker-exit", "0", "--report", str(report), "--evidence-ref", str(report)])
        assert done["attempts_total"] == len(ids) and done["unfinished_count"] == 0
        projection["menus"].append([c["hypothesis_id"] for c in menu["choices"]])
        projection["claims"].append(ids)
        projection["choices"].append(choices)
        projection["reasons"].append(done["attempts"])
    conn = connect(database)
    try:
        history = campaign_scorecard(conn)
        (directory / "ledger-feedback.json").write_text(json.dumps(history, indent=2) + "\n")
        projection["totals"] = history["totals"]
    finally:
        conn.close()
    # Paths/timestamps/tokens identify actual runs; deterministic decisions compare without them.
    projection["reasons"] = [[{k: a[k] for k in ("idea_id", "evidence_id", "outcome", "reason")}
                              for a in rows] for rows in projection["reasons"]]
    (directory / "commands.json").write_text(json.dumps(commands, indent=2) + "\n")
    return {"provenance": "SYNTHETIC_FIXTURE; not autonomous or economic acceptance",
            "registry": str(database),
            "registry_sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
            "deterministic_projection": projection}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    print(json.dumps(run_example(parser.parse_args().output_dir.resolve()), indent=2))
