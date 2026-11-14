# Statistics stack trim (lean trim step 7) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the advisory statistics machinery: the FDR ledger remains, family governance, the regime, window-stability and idiosyncratic-alpha checks, and the haircut. Keep deflated Sharpe (DSR) and the bootstrap as the one advisory quality signal, and rewire DSR's trial count to `max(own lifetime combos, funnel-wide windowed combos)`.

**Architecture:** Each subsystem is removed in its own revertable commit. Gate rows keep their schema: removed columns are written NULL or left at their default, and nothing is migrated destructively. Historical `decision_json` keys stay readable. `evaluate_gate`'s `passed` keeps the exact binding set it has today.

**Tech Stack:** Python 3.12, SQLite, typer, pytest (Linux Docker only).

**Spec:** `docs/superpowers/specs/2026-11-12-lean-codebase-trim-design.md` §4.7–4.9 (owner-approved 2026-11-12; §4.9 mint-cap removal explicitly approved).

## Binding inventory (what this plan proves it does not loosen)

`evaluate_gate` (`algua/research/gates.py`) sets `passed = all(c["passed"] for c in checks if not c.get("advisory"))`. The non-advisory checks are:

| Check | Binding | This plan |
|---|---|---|
| `min_holdout_observations` (63) | yes | unchanged |
| `holdout_sharpe_floor` (raw holdout Sharpe > 0) | yes | unchanged |
| `pit_required` | yes | unchanged |
| `holdout_sharpe` (bar deflated by the haircut) | advisory | stays advisory; threshold becomes the base `min_holdout_sharpe` (Task 4) |
| `holdout_return` | advisory | unchanged |
| `pct_positive_windows`, `min_window_sharpe` (window stability) | advisory | removed (Task 3) |
| `dsr_evidence`, bootstrap | advisory | kept; trial count rewired (Task 2) |
| regime robustness, `idiosyncratic_alpha` | advisory | removed (Task 3) |

