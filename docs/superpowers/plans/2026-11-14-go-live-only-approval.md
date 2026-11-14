# Go-live-only approval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the signed `--actor human` gate-override path and every relaxation it unlocks, so the signed go-live is the only approval and gates are fixed at today's agent values for every actor.

**Architecture:** Delete `algua/registry/human_actor.py` and its call sites. On `research promote` delete the human-only flags and make the agent-only preflight checks unconditional. On `paper promote` keep the threshold flags as tighten-only for every actor. Remove the `human-actor` enrolment namespace. No schema change.

**Tech Stack:** Python 3.12, typer, SQLite, pytest (Linux Docker only; macOS cannot import `algua.cli`).

**Spec:** `docs/superpowers/specs/2026-11-13-go-live-only-approval-design.md`

## Global Constraints

- Nothing becomes weaker for an agent. A flag is removed, never opened to agents.
- The go-live wall (`registry transition --to live`, namespace `algua-go-live`, forward certificate) is unchanged.
- No migration: `actor_challenges` table and all columns stay; nothing new writes to `actor_challenges`.
- `--actor human|agent` stays on both promote commands as an audit label that unlocks nothing.
- Operational human actions (`paper kill`, `paper resume`, `--disable-drawdown-breaker`) are untouched.
- Builder ruling (spec §6): the seven `paper promote` threshold flags stay, tighten-only for every actor.
- Size-ratchet pins only go down; an import-linter contract whose subject is deleted is removed with the reason in the commit.
- Repo is public; no vendor data in fixtures. Do not push.
- Test command (Linux Docker):
  `docker run --rm -v "$PWD":/w -v algua-linux-venv:/venv -v /Users/liornisimov/Projects/algua/.git:/Users/liornisimov/Projects/algua/.git -w /w -e UV_PROJECT_ENVIRONMENT=/venv -e UV_LINK_MODE=copy ghcr.io/astral-sh/uv:python3.12-bookworm uv run --frozen <cmd>`
  Never touch containers or volumes with "drive" in the name.

## Review Focus

1. Passing a removed flag (`--actor-signature`, `--n-combos`, `--allow-holdout-reuse`, `--allow-non-pit`, `--assume-terminal-last-close`, `--new-family`) must fail as an unknown option (exit 2), never be silently ignored.
2. `--actor human` on `research promote` must hit every preflight an agent hits (non-reproducible snapshot, missing `feature_lookback`, universe check, measured breadth).
3. `paper promote --actor human` with a loosened threshold must be refused exactly like an agent.
4. Go-live still works end to end: `enroll-approver --namespace go-live`, challenge, signature, transition.
5. No automation (`scripts/`, `deploy/`, `.opencode/`, `.claude/skills/`, `algua/operator/`) passes a removed flag.

---

### Task 1: research promote — remove the human override path

