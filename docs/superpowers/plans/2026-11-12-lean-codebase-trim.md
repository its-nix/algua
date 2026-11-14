# Lean codebase trim Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut test time and remove features nothing uses, without loosening any binding check.

**Architecture:** One branch per task, each stacked on the previous and each small enough to review
or revert alone. Removals are traced by imports and by references in `deploy/`, `scripts/`,
`.opencode/`, `.claude/skills/`, `.github/` and docs. Guard tests pin that removed commands stay
removed and that historical registry/data records stay readable.

**Tech Stack:** Python 3.12, uv, pytest + pytest-xdist, typer, SQLite registry, import-linter.

**Spec:** `docs/superpowers/specs/2026-11-12-lean-codebase-trim-design.md`

## Scope

This plan covers spec §5 steps 1–6. **Step 7 (statistics stack, §4.7–4.9) gets its own plan**,
written after Tasks 1–6 are merged. It is protected (CODEOWNERS), the largest step, and its code
shifts under the earlier removals. Writing it now would mean planning against code that will have
moved.

## Global Constraints

- No binding check loosened: PIT requirement, 63-observation floor, holdout Sharpe > 0, single-use
  holdout, integrity preflights, measured-breadth preflight, live wall, lane parity, risk and kill
  switches.
- Registry history stays readable. No destructive DB migration. Enum members and manifest dataset
  names used by existing records stay, even when their writer is removed.
- `algua.cli` cannot be imported on macOS (`os.waitid`). Run anything that imports the CLI in
  Linux:
  `docker run --rm -v "$PWD":/w -v algua-linux-venv:/venv -w /w -e UV_PROJECT_ENVIRONMENT=/venv -e UV_LINK_MODE=copy ghcr.io/astral-sh/uv:python3.12-bookworm uv run --frozen <cmd>`
  (written below as `LINUX <cmd>`). Run `uv sync --frozen` in the container after any dependency
  change.
- Each task ends green on these checks:
  - `LINUX pytest -q` (the default fast set once Task 1 lands);
  - `uv run ruff check .`;
  - `LINUX mypy algua scripts`;
  - `uv run lint-imports`.
- When a deleted module had a size-ratchet pin in `tests/test_module_size_ratchet.py`, remove the
  pin. When a kept module shrinks far below its pin, lower the pin.
- An import-linter contract whose subject modules are all deleted is removed. The commit message
  says why.
- Each PR reports before/after numbers: product lines, test lines, test count, and default and
  full run times.
- Commit on the task branch only. Pushing and opening PRs need the owner's go-ahead.

## Review Focus

1. **A deployed unit or agent script still calls a removed command.** It fails on the VPS at
   runtime, not in tests. Task 3 adds `tests/test_removed_commands.py`, which scans `deploy/`,
   `scripts/`, `.opencode/`, `.claude/skills/` and `.github/` for every removed command string.
   Tasks 4–5 extend its list.
2. **Old data snapshots of a removed kind** (fundamentals/news manifest records on the VPS) must
   still load in `data inspect` and `data verify`. Task 5 adds
   `test_manifest_with_fundamentals_record_still_lists`.
3. **A registry row whose strategy module was pruned.** `registry list` and `registry show` must
   still work. Task 6 adds `test_registry_show_survives_missing_strategy_module`.
4. **Tests sharing machine-global state under xdist** (fixed paths, the same data dir, ports, env)
   flake intermittently. Task 1 runs the parallel suite three times and requires identical results.
5. **Links to deleted docs.** Task 2 adds `tests/test_docs_links.py`, which fails on any relative
   markdown link in a kept doc that points at a missing file.

---

### Task 1: Parallel tests and a fast default run (spec §4.4, §4.12)

Branch: `chore/trim-1-test-speed` from `main`.

**Files:**
- Modify: `pyproject.toml`. Add `pytest-xdist` to `[dependency-groups].dev`. Under
  `[tool.pytest.ini_options]`, add:
  - `addopts = "-n auto -m 'not slow'"`;
  - `markers = ["slow: >5s; excluded by default, run with -m ''", "serial: must not run in parallel"]`.