Preflight raises in `registry/promotion.py` stay binding: reproducible source, cost floor, `feature_lookback`, signal-panel parity, universe subset (#559), measured breadth via `backtest sweep`, and delisting handling. The only binding controls removed are family-governance refusals: the `AGENT_NOVEL_MINT_CAP` rate cap and the `FamilyGraphDrift` CAS. The owner approved removing them in spec §4.9. The FDR throttle has not been consulted since stage 4a. `research/fdr_lord.py` is already gone, and rows already write `fdr_binding` NULL. The eval harness went in trim step 4.

`forward_evidence.qualified_holdout_sharpe` reads only the `holdout_sharpe` check's **value** (raw holdout Sharpe), never its threshold. So changing that check's threshold leaves the forward bar unchanged.

## Global Constraints

- Never change the binding set above, the 63-observation constant (`research/_constants.py`; only its comment may change), or the go-live wall.
- No destructive migration. Tables and columns written by removed code stay in place, and new rows write NULL. The schema version is not bumped unless a column default must change; if it must, the change is additive only.
- Historical rows stay readable: every reader of `gate_evaluations.decision_json`, the `fdr_*` columns and the family tables must accept both an old-shape row (all keys present) and a new-shape row (keys absent or NULL).
- Keep byte-identical: `operator/journal.py::_STRICT_RELAXATION_CANONICAL` and every attempt-token pre-image string.
- **Two concepts share names and must not be confused.** Strategy *families* (#222/#524: `registry/family_assignment.py`, `registry/store/family.py`, `research/clustering.py`) are removed. Research *campaign/idea families* (`research/campaign_*`, idea pool, research memory) stay. *Regime robustness* (`research/regime.py`) is removed. *Regime features and overlays* (`features/regime.py`, `regime_gate` overlay policy, `momentum_regime_stop`) stay. Walk-forward `wf.stability` metrics stay, because sweep ranking and tracking use them; only the gate checks on them go.
- Removed CLI flags fail as unknown options (exit 2); add them to `tests/test_removed_gate_overrides.py`.
- Import-linter: a contract whose subject is deleted is removed, with the reason in the commit. Size-ratchet pins only go down.
- Repo is public; fixtures are synthetic. Do not push.
- Test command (Linux Docker; the extra `.venv` mount is required, because gate-comparison fixtures exec `/w/.venv/bin/algua`):
  `docker run --rm -v "$PWD":/w -v algua-linux-venv:/venv -v algua-linux-venv:/w/.venv -v /Users/liornisimov/Projects/algua/.git:/Users/liornisimov/Projects/algua/.git -w /w -e UV_PROJECT_ENVIRONMENT=/venv -e UV_LINK_MODE=copy ghcr.io/astral-sh/uv:python3.12-bookworm uv run --frozen <cmd>`
  Never touch containers or volumes with "drive" in the name.
- Verification is proportional: focused files per task, then ONE default `pytest -q` at the end. Compare against a fresh baseline taken at the plan's BASE with the same mount. The `.venv` mount turns most `test_gate_owned_comparison` errors green, so the old known-failures list is too loose.

## Review Focus

1. A historical gate row (with `fdr_*`, family, regime, IR and haircut keys) must still render through `registry show`, `gate_history`, run views and `--summary` without KeyError.
2. A promote run on a fresh registry with no families must pass or fail exactly as before on the binding set. This is the ordinary path once family assignment is gone.
3. The DSR trial count must include sweeps from strategies whose gate failed and from human-labelled runs (`search_trials` has no `passed` or `actor` filter; keep it that way).
4. A merge-back attempt already in flight before the upgrade must re-derive the same attempt token.
5. No skill, agent prompt or doc tells an agent to read a removed field or pass a removed flag.

---

### Task 0: fresh baseline

- [ ] **Step 1:** at BASE, run the default `pytest -q` with the test command above. Save the sorted failing node IDs to the SDD workspace as `baseline.txt`. Record the counts in the ledger. No commit.

### Task 1: FDR ledger remains

**Files:** `algua/registry/store/gate.py`, `algua/registry/repository.py`, `algua/registry/db/gate.py`, `algua/registry/db/migrate.py` (read paths only), `algua/registry/gate_history.py`, `algua/research/gate_serialization.py`, `algua/registry/store/runs.py`, `algua/registry/store/base.py`, `algua/contracts/types.py`, `algua/cli/research_cmd.py`, `algua/cli/research_batch_cmd.py`; tests listed by `grep -rli fdr tests`.

- [ ] **Step 1: Failing test** `tests/registry/test_stats_trim_history.py::test_old_and_new_gate_rows_render`. It inserts one synthetic old-shape `gate_evaluations` row (real `fdr_*` values, plus the family/regime/IR/haircut keys in `decision_json`) and one new-shape row (those NULL or absent). It then asserts that `strategy_gate_history`, `gate_evaluation_history` and the runs view return both rows without error, and that the old row's FDR values still show. This test grows in Tasks 2–4. Run it: it should pass for the old row, and the new-row assertions should fail where readers assume keys.
- [ ] **Step 2:**
  - Rename `record_gate_with_fdr_and_maybe_promote` to `record_gate_and_maybe_promote`.
  - Delete `fdr_stream_state`, `FdrStreamState` and the `fdr_*` result fields.
  - The insert omits the `fdr_*` columns (or writes NULL).
  - Readers treat `fdr_*` as optional historical fields.
- [ ] **Step 3:** run Step 1's test plus `tests/test_promotion.py tests/test_research_gates.py tests/test_registry_store.py tests/test_registry_db.py tests/test_concurrency.py tests/registry/test_run_views.py tests/test_cli_registry_gates.py`. Expect PASS once tests that asserted the removed fields are updated or deleted, with the reason given in the commit body.
- [ ] **Step 4: Commit** `chore(stats): remove the frozen FDR ledger code (columns stay, historical rows readable)`.

### Task 2: family governance, and the breadth rewire

**Files:**
- Delete: `algua/registry/family_assignment.py`, `algua/research/clustering.py`, `algua/registry/lineage.py` (if only family code uses it).
- Modify:
  - `algua/registry/store/family.py`: delete it if no remaining reader needs it. Otherwise keep only what historical reads use.
  - `algua/registry/db/family.py`: the schema stays.
  - Also `algua/registry/store/gate.py`, `algua/registry/promotion.py`, `algua/registry/promote_run.py`, `algua/registry/repository.py`, `algua/research/dsr.py`, `algua/registry/mergeback_intake.py`, `pyproject.toml`, `CODEOWNERS`.
- Tests: strategy-family tests only (see the name-collision constraint).

- [ ] **Step 1: Failing tests:**
  - `tests/research/test_effective_breadth.py::test_breadth_is_max_of_own_and_windowed`: `effective_funnel_breadth(5, 12) == 12`, `effective_funnel_breadth(9, 3) == 9`, and the function takes exactly two parameters (`inspect.signature`).
  - `test_windowed_breadth_counts_failed_and_human_runs`: record `search_trials` for strategy A, whose gate failed, and for strategy B, whose runs are human-labelled. `windowed_search_combos(window)` includes both. `research promote` on strategy C passes that total as DSR `n_trials` (read `decision_json["dsr_n_trials"]`).
  - `test_promote_on_empty_registry_has_no_family_step`: a promote that passes the binding set on a registry with zero families commits `candidate`, and writes no `strategy_families` and no `family_events` rows.
  - Extend `test_old_and_new_gate_rows_render` with old rows from the family tables.
- [ ] **Step 2:** run. Expect FAIL.
- [ ] **Step 3:**
  - Remove classification from the preflight, along with `BreadthContext.family_id`, `expected_family_id`, `pending_novel_family`, `_revalidate_pending_novel`, the `FamilyGraphDrift` checks, the pending mint in the store transaction, `AGENT_NOVEL_MINT_CAP`, parent edges and lifetime priors.
  - `effective_funnel_breadth(own_lifetime, windowed_total)` returns their `max`, and `promote_run` passes that as `n_combos`.
  - Keep the measured-breadth preflight raise and `search_trials` recording unchanged.
  - Drop the import-linter contracts and CODEOWNERS lines whose subject is deleted.
- [ ] **Step 4:** run Step 1's tests plus `tests/test_promotion.py tests/test_family_registry.py tests/registry/ tests/test_cli_research*.py tests/test_cli_merge_back.py tests/test_concurrency.py tests/test_removed_gate_overrides.py`. Expect PASS. Delete tests whose only subject was strategy-family governance, listing them in the commit body.
- [ ] **Step 5: Commit** `chore(stats): remove strategy-family governance; DSR breadth is max(own lifetime, funnel windowed)`.

### Task 3: regime robustness, window stability and idiosyncratic alpha

**Files:** `algua/research/regime.py` (delete the robustness check and `information_ratio`; delete the file if nothing else remains), `algua/research/gates.py`, `algua/registry/promote_run.py` (`market_returns` plumbing), `algua/cli/research_cmd.py` (`--min-pct-positive`, `--min-window-sharpe`), `algua/research/gate_serialization.py`, `algua/registry/gate_history.py`; tests `tests/research/test_regime_robustness.py`, `tests/research/test_information_ratio.py` and the gate tests that assert these checks.

- [ ] **Step 1: Failing tests:**
  - `test_gate_checks_are_exactly` asserts that `[c["name"] for c in evaluate_gate(...).checks]` equals `["holdout_sharpe", "holdout_return", "min_holdout_observations", "holdout_sharpe_floor", "pit_required"]`, plus `dsr_evidence` and the bootstrap when armed.
  - `--min-pct-positive` and `--min-window-sharpe` exit 2.
  - Extend the history test with old regime/IR keys.
- [ ] **Step 2:** run. Expect FAIL.
- [ ] **Step 3:**
  - Remove the two `GateSpec`s, the regime and IR blocks, and their `GateDecision` fields.
  - Remove `GateCriteria.min_pct_positive_windows` and `min_window_sharpe`, and their CLI flags.
  - Keep `wf.stability` in walk-forward results.
- [ ] **Step 4:** run Step 1's tests plus `tests/test_research_gates.py tests/test_promotion.py tests/test_cli_research*.py tests/test_walkforward.py tests/test_sweep_ranking.py tests/test_features_regime.py tests/test_portfolio_overlays.py`. Expect PASS.
- [ ] **Step 5: Commit** `chore(stats): remove regime-robustness, window-stability and idiosyncratic-alpha checks`.

### Task 4: haircut and the dominance audit

**Files:** delete `algua/research/haircut.py`; modify `algua/research/gates.py`, `algua/research/gate_serialization.py`, `algua/registry/gate_history.py`, `algua/research/_constants.py` (comment only), `pyproject.toml` (the import-linter edge list at about line 415); delete `tests/research/test_dominance_predeclaration.py`.

- [ ] **Step 1: Failing tests:**
  - `test_holdout_sharpe_threshold_is_base_bar`: with `n_combos=50`, the advisory `holdout_sharpe` check's threshold equals `criteria.min_holdout_sharpe`, and its value equals the raw holdout Sharpe.
  - `test_forward_bar_reads_value_not_threshold`: `qualified_holdout_sharpe` returns the same number for an old row (deflated threshold) and a new row with the same value.
  - Extend the history test with `haircut_would_have_blocked`, `phase3_component_mask` and `effective_min_holdout_sharpe` in old rows.
- [ ] **Step 2:** run. Expect FAIL.
- [ ] **Step 3:**
  - Remove the haircut, `effective_min_holdout_sharpe`, `haircut_would_have_blocked`, `PHASE3_COMPONENT_MASK` and the `DOMINANCE_AUDIT_*` constants.
  - The non-finite-threshold fail-closed branch goes with them: the base bar is always finite. A zero-length holdout is still refused by `min_holdout_observations`.
- [ ] **Step 4:** run Step 1's tests plus `tests/test_research_gates.py tests/test_promotion.py tests/test_forward_promotion.py tests/test_cli_sweep.py tests/test_cli_registry_gates.py`. Expect PASS.
- [ ] **Step 5: Commit** `chore(stats): remove the breadth haircut; DSR is the trial-aware signal`.

### Task 5: docs, skills and final verification

**Files:** `CLAUDE.md` (the research-promote bullet: drop the family-governance paragraph, the FDR paragraph and the statistics list; state the kept signal), `AGENTS.md`, `docs/architecture.md`, `docs/vision-reconciliation.md`, `docs/agent/*`, `.opencode/skills/interpret-results/SKILL.md`, `.opencode/skills/run-the-research-loop/SKILL.md`, `.opencode/agents/*`, `tests/test_module_size_ratchet.py`.

- [ ] **Step 1:** grep docs, skills, agents and scripts for `fdr`, `LORD`, `family governance`, `AGENT_NOVEL_MINT_CAP`, `--new-family`, `regime_robust`, `idiosyncratic`, `window stability`, `haircut`, `effective_min_holdout`, `--min-pct-positive` and `--min-window-sharpe`. Rewrite each hit to the new truth:
  - one advisory, trial-aware signal: DSR plus bootstrap, with trials counted as `max(own lifetime, funnel windowed)`;
  - the binding floor unchanged;
  - making DSR binding is an owner decision.
- [ ] **Step 2:** lower size-ratchet pins for shrunken files, and remove pins for deleted files.
- [ ] **Step 3: Verify:** `ruff check .`, `mypy algua`, `lint-imports`, `tests/test_docs_links.py tests/test_module_size_ratchet.py`, then ONE default `pytest -q`. Expect no failing node ID outside `baseline.txt`.
- [ ] **Step 4: Commit** `docs(stats): describe DSR as the one advisory quality signal`.