**Files:**
- Modify: `algua/cli/research_cmd.py`, `algua/registry/promote_run.py`, `algua/registry/promotion.py`, `algua/registry/family_assignment.py`, `algua/backtest/delisting.py` / `algua/backtest/engine.py` (only the human-only `assume_terminal_last_close` plumbing reachable from promote; the backtest command's own option may stay if it is not a gate)
- Test: `tests/test_removed_gate_overrides.py` (new), existing tests that exercised the human path (update or delete)

- [ ] **Step 1: Write the failing guard test** `tests/test_removed_gate_overrides.py`:
  - `test_research_promote_refuses_removed_flag[flag]` parametrized over `--actor-signature x.sig`, `--n-combos 3`, `--allow-holdout-reuse`, `--allow-non-pit`, `--assume-terminal-last-close`, `--new-family fam`: `CliRunner().invoke(app, ["research", "promote", "s", "--universe", "u", "--start", "2020-01-01", "--end", "2021-01-01", *flag])` has `exit_code == 2` and "No such option" in the output.
  - `test_human_actor_gets_agent_preflight`: a human-labelled promote on a strategy with no recorded sweep breadth is refused with the same error class/message as an agent (reuse an existing promotion-preflight fixture).
- [ ] **Step 2: Run it; expect FAIL** (flags still exist; human bypasses breadth).
- [ ] **Step 3: Remove** the options and the `authenticate_actor` call; make `guard_agent_relaxations` and every `actor is Actor.AGENT and …` preflight in `promotion.py` unconditional (delete the relaxation parameters it guarded); remove the human NOVEL fresh-family branch so humans follow the agent deferred-mint path.
- [ ] **Step 4: Run the guard + `tests/test_promotion.py tests/test_cli_research*.py tests/test_family_registry.py`; expect PASS** after updating tests that asserted the human path (delete tests whose only subject was a human relaxation).
- [ ] **Step 5: Commit** `chore: research promote has no human override path`.

### Task 2: paper promote and the rest of the signed path

**Files:**
- Modify: `algua/cli/paper_cmd.py`, `algua/research/forward_gates.py`, `algua/cli/paper_experimental.py`, `algua/cli/registry_cmd.py`, `algua/registry/transitions.py`
- Delete: `algua/registry/human_actor.py` (and `challenges.py` only if go-live no longer uses it — it does, so keep)
- Test: `tests/test_removed_gate_overrides.py`

- [ ] **Step 1: Add failing tests:**
  - `test_paper_promote_refuses_actor_signature`: exit 2, "No such option".
  - `test_paper_promote_human_cannot_loosen[flag]` over the seven threshold flags with a loosened value: refused for `--actor human` with the same error as for an agent.
  - `test_enroll_approver_rejects_human_actor_namespace[ns]` for `human-actor` and `both`: non-zero exit; `go-live` still accepted.
  - `test_qualify_experimental_refuses_actor_signature`: exit 2.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Remove** `--actor-signature` from `paper promote` and `qualify-experimental`; make the forward-gate relaxation guard refuse loosening for every actor; drop the `human-actor`/`both` namespaces from `enroll-approver`; delete `human_actor.py`. In `transitions.py`, confirm the human exemptions on `backtested -> candidate` and `paper -> forward_tested` are unreachable behind `raw_edge.refuse_raw_edge` (trace every caller of `transition_strategy`); if unreachable, remove them so both edges always require the gate token. Ledger the trace.
- [ ] **Step 4: Run the new tests + `tests/test_cli_paper.py tests/test_forward_certificate.py tests/test_registry_approvals.py tests/test_paper_exit_golive.py tests/test_cli_registry.py` and every test file that imported `human_actor`; expect PASS.**
- [ ] **Step 5: Commit** `chore: go-live is the only signed approval`.

### Task 3: docs, automation and structure

**Files:** `CLAUDE.md`, `AGENTS.md`, `docs/architecture.md`, `docs/agent/*`, `.opencode/skills/*`, `.opencode/agents/*`, `CODEOWNERS`, `pyproject.toml` (import-linter), `tests/test_module_size_ratchet.py`

- [ ] **Step 1:** grep for `actor-signature`, `human-actor`, `--n-combos`, `--allow-non-pit`, `--allow-holdout-reuse`, `--assume-terminal-last-close`, `--new-family`, `#329` across docs, skills, scripts, deploy. Rewrite each to the new truth: one signed approval (go-live); gates fixed for everyone; agents may tighten paper thresholds. `docs/agent/research-lifecycle.md` stops telling anyone to pass `--n-combos`.
- [ ] **Step 2:** remove CODEOWNERS / import-linter entries for `human_actor.py`; lower size-ratchet pins for shrunken files.
- [ ] **Step 3: Verify:** `ruff check .`, `mypy algua`, `lint-imports`, `tests/test_docs_links.py tests/test_module_size_ratchet.py tests/test_removed_gate_overrides.py`, then ONE default `pytest -q`: no failing node IDs beyond the stack's known set (main already fails `tests/test_campaign_choice_producer.py::test_large_context_trims_only_optional_history_before_claiming`).
- [ ] **Step 4: Commit** `docs: describe go-live as the only approval`.