- Modify: `uv.lock`, through `uv add --dev pytest-xdist`.
- Modify: `.github/workflows/ci.yml`. The `gate` job runs `uv run pytest -q -m "" --durations=20`.
- Modify: `tests/conftest.py`. Add a hook that puts every `serial`-marked test in
  `xdist_group("serial")`, so they run on one worker. The default run uses `--dist loadgroup`, so
  add `--dist loadgroup` to `addopts`.
- Modify: each test file that takes >5 s. Add `pytestmark` or a per-test `@pytest.mark.slow`.
- Modify: `CLAUDE.md`, "Fast delivery" section. Document the default run, `pytest -m ""` for the
  full set, and the `LINUX` command.

- [ ] **Step 1: Record the baseline.** Run
  `LINUX pytest -q --durations=0 > .superpowers/baseline.txt 2>&1` on `main`. Keep
  the pass/fail/error counts and the wall time, and list the failing node IDs. These are the
  pre-existing failures; Task 1 must not add any.
- [ ] **Step 2: Add xdist and the markers.** Make the `pyproject.toml`/`uv.lock`/`conftest.py`
  changes above.
- [ ] **Step 3: Mark slow tests.** Every test over 5.0 s in the baseline `--durations=0` output gets
  `slow`. Expected among them: `tests/research/test_eval_harness.py`,
  `tests/test_portfolio_long_replay.py`, `tests/test_research_campaign.py`,
  `tests/test_research_memory_driver.py`.
- [ ] **Step 4: Run the full set in parallel, three times.**
  `LINUX pytest -q -m "" -n auto` ×3.
  - Expected: the same failing set as the baseline every time, and nothing new.
  - A test that fails only in parallel gets its shared state fixed (a `tmp_path`, or per-test env
    through `monkeypatch`). Use `serial` only when the state is truly global, for example
    `operator.lock` semantics. Record each case in the commit message.
- [ ] **Step 5: Time the runs.** `LINUX pytest -q` (default) and `LINUX pytest -q -m ""` (full).
  - Expected: the default run is under 10 minutes on a 4-core machine.
  - Report both numbers against the baseline.
- [ ] **Step 6: Commit.** `chore(test): run pytest in parallel and skip slow tests by default`

---

### Task 2: Docs archive, link guard, and route correction (spec §4.11, §4.14)

Branch: `chore/trim-2-docs` from Task 1's branch.

**Files:**
- Create: `tests/test_docs_links.py`
- Delete: historical files under `docs/superpowers/plans/`, `docs/superpowers/specs/` and
  `docs/development/`, chosen by the rule below.
- Modify: `CLAUDE.md` (research promote bullet), `docs/architecture.md`, `docs/agent/capped-live.md`,
  `docs/vision-reconciliation.md`.

- [ ] **Step 1: Write the failing link guard.** It covers every `*.md` in the repo outside
  `node_modules`, `.superpowers` and `.venv`.

```python
def test_relative_markdown_links_resolve():
    broken = [(md, target) for md, target in _relative_links(REPO) if not (md.parent / target).exists()]
    assert broken == []
```

  `_relative_links` yields `(file, path)` for `[text](path)` links. It skips URLs (`scheme:`),
  pure `#anchors`, and links inside fenced code blocks, and it strips `#fragment` before checking.
- [ ] **Step 2: Run it.** `uv run pytest tests/test_docs_links.py -q`. If it fails on today's tree,
  fix those pre-existing links first, so the guard starts green.
- [ ] **Step 3: Choose the files to keep.**
  - Keep a file if any of these link to it (directly, or through a kept doc):
    `CLAUDE.md`, `AGENTS.md`, `README.md`, `docs/architecture.md`,
    `docs/vision-reconciliation.md`, `docs/PRD.md`, `docs/agent/**`, `docs/contracts/**`,
    `docs/acceptance/**`, `.claude/skills/**`, `.opencode/**`, or a docstring/comment under
    `algua/`.
  - Also keep a file if its first commit is within the last 14 days
    (`git log --diff-filter=A --format=%cs -- <file>`).
  - Delete the rest of `docs/superpowers/{plans,specs}/` and `docs/development/`.
  - Put the counts in the commit message.
