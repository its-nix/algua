# Lean codebase trim

Date: 2026-11-12. Base: `main` at `e144fc9`. Status: agreed with the owner in conversation; not yet
implemented. Removes code; changes no binding gate, threshold, lifecycle edge, capital or live
permission (§4.7 names the one place a binding gate could be tightened later, as a separate decision).

## 1. Intent

The codebase has grown faster than its use. Measured at `cfc7b48`:
- 68k lines of product code in 503 modules;
- 120k lines of tests (about 9,250 tests, 1.8× the code);
- 126k lines of docs, of which 105k are historical superpowers plans and specs;
- a 19.6k-line web app;
- 116 CLI commands, of which automation (timers, agent scripts, skills) calls about 25.

The last recorded full CI run (4 Nov, 8,269 tests) took 44 minutes, single-process.

Nothing is orphaned: every non-strategy module is imported somewhere. The weight is whole features
that are not on the path to the owner's goal (autonomous profit from validated strategies), and
safety machinery that was frozen or made advisory but kept running.

The owner wants a focused codebase and a fast check loop. Keep the walls that make results
trustworthy; remove what does not serve them.

## 2. Goals, non-goals, anti-goals

**Goals**
- The default local/CI test run finishes in minutes; the full run stays available on demand.
- Remove the features listed in §4.1–4.3 with their tests, docs and wiring.
- Replace the frozen/advisory statistics stack with one small, honest quality signal
  (§4.7) that uses a plain trial count.
- Docs describe the current qualification routes correctly (§4.14).

**Non-goals**
- The new dashboard. The current web app is removed; its replacement is a separate design.
- Composable fundamentals/news inputs. The current form is removed; the redesign under the strategy
  contract is a separate design.
- The PIT data pipeline (separate spec, `docs/superpowers/specs/2026-11-12-pit-data-pipeline-design.md`).
- Rewriting code that stays, beyond what removal forces.

**Anti-goals (failure even if it "works")**
- Loosening any binding check. That includes the PIT requirement, the 63-observation floor, the
  holdout Sharpe > 0 floor, the single-use holdout, integrity preflights, the live wall, lane
  parity, risk and kill switches.
- Destroying registry history. Existing gate rows, families and transition records stay readable.
- One giant removal commit that cannot be reviewed or reverted piecewise.
- Deleting tests that guard code that stays.

## 3. Constraints

- **CODEOWNERS:** files listed there need human review. The owner reviews those removals.
- **Registry DB:** the registry is a migrated SQLite schema with live data on the VPS. Removing
  columns or tables is a migration. Prefer leaving columns in place (written NULL or a fixed value)
  over destructive migrations.
- **Layering:** import-linter has 31 contracts. Removing a module may orphan a contract. A contract
  whose subject is gone is deleted with it, with the reason in the commit.
- **Size ratchet:** `tests/test_module_size_ratchet.py` pins every module of 300+ lines. Shrinking
  is free, and a pin that drifts far above reality is lowered (the ratchet's stale-pin test nags
  about this).
- **Frozen artifacts:** frozen paper/live bundles pin source by digest. Removing a strategy module
  or library code used by an existing frozen bundle must not break replay or the running lane.
  Check before removing.
- **Owner direction (CLAUDE.md):** focused checks per change, with the full suite when scope
  warrants it.

## 4. Decisions

### Owner decisions
1. **Web app:** remove `web/`, `deploy/systemd/algua-web.service` and the CI `web` job. The owner
   still wants a dashboard as their interface. It will be a separate design: minimal widgets, no
   empty elements.
2. **Unused command groups:** the owner never runs these by hand and no automation calls them.
   Remove `campaign`, `backtest replay` (portfolio replay), `negative`, `governance` and
   `paper-mechanics`, with their supporting modules and tests. Supporting code that other code
   still uses stays.
3. **Fundamentals and news, current form:** remove `ingest-fundamentals`, `query-fundamentals`,
   `ingest-news`, `query-news`, `data fetch-fundamentals`/`fetch-news`, the providers
   (`yfinance_fundamentals`, `yahoo_news`), schemas, stores, `hindsight` queries and the two
   strategies that use them. They come back later through a composable redesign under the
   generic strategy contract.
4. **Speed and docs:** parallel test execution, a fast/slow split, and archiving historical plans
   and specs. Agreed.
5. **Statistics stack:** keep a trial-aware quality signal; remove the rest (§4.7–4.9).

### Design calls (Claude's; owner may override)
6. **Order.** Speed first (§5 step 1), so every later step verifies fast. Then the docs archive.
   Then one removal per branch, safest first. The statistics stack goes last, because it is
   protected and the largest.
7. **The kept quality signal.** `research/dsr.py` (deflated Sharpe) and `backtest/bootstrap.py`
   (bootstrap interval on holdout Sharpe) stay.
   - **Trial count.** The unit stays sweep combos; counting each strategy once would weaken the
     deflation. `effective_funnel_breadth` (`research/dsr.py`) drops its family term and becomes
     `max(own lifetime combos, funnel-wide windowed combos)`. The window keeps today's rolling
     calendar window. Every gate run that recorded breadth counts, failed ones and human runs
     included. The trial-Sharpe variance keeps today's source: the strategy's own sweep, with the
     funnel floor.
   - **The measured-breadth preflight stays binding.** That is the refusal of a promote with no
     recorded `backtest sweep` breadth (`registry/promotion.py`). The `search_trials` recording
     that feeds the count stays too.
   - The PIT spec's per-seal-window evaluation counter (its decision 19) is a separate number: how
     many strategies were evaluated on the sealed window. It is shown beside this one, not
     substituted for it.
   - `research/campaign_policy.py` and the research loop's `--choose-campaign` mode are not part of
     the `campaign` command removal (§4.2). They stay.
   - The signal stays **advisory**: recorded and shown on every promote, vetoing nothing.
   - Making it binding is a separate owner decision. It is the change that would most improve
     strategy quality.
