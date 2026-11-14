# Go-live is the only approval

Date: 2026-11-13. Status: approved by the owner 2026-11-14 ("i approve the removal of the gate override signatures").
Follows the lean codebase trim (`2026-11-12-lean-codebase-trim-design.md`) and lands as its own branch.

## 1. Intent

The owner wants one human approval in the whole system: the signed `forward_tested -> live`
go-live. Today a second signed path exists. `--actor human --actor-signature <sig>` (#329) on
`research promote` and `paper promote` lets a human loosen a gate for one run. Nobody uses it, and
it carries a challenge table, a signing namespace, an enrolment mode and about 60 test files.

Removing it must not loosen anything. So the relaxations go with the signature: the gates become
fixed for everyone, at today's agent values.

## 2. Goals, non-goals, anti-goals

**Goals**
- The go-live signature is the only signed approval left.
- Every gate check that an authenticated human could skip or relax today now applies to every run.
- Less code: `algua/registry/human_actor.py` and its wiring, tests and docs are gone.

**Non-goals**
- Changing the go-live wall: challenge, `algua-go-live` namespace, fresh forward certificate.
- Operational human actions that are not approvals, which stay as they are: `paper kill`,
  `paper resume`, `--disable-drawdown-breaker`. They write `actor="human"` audit rows and need no
  signature today.
- The statistics stack (trim step 7). It is touched only where a human-only flag lives in it.

**Anti-goals**
- Any check that becomes weaker for an agent. A flag is removed, never opened to agents.
- Destroying history. The `actor_challenges` table and past rows stay; nothing writes to them.

## 3. What is removed

On `research promote`:
- `--actor-signature`, and the authentication call in `registry/promote_run.py`.
- The human-only flags: `--n-combos`, `--allow-holdout-reuse`, `--allow-non-pit`,
  `--assume-terminal-last-close`, `--new-family`.
- The human exemptions in the preflight (`registry/promotion.py`): a non-reproducible snapshot, a
  missing `feature_lookback`, and the universe check. They now apply to every actor.

On `paper promote`:
- `--actor-signature`.
- Loosening any threshold below its default. That covers `--degradation-factor`, `--sharpe-floor`,
  `--min-observations`, `--min-coverage`, `--min-vol`, `--max-drawdown` and `--max-staleness`.
  Each flag may stay as tighten-only, which agents may already do. The builder chooses: keep it
  tighten-only, or delete it if nothing passes it.

Elsewhere:
- `registry enroll-approver --namespace human-actor|both`. Only `go-live` remains. A key already
  enrolled for `algua-human-actor` in `approvers/allowed_signers` is harmless and can stay.
- `paper qualify-experimental --actor-signature`, which is already ignored.
- The human exemption in `registry/transitions.py` for `backtested -> candidate` and
  `paper -> forward_tested`. The builder confirms it is unreachable behind `raw_edge.py`, which
  refuses both edges for every actor, and removes it.

`--actor human|agent` stays on the promote commands as an audit label that unlocks nothing.

## 4. Consequences the owner accepts

- **No non-PIT promotes.** Until PIT data exists (the Sharadar pipeline), nothing reaches
  `candidate`, for anyone. That is already true for agents.
- **A burned holdout stays burned.** To promote a strategy again, a run must use a new holdout
  window.
- **Breadth must be measured.** A strategy needs `backtest sweep` records, because breadth can no
  longer be declared by hand.
- **No exceptions without a code change.** Getting one means a reviewed change, not a signature.

## 5. Constraints

- CODEOWNERS: most of these files are protected. The owner reviews the branch.
- Registry DB: no migration. The tables and columns stay in place.
- The size ratchet pins only shrink. Import-linter contracts whose subject disappears are deleted,
  with the reason given in the commit.
- `CLAUDE.md`, `docs/architecture.md`, `AGENTS.md`, `docs/agent/*` and `.opencode/skills/*` stop
  describing the human-actor path. `docs/agent/research-lifecycle.md` stops telling anyone to pass
  `--n-combos`.
- A guard test proves that each removed flag is refused by the CLI, as an unknown option.

## 6. Left to the builder

- The exact list of modules and tests, found by tracing from `human_actor.py`.
- Whether to keep each paper-promote threshold flag as tighten-only or delete it.
- The order: after the trim branches, before or folded into trim step 7. `--new-family` and the
  family exemptions overlap with step 7.