- [ ] **Step 4: Rewrite dangling links.** A kept doc that linked a deleted file gets either
  the link text without the link, or a link to the file's last commit on GitHub. Prefer plain text.
- [ ] **Step 5: Correct the route text (spec §4.14).** Replace the `CLAUDE.md` sentence
  "The **FORWARD gate is the harsh threshold** (its Sharpe bar is 0.5× the holdout Sharpe recorded
  here, so overfit inflation self-punishes)." with:

  > On the STRICT route the forward gate is the harsh threshold (Sharpe ≥ max(0.5× holdout, 0.3) over
  > 63 broker-clocked sessions). On the CAPPED experimental route the edge is judged only by this
  > gate's out-of-sample holdout (Sharpe > 0, ≥63 bars) — a weak bar — while the five paper sessions
  > prove mechanics, not edge. The deflated-Sharpe signal recorded here is the advisory quality
  > measure and the candidate binding bar.

  Make the matching one-paragraph correction in `docs/architecture.md`,
  `docs/agent/capped-live.md` and `docs/vision-reconciliation.md`, where each describes the routes.
- [ ] **Step 6: Run the guard.** `uv run pytest tests/test_docs_links.py -q`. Expected: PASS.
- [ ] **Step 7: Commit.** `docs: archive historical plans/specs to git history and correct the capped-route quality text`

---

### Task 3: Remove the web app (spec §4.1)

Branch: `chore/trim-3-web` from Task 2's branch.

**Files:**
- Delete: `web/`, `deploy/systemd/algua-web.service`.
- Modify: `.github/workflows/ci.yml` (drop the `web` job), `deploy/systemd/install-user-units.sh`
  and `deploy/systemd/README.md` (drop the web unit), `CLAUDE.md` (drop the `web/` check
  paragraph), `docs/architecture.md`, and any other `web/` reference (`rg -n "web/|algua-web"`).
- Create: `tests/test_removed_commands.py`

- [ ] **Step 1: Write the guard (failing).**

```python
REMOVED = ["algua-web", "--project web"]

@pytest.mark.parametrize("needle", REMOVED)
def test_removed_reference_absent(needle):
    hits = [p for p in _scan(["deploy", "scripts", ".opencode", ".claude/skills", ".github"]) if needle in p.read_text(errors="ignore")]
    assert hits == []
```

  `_scan` yields text files under those roots and skips binaries.
- [ ] **Step 2: Run it.** `uv run pytest tests/test_removed_commands.py -q`. Expected: FAIL. CI
  and the unit still reference the web app.
- [ ] **Step 3: Delete and unwire.** Make the deletions and edits above.
- [ ] **Step 4: Run the checks.** The guard, `tests/test_docs_links.py` and the Global
  Constraints checks. Expected: all green.
- [ ] **Step 5: Note the VPS step in the PR.** The VPS still has an enabled `algua-web.service`.
  The owner disables it (`systemctl --user disable --now algua-web`) when merging. The plan does
  not touch the VPS.
- [ ] **Step 6: Commit.** `chore: remove the web monitor app (a new dashboard gets its own design)`

---

### Task 4: Remove unused command groups (spec §4.2, plus §4.8's eval harness)

Branch: `chore/trim-4-commands` from Task 3's branch. One commit per group.

**Interfaces:**
- Consumes: `tests/test_removed_commands.py` and its `REMOVED` list (Task 3).

**Groups:**
- **`research campaign-menu`**
  - Delete: `algua/cli/campaign_cmd.py`; `algua/registry/campaign_read.py` if nothing else imports
    it; their tests.
  - Keep: `algua/research/campaign_policy.py` and `algua/registry/campaign_selection.py`, which
    the research loop's `--choose-campaign` uses.
  - Update `docs/agent/midcap-research-campaign.md` and `docs/agent/research-profile.md`.