8. **Removed from the statistics stack:**
   - the LORD++ FDR ledger and its throttle code;
   - family classification (code ancestry, factor lineage, return-correlation clustering);
   - parentage edges and lifetime priors;
   - regime robustness, window stability and idiosyncratic-alpha checks;
   - `research/haircut.py`;
   - the eval harness (`research/eval_harness.py`, `eval gate`), which measured the old gate.

   DB columns and tables these wrote stay in the schema and read as historical. New rows write
   NULL. No destructive migration.
9. **`AGENT_NOVEL_MINT_CAP` goes with family governance.**
   - It bounded agents minting fresh families to escape the breadth tax. With no family-scoped
     tax, there is nothing to escape.
   - The trial count in §4.7 counts every recorded sweep funnel-wide, whatever its family, so
     disguising a sibling as a new family gains nothing.
   - **Owner approved 2026-11-12.** This removes a binding control. Accepted gap: the funnel-wide
     count covers a rolling window, so an old burst of trials stops counting (a strategy's own
     lifetime combos still count). Revisit if the deflated bar is made binding.
10. **Strategy modules.**
    - Remove a strategy module only if all of these hold:
      - its registry stage is `retired`;
      - no frozen bundle pins it;
      - no test or fixture imports it;
      - it is not a template or infrastructure module (`strategies/ml/model_*`,
        `cross_sectional_momentum`, `midcap_weekly_momentum_smoke`).
    - Work in progress (`idea`, `backtested`, `candidate`) and anything operational stays.
    - Git history keeps the removed source. There is no gate-row replay path that needs it.
    - The live VPS registry is the authority for stages. The builder reads it read-only
      (`registry list` over the existing deploy access). If that access is unavailable, the owner
      supplies the output. The kept/removed list goes in the PR.
11. **Docs archive.** Delete historical plans and specs from `docs/superpowers/` and
    `docs/development/` unless `CLAUDE.md`, `AGENTS.md`, `docs/architecture.md`,
    `docs/vision-reconciliation.md`, `docs/agent/*` or a kept code docstring links to them, or they
    are from the last 14 days. Git history is the archive. Fix or remove dangling links.
12. **Test speed.**
    - Add `pytest-xdist` as a dev dependency and run `-n auto` by default.
    - Tests that cannot run in parallel get an `xdist_group` or a `serial` marker. Fix their shared
      state rather than serialising widely.
    - Add a `slow` marker. Any test over 5 s in a `--durations` run gets it.
    - The default run is `-m "not slow"`; the full run is `-m ""`. CI's manual workflow runs the
      full set.
13. **Research memory stays** for now: `algua-research.service` calls it. Revisit separately.

14. **Doc correction: where the edge is judged.**
`CLAUDE.md` (research promote bullet) says the forward gate "is the harsh threshold … so overfit
inflation self-punishes". That holds only on the **strict** route (`paper promote`, 63 broker-clocked
observations, Sharpe ≥ max(0.5× holdout, 0.3)).

On the **capped experimental** route the forward test is the evaluation on already-present
out-of-sample data:
- the research gate's non-reused PIT holdout, and later the sealed window of the PIT spec;
- the five paper sessions prove the machine, not the edge;
- the binding economic bar there is holdout Sharpe > 0 over at least 63 bars, a weak filter: with
  no edge, roughly half of all candidates pass.

The trim updates `CLAUDE.md`, `docs/architecture.md`, `docs/agent/capped-live.md` and
`docs/vision-reconciliation.md` to say this plainly, and to point to the kept trial-aware signal
(§4.7) as the advisory quality measure and candidate binding bar.

## 5. Sequence

Each step is one branch, small enough to review, merged before the next.
1. **Speed.** Add xdist, the markers and the CI workflow change. Measure before and after.
2. **Docs archive** (§4.11) and the doc correction (§4.14).
3. **Web app removal** (§4.1).
4. **Unused command groups** (§4.2), one commit per group.
5. **Fundamentals and news removal** (§4.3).
6. **Strategy pruning** (§4.10).
7. **Statistics stack** (§4.5, §4.7–4.9). Protected and human-reviewed. It ends with the DSR
   trial count rewired to the plain count (§4.7).

## 6. Left to the builder

- Exact module lists per removal, found by import tracing. Shared helpers that stay are noted in the
  PR.
- Which tests need `xdist_group`, and how to fix their shared state.
- Whether any removed command is referenced by `scripts/`, `.opencode/`, `.claude/skills/` or
  `deploy/`. Update or remove those references.
- Import-linter contracts orphaned by removals.
- Size-ratchet pins to lower after shrinking.
- How the plain trial count is stored. A query over existing gate rows is preferred over a new
  table.
- The before/after numbers: lines of code and tests, test count, default and full run times. They
  are reported in each PR.
