---
name: run-the-research-loop
description: The autonomous research loop playbook — work the ideas claimed from the pool for this run, author a strategy per idea, backtest/walk-forward/sweep it, gate it with research promote, and record a run report whose v2 trailer reports each idea's outcome. Use when running an autonomous research session.
---

# Running the research loop

You operate algua autonomously to take strategy ideas to **candidate**, then hand back a branch
for human review. Read `operating-algua` first for the golden rules. Delegate authoring to the
`author` subagent and results-judgement to the `interpret` subagent.

## The thesis

Read `docs/PRD.md` §§3, 8–10: search broadly for economically plausible net-of-cost edges,
preserve failed experiments and lessons, and aim for a small portfolio of deeply validated,
weakly correlated strategies. No thesis is permanently privileged. Ideation categories in
`.opencode/categories.txt` guide the search within supported data and market capabilities.
Before repeating substantially equivalent research, search the existing strategy/family notes
and experiment records and explain what changed. Report gaps in available memory; do not invent
evidence of a previous search. Complete structured experiment memory remains roadmap work.

You do not pick the belief. The driver claims ideas from the pool before your run and names them
in your goal; your job is to test them honestly and report what happened.

## Evaluation inputs

Keep the run's declared data context throughout author smoke, backtest, walk-forward, sweep and
gate. In the examples below, `<data-options>` means the exact `--snapshot <id> --start D --end D`
and required sidecar options supplied for this experiment. Use `--demo` only for an explicitly
synthetic experiment, and report it as synthetic. Never fall back to demo when real inputs are
missing. If the selected interface cannot run a required evaluation, record `run_error` with the
actual refusal; do not replace the hypothesis, strip a required model or relax a gate.

### Declared real-data pilot

`pilot_real_proxy` permits exploratory backtests, chronological walk-forward windows and sweeps
on the pinned real snapshot. Missing historical membership or as-of adjustment history does not
by itself prevent these calculations. Use `adj_close` for price signals; keep the declared
snapshot, dates, costs, configuration and seed. Use the static-universe backtest path when genuine
historical membership is unavailable; never manufacture a PIT universe from today's members.
Tell both author and interpret that this is proxy exploration before delegating.

Preserve all seven pilot limitations in the report: vendor-revisable adjusted prices, unverified
corporate actions, missing delisted symbols, unavailable event knowledge times, unavailable
historical market cap, unavailable PIT universe membership and survivorship bias. Previously
examined pilot windows are not an untouched holdout. Numerical results can test implementation
and proxy behavior; they establish neither PIT correctness nor an investable edge.

Run the empirical steps below before judging the proxy's observed behavior, unless the actual
CLI refuses or a required input is missing. Report those failures honestly; never fabricate
metrics. Qualification remains separate: a known-ineligible proxy must not reach candidate or
enqueue `merge_back`. A strict preview may record the gate's actual refusal, without relaxation
flags; otherwise record the known provenance preflight limit with `preview_gate: null`. Keep the
existing `integrity_fail` outcome for that qualification limit and assess the economic
falsification only as far as the recorded proxy evidence supports. Do not describe an unrun gate
as an executed gate or a provenance limitation as numerical refutation of the hypothesis.

## The loop (repeat for each claimed idea, then stop)

For each claimed idea:

1. **Work the claimed ideas.** Your goal names them (`idea_id`, title, hypothesis, category,
   market, horizon, `falsification`, inspirations). Do not invent a hypothesis; if an idea is
   untestable, report `outcome: run_error` with the reason. Read
   `kb/principles/research-methodology.md` before authoring (leakage vectors, search-breadth
   honesty, designing for generalization), plus `kb/strategies/_index.md` and
   `kb/strategies/_families.md` for what the relevant family already learned. Pick a unique
   strategy name; skip names already in `uv run algua registry list`.
2. **Author.** Delegate to the `author` subagent (it follows `author-a-strategy`) to scaffold once
   with `uv run algua strategy new <name> --family <slug>` (plus `--derived-from <parent>` only
   when there is an actual parent), then write `algua/strategies/<family>/<name>.py`.
   Pass the hypothesis and exact evaluation inputs. Do not create the same scaffold beforehand.
   `strategy new` already registers the scratch idea and creates the KB doc + family hub;
   then fill in the doc's `## Hypothesis` and `## Derivation` prose. Confirm it loads:
   `uv run algua backtest run <name> <data-options>`.