- **`backtest replay`**
  - Delete: `algua/cli/replay_cmd.py`, `tests/test_cli_portfolio_replay.py`,
    `tests/test_portfolio_long_replay.py` and other replay-only tests.
  - Keep: `live/paper_loop.py` and `execution/sim_broker.py`, which are shared.
  - Update `docs/agent/midcap-machinery.md`.
- **`governance record|list|overdue`**
  - Delete: `algua/cli/governance_cmd.py`; any `algua/knowledge` code only it uses; their tests.
- **`eval gate`**
  - Delete: `algua/cli/eval_cmd.py`, `algua/research/eval_harness.py`, `tests/research/test_eval_harness.py`,
    `tests/test_cli_eval.py`.
  - Why here: an independent offline harness, not part of the binding promote path. Moving it
    here takes out 6 of the 20 slowest tests early.
- **`paper mechanics` (gated)**
  - Before deleting, stop and ask the owner. It is the deployed SSH tool `/usr/local/sbin/algua-paper`
    (`deploy/scripts/algua-paper-entry.sh`, `docs/agent/paper-mechanics-smoke.md`), approved on
    2026-11-09 for the paper smoke.
  - If removal is confirmed, delete `algua/cli/paper_mechanics_cmd.py`,
    `algua/execution/paper_mechanics*.py` (only after checking nothing else imports them),
    `deploy/scripts/algua-paper-entry.sh`, the doc and their tests. The account-lock code in
    `operator/paper_account_lock.py` stays if anything else uses it.
- **Not removed: `research log`** (`negative_cmd`). `.opencode/scripts/leap.sh` calls
  `research log list`, and `registry/negative_results.py` feeds `promote_run` and the idea
  scorecard. This departs from the spec's premise that no automation calls it.

- [ ] **Step 1: Extend the guard (failing).** Add to `REMOVED`: `"research campaign-menu"`,
  `"backtest replay"`, `"governance record"`, `"governance list"`, `"governance overdue"`,
  `"eval gate"`. Add `"paper mechanics"` only if the owner confirms. Also add a CLI test:

```python
@pytest.mark.parametrize("argv", [["research", "campaign-menu"], ["backtest", "replay"], ["governance", "list"], ["eval", "gate"]])
def test_removed_command_is_gone(argv):
    assert runner.invoke(app, [*argv, "--help"]).exit_code != 0
```

- [ ] **Step 2: Run it.** `LINUX pytest tests/test_removed_commands.py -q`. Expected: FAIL. The
  commands exist and the docs reference them.
- [ ] **Step 3: Remove each group in its own commit.** Unregister in `algua/cli/main.py`; delete
  the modules only that command used (verify with `rg -n "<module>" algua scripts`); delete their
  tests; update the docs listed. Commit message: `chore: remove <group>`.
- [ ] **Step 4: Run the checks.** The guard plus the Global Constraints checks. Expected: green,
  with no failure that wasn't already in Task 1's baseline.

---

### Task 5: Remove fundamentals and news in their current form (spec §4.3)

Branch: `chore/trim-5-context-data` from Task 4's branch.

**Files:**
- Delete:
  - `algua/cli/data_context_cmd.py`;
  - `algua/data/providers/yfinance_fundamentals.py`, `algua/data/providers/yahoo_news.py`;
  - `algua/data/fundamentals_schema.py`, `algua/data/news_schema.py`, `algua/data/hindsight.py`;
  - `algua/data/store/fundamentals.py`, `algua/data/store/news.py`;
  - `algua/research/multimodal_context.py`, `scripts/multimodal_context_exercise.py`;
  - `algua/strategies/fundamentals/`, `algua/strategies/news/`, if no other registered module is
    in them;
  - their tests.
- Modify:
  - `algua/cli/data_cmd.py`: drop `ingest-fundamentals`, `query-fundamentals`, `ingest-news`,
    `query-news`;
  - `algua/cli/main.py`;
  - `algua/data/store/__init__.py`: drop the mixins;
  - `algua/data/capabilities.py` and any provider registry entry;
  - `CLAUDE.md` and `docs/architecture.md`.
