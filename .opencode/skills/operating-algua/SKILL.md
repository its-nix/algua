---
name: operating-algua
description: Orientation for operating the algua algotrading platform — the golden rules, the CLI/JSON seam, the strategy lifecycle, and where to look. Read this first when running or operating algua.
---

# Operating algua

algua is an **agent-first** algotrading research platform. You operate it the same way the human
operator does: through one CLI, `uv run algua ...`, where **every data command emits JSON on
stdout**. You drive research; the system enforces the safety boundary.

## Golden rules (non-negotiable)

1. **Drive everything through `uv run algua ...`.** Never import or call algua modules directly to
   bypass the CLI. The CLI is the contract.
2. **Isolated research workers stop at `candidate`.** Operational commands outside that worker
   role may advance through `forward_tested` under the existing gates. You may **never** put a
   strategy `live`. The `forward_tested → live` transition requires a verified
   human approval, a human actor, AND a fresh forward-test certificate; the system enforces this
   and you must not attempt to route around it.
3. **Do not weaken safety or integrity code.** Research workers never edit any file protected by
   root `CODEOWNERS`, including registry, lifecycle, backtest engine, gates and portfolio policies.
   Changing those files is out of scope for a research run.
4. **Validate proportionally** under `docs/agent/story-delivery.md`: use focused regression or
   smoke checks for the behavior changed and report what actually ran. Full validation is for
   broad integration changes or an explicit request, not every small addition. Existing enforced
   promotion and merge-back gates remain binding.

## The lifecycle

```
idea → backtested → candidate → paper → forward_tested → live → retired
```
(plus allowed back-steps and `→ retired`). Research workers stop at `candidate`; operational
commands may reach `forward_tested` under their gates. Stage lives in the SQLite registry —
`uv run algua registry show <name>` reports it.

## Command surface (the ones you use most)

- `uv run algua doctor` — environment readiness (non-zero exit = a failed check).
- `uv run algua registry list [--stage S]` / `registry show <name>` — inspect strategies + history.
- `uv run algua backtest run <name> --demo --register` — backtest + register + advance to `backtested`.
- `uv run algua backtest walk-forward <name> --demo` — K windows + stability (out-of-sample evidence); the holdout is withheld until `research promote`.
- `uv run algua backtest sweep <name> --demo --param KEY=v1,v2` — bounded parameter grid, ranked.
- `uv run algua research promote <name> --snapshot <id> --universe <pit-universe> --start D --end D`
  — gate `backtested → candidate`; requires measured sweep breadth and a fresh holdout, and
  promotes only on pass. Breadth is measured from sweeps; declarations are unsupported.
- `uv run algua paper promote <name>` — gate `paper → forward_tested`; requires ≥63 broker-clocked daily return observations, ≥90% coverage, realized Sharpe ≥ max(0.5×holdout, 0.3), vol/DD bounds, clean integrity + hygiene, evidence ≤5 sessions stale. Threshold flags may only tighten, for every actor.
- `uv run algua data inspect --summary` — what data snapshots exist.

Pass `--summary` to `backtest walk-forward`, `backtest sweep`, and `research promote` to emit
ONLY the decision-relevant scalars (drops the per-window/per-combo lists and the deep gate
diagnostics; the payload is stamped `"summary": true`). Prefer it for unattended operation so
verbose tool output doesn't rot your context (#349); omit it when you need the full detail.

`--demo` uses the synthetic data provider for explicit offline smoke tests, not economic evidence.
Research uses the assigned real `--snapshot <id>`, dates, universe and sidecars. Snapshot existence
does not prove PIT eligibility; report missing inputs or a refused gate rather than inventing them.

## Where to look

- **The research loop you run:** the `run-the-research-loop` skill.
- **Writing a strategy:** the `author-a-strategy` skill.
- **Reading results / deciding promote-or-discard:** the `interpret-results` skill.
- **The canonical command walkthrough:** `docs/agent/research-lifecycle.md`.
- **Product vision of record:** `docs/PRD.md`.
- **Current implementation and rules:** `docs/architecture.md`, `CLAUDE.md` and
  `docs/agent/operating.md`; `docs/vision-reconciliation.md` preserves the dated September gap assessment.
- **Historical architecture rationale:** `docs/superpowers/specs/2026-05-29-algua-platform-architecture-design.md`;
  its original lifecycle, authentication and roadmap are not current operating instructions.
- **The data contract crossing data↔research:** `docs/contracts/bar-schema.md`.

## How you're run

You typically run autonomously inside an isolated git worktree on a `research-run/<stamp>` branch.
Write your authored files and a report at `kb/research-runs/<stamp>.md` in that worktree. The
trusted launcher commits both afterward; the worker does not run `git commit`. For any
hypothesis whose preview passed, name its `merge_back` in the report's trailer (see
`run-the-research-loop`) — the launcher parses it and enqueues the REAL, authoritative
`paper merge-back` for the automated drainer to run; you never run it yourself. Operate freely
within the worktree — it's contained and reviewable.