3. **Backtest + register.** `uv run algua backtest run <name> <data-options> --register` (advances `idea →
   backtested`).
4. **Out-of-sample evidence.** `uv run algua backtest walk-forward <name> <data-options>` (K windows +
   stability; the holdout is withheld until `research promote`). Optionally `uv run algua backtest sweep <name> <data-options> --param KEY=v1,v2,...`
   to scan parameters — but remember every combo you search raises the bar the holdout must clear
   (see `interpret-results` on search breadth).
5. **Interpret.** Delegate the results JSON to the `interpret` subagent for a promote/discard
   recommendation with reasoning, and assess the idea's own `falsification` statement against the
   walk-forward evidence -> `falsification_assessment` (`refuted` | `survived` | `untested`).
6. **Gate.** Run `uv run algua research promote <name> <data-options>` (record the combos you searched with
   `--n-combos K`). The gate advances `backtested → candidate` **only on pass**; on a fail it
   reports why and leaves the stage unchanged. Trust the gate — do not lower thresholds to force a pass.
7. **Record.** Sync the synced fact blocks: `uv run algua strategy doc <name>`. Then write
   the doc's `## Verdict & next` (what was learned + the next idea as a `[[dangling-link]]`),
   set `hypothesis_status`, and update the family doc's `## State of exploration` and
   `status`. Finally append the hypothesis, params, key metrics, the gate decision, and your
   candidate/discard rationale to your run report (see "Finishing a run" below). For a strategy
   worth a deeper write-up, the `report-experiments` skill turns its tracked sweep/walk-forward
   runs into a plotted, provenance-stamped report in the vault.

## Stopping

Work exactly the **claimed ideas** in your goal (at most N), then stop. If you are running low on
time, stop early — but always finish by writing the report, and give every claimed idea you never
got to its own trailer entry with `outcome: run_error`. An idea missing from the trailer is
recorded as `run_error` / `missing_from_trailer` anyway; saying why yourself is strictly better.

## Boundaries

- Operate **only** through `uv run algua ...`. Never go past `candidate` in an autonomous research
  session — do not attempt `registry transition --to paper/forward_tested/live` or `registry
  approve`; advancing to paper or beyond is outside the research loop scope.
- Never edit the human-owned safety/integrity files (see `operating-algua`).
- Author only **new** files under `algua/strategies/<family>/` via `strategy new --family <slug>`.

## Finishing a run

1. Ensure every authored strategy file is committed on the current `research-run/<stamp>` branch.
2. Write your report to `kb/research-runs/<stamp>.md` (create the directory if it doesn't exist):
   one section per hypothesis (name, params, backtest + walk-forward + gate results, decision +
   why), then a summary of what you promoted to candidate.
3. The report MUST end with a machine-readable trailer — one fenced ```json block with **exactly
   one `hypotheses[]` entry per claimed idea** (trailer **v2**):
   - `idea_id` — the claimed idea's id. Required; an entry without it teaches the pool nothing.
   - `title` — <= 120 chars, plain ASCII.
   - `outcome` — what actually happened, written straight into the authoritative idea ledger:
     `integrity_fail` (preflight/integrity refused it) | `holdout_negative` (holdout Sharpe <= 0) |
     `walkforward_refuted` (out-of-sample windows refute it) | `sweep_unstable` (only isolated
     combos work) | `candidate_preview_pass` (the preview gate passed) | `run_error` (you could not
     test it). Be honest — this is the record the funnel learns from.
   - `reason` — <= 300 chars, why that outcome.
   - `falsification_assessment` — `refuted` | `survived` | `untested`, judging the idea's own
     falsification statement against your walk-forward evidence.
   - `verdict` — `"discarded"|"candidate-preview-pass"|"error"` (kept for the digest readers).
   - `merge_back` — ONLY when `verdict` is `"candidate-preview-pass"`: `idea_id`, `strategy`,
     `universe`, `start`, `end`, `eval_context`, naming the exact strategy module you authored and
     its promote window.

   The launcher parses this into the durable run digest, writes one `record-outcome` per claimed
   idea, and for every valid `merge_back` enqueues the REAL, authoritative `paper merge-back` for
   the automated drainer to run — the merge-back you'd otherwise hand a human is now automatic; do
   not run it yourself.
4. Commit the report (the launcher does this for you). Review the branch afterward with
   `git diff main...<branch>` if you want to double-check what shipped.