- Keep: the `Dataset`/`Kind` enum members for fundamentals and news in `algua/data/models.py`.
  Existing manifest records use them.

- [ ] **Step 1: Extend the guard and write the history test (failing).** Add to `REMOVED`:
  `"ingest-fundamentals"`, `"query-fundamentals"`, `"ingest-news"`, `"query-news"`,
  `"fetch-fundamentals"`, `"fetch-news"`. Add, in `tests/test_removed_context_data.py`:

```python
def test_manifest_with_fundamentals_record_still_lists(tmp_path):
    store = DataStore(tmp_path)
    _write_manifest_record(store, dataset=Dataset.FUNDAMENTALS)  # raw manifest write, no mixin
    assert [r.metadata.dataset for r in store.manifest.list_records(Dataset.FUNDAMENTALS)] == [Dataset.FUNDAMENTALS]
```

  Use the manifest API directly, so the test survives the mixin removal.
- [ ] **Step 2: Run it.** `LINUX pytest tests/test_removed_commands.py tests/test_removed_context_data.py -q`.
  Expected: the guard FAILS and the history test PASSES. The history test protects behaviour that
  already works, so it must stay green through Step 3.
- [ ] **Step 3: Delete and unwire.** Make the deletions and edits above. The two strategies are
  removed with their packages; Task 6's registry rule does not apply to them, because their data
  source is gone.
- [ ] **Step 4: Run the checks.** The guard, the history test, `LINUX pytest -q`, and the Global
  Constraints checks. Expected: green. `data inspect` on a store with old fundamentals records
  still lists them.
- [ ] **Step 5: Commit.** `chore: remove fundamentals/news ingestion in its current form (redesign pending)`

---

### Task 6: Prune retired strategy modules (spec §4.10)

Branch: `chore/trim-6-strategies` from Task 5's branch.

**Files:**
- Delete: strategy modules that meet every condition of spec §4.10.
- Create: `tests/test_registry_missing_module.py`

- [ ] **Step 1: Get the stages.** Run `registry list` read-only on the VPS over the existing
  deploy access, or ask the owner for its output. Save it to `.superpowers/registry-list.json`. It
  is git-ignored and never committed.
- [ ] **Step 2: Build the removal list.** Take modules whose registry stage is `retired`. Remove
  any that a frozen bundle pins (check the frozen manifests and deployment records via
  `deployment verify`/the registry), any that a test or fixture imports (`rg`), and the
  template/infrastructure modules named in §4.10. Record kept and removed modules, with the reason
  for each, in the PR body.
- [ ] **Step 3: Write the failing test.**

```python
def test_registry_show_survives_missing_strategy_module(tmp_path, monkeypatch):
    # register a strategy whose module path does not exist, then:
    assert runner.invoke(app, ["registry", "show", "ghost_strategy"]).exit_code == 0
    assert runner.invoke(app, ["registry", "list"]).exit_code == 0
```

- [ ] **Step 4: Run it.** `LINUX pytest tests/test_registry_missing_module.py -q`. If it already
  passes, keep it as a guard. If it fails, make `registry show`/`list` report the module as
  missing instead of crashing. That is the minimal fix in the registry read path.
- [ ] **Step 5: Delete the listed modules.** Run the Global Constraints checks. Expected: green.
- [ ] **Step 6: Commit.** `chore: prune retired strategy modules (source kept in git history)`

---

### After Task 6

Write the step-7 plan (statistics stack, spec §4.7–4.9) against the trimmed `main`, using
superpowers:writing-plans. It covers:
- removing the FDR ledger, family governance with `AGENT_NOVEL_MINT_CAP`, the regime, stability
  and idiosyncratic-alpha checks, and `haircut.py`;
- rewiring `effective_funnel_breadth` to `max(own lifetime, funnel windowed)`;
- keeping the measured-breadth preflight binding;
- leaving DB columns in place, so new rows write NULL.

It needs CODEOWNERS review by the owner.
