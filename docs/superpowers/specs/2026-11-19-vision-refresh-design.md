# Vision refresh — evidence, capital and market roadmap

**Status:** Draft for owner approval · **Date:** 2026-11-19 · **Owner:** Lior Nisimov
**Origin:** owner design session ("roadmap"), 2026-11-16 → 2026-11-19, with two independent Codex
reviews folded in.

This document records owner decisions that amend the [PRD](../../PRD.md). Once approved, the PRD,
operating guides and agent instructions are updated to match (see §12). Until the code described
here is built and accepted, the operating guides keep describing what the code enforces **today**;
every target below that is not yet enforced is labelled as a target and linked to its work card.

---

## 1. Intent

Algua exists to make net trading profit. The owner wants the machine to tell the **truth** about
whether an edge exists — "the bitter truth over the blissful lie" — while requiring as little
routine owner attention as possible. The owner is a capital allocator, not a reviewer: no human code
review, no recurring decisions, one-tap approvals only where authority requires a human.

The path to money is fixed in this order:

```
personal capital ──► funded futures accounts ──► audited multi-year live record ──► client money
  (prove an edge)       (multiply it)               (comes from both)               (scale it)
```

### Goals
- A gate that certifies only edges that are real **and** worth money, robust to multiple testing,
  data snooping, LLM knowledge contamination and distribution shift.
- Capital that grows only on live evidence and shrinks automatically on failure.
- A side-agnostic core so the futures/funded lane does not require a core rewrite.
- An ideation engine that spends research effort where yield is measured to be highest.

### Non-goals
- Proving alpha by a deadline. No milestone lowers a gate.
- Forex. Options. Client money before its prerequisites (§9).
- Intraday US-stock operation (intraday arrives with futures).

### Anti-goals (would be failure even if it "works")
- Any path where agents or the owner can see holdout results and iterate on them.
- Any gate a lucky strategy passes with meaningful probability.
- Any design that needs recurring owner attention.
- Responding to a thesis failure by adding features (§10).

---

## 2. Vocabulary (minimal, used everywhere)

| Word | Meaning | Question it answers |
|---|---|---|
| **train** | Oldest history. Agents build and tune freely. | — |
| **validation** | History after train. Agents analyse failures, tweak and retry. Burned by iteration, and charged for it by the pre-screen. | "Is it worth a holdout trial?" |
| **holdout** | The sealed most-recent history. One test per frozen strategy. Nobody sees its numbers. | **"Is the edge real and good?"** |
| **freeze** | Code, config, data contract and model recipe hashed before the holdout. Any later change = new strategy. | "Is it the thing we tested?" |
| **probation** | Paper trading on new data after the holdout pass. | "Is it broken?" |
| **live** | Real money on the capital ladder. | "Is it still good?" |
| **trial** | One holdout evaluation. Counted for life. | — |

**Dropped terms:** forward / forward test / forward-tested / forward certificate, OOS as a gate term
(walk-forward survives only as a research tool name), strict route, capped route, "five paper
sessions", the 63-bar holdout floor, qualification profile, candidate-preview, experimental
activation.

**Lifecycle stages:** `idea → research → holdout → probation → live → retired`, plus `dormant`
(benched; can return). `holdout` as a stage means "passed the holdout". Code renames are part of the
migration (§11); until then docs give a one-line mapping (`backtested`→research,
`candidate`→holdout, `paper`→probation, `forward_tested` removed).

---

## 3. Data split

- Source: Sharadar daily US equities (full history from ~1998; verify on the installed data).
- **Train:** 1998 → 2013. **Validation:** 2014-01-01 → 2017-12-31.
  **Holdout:** 2018-01-01 → 2025-12-31 (8 complete calendar years). Boundaries are exchange
  sessions, pinned exactly; labels that cross a boundary are purged.
- The current incomplete year belongs to no split until it completes.
- **Sliding:** each January all three windows advance one year; the oldest holdout year enters
  validation and the completed year enters the holdout. Research thereby keeps learning recent
  markets and the gate always judges the latest 8 years.
- **Precondition:** every split year must be point-in-time qualified (survivorship, delistings,
  corporate actions, membership as of date). Unqualified years cannot be holdout years.
- **Fundamentals:** the current ARQ provider assumes a reporting lag rather than certifying
  availability (`algua/data/providers/sharadar_fundamentals.py`). Strategies using fundamentals are
  **not holdout-eligible** until availability/revision semantics are certified. Price-only
  strategies are unaffected.

---

## 4. The holdout gate

### 4.1 Eligibility (pre-screen)
A frozen strategy may reserve a trial only if, on train+validation data alone:
1. purged walk-forward excess return is positive against both benchmarks (§4.3) after costs; and
2. deflated Sharpe ≥ 0.95, where the trial count includes **every** variant evaluated for it:
   sweeps, manual edits, signal subsets, weightings, transforms and abandoned branches.
3. It is deployable under current capital policy: long-only for stocks; both directions only for
   instruments whose policy allows shorts (futures, later). Long-short stock evaluation is a
   research diagnostic only.
4. It uses only holdout-eligible inputs (§3 fundamentals rule; §6 model-feature rules).

Hard rate cap: **10 trials per calendar month**.

### 4.2 Trial accounting
- A trial is **reserved atomically before any holdout data is read**; a crashed, aborted or
  erroring evaluation still consumes its trial.
- **Lifetime budget N = 500**, never reset, across all holdout windows. Each trial is tested at
  one-sided α = 0.05 / 500 (critical t ≈ 3.72). Overlapping/sliding windows are covered because each
  trial's null p-value is valid on its own window.
- When 500 is reached the gate refuses new trials and a thesis review is opened (§10). Raising N is
  a signed owner decision recorded in the PRD.

### 4.3 Pass criteria (all required)
Returns are daily, net of modelled costs, in excess of the cash rate.
1. **Alpha vs SPY:** regression intercept with Newey-West (HAC) standard errors, t ≥ 3.72.
2. **Alpha vs universe equal-weight:** same test against an equal-weight portfolio of the
   strategy's declared universe — point-in-time membership, lagged one session, investable, with
   its own turnover and costs.
3. **Economic hurdle:** estimated annualised alpha ≥ **2%** against both benchmarks.
4. **Beats SPY in money:** cumulative net return over the holdout > SPY's (sign check).
5. **No decay:** alpha positive in ≥ 6 of 8 holdout years and over the most recent two years
   combined. The power of this rule is checked by simulation before enforcement.

Both benchmark tests must pass (intersection test; no extra correction).

### 4.4 Blindness
- Holdout bars and every holdout result live in a store the research runtime user cannot read,
  enforced by OS permissions on the VPS. The gate runs as a separate privileged step.
- **Agents see nothing** about holdout outcomes — not numbers, not pass/fail. Ideation inputs,
  scorecards and bandit rewards must never contain holdout or gate outcomes, nor stage changes that
  reveal them (the current `algua/registry/idea_scorecard.py` downstream fields are removed from
  ideation inputs).
- **The owner sees** pass/fail per criterion and the trial counter — never holdout numbers or
  charts. When approving, the owner sees train/validation detail, probation results, capacity,
  costs and gate self-test status.

### 4.5 Gate self-tests
On a schedule and before any trial: (a) seeded planted-alpha fixtures must pass; (b) a large
random-signal simulation must pass at no more than the nominal rate (~1/10,000 per trial). Any
failure halts the gate until fixed. Fixtures verify correctness; the simulation verifies size and
power. Neither consumes trials or touches the real holdout.

---

## 5. Probation, live and capital

### 5.1 Probation (paper)
- Length: at least **20 sessions and** at least **3 completed rebalances**, whichever is later.
- Pass requires:
  1. **Mechanics:** every order submitted and resolved; zero ledger/broker difference each session;
     no duplicates; one forced restart during an **uncertain** order survived; partial fills
     reconciled.
  2. **Tracking:** paper returns match a backtest replay of the same days within tolerance
     (cumulative gap < 10% of the replay's volatility over the window).
  3. **No blowup:** drawdown within what the strategy's validation-period volatility makes
     plausible.
- A platform-bug failure allows a rerun of probation after the fix without a new trial (max two);
  a strategy change is a new strategy and needs a new trial.

### 5.2 First live step = real-cost check
Paper cannot measure real costs. During the first live step the same replay comparison runs on
real fills. If realised implementation costs exceed the modelled costs beyond tolerance, the
strategy is paused automatically and its **deployment qualification** is voided; the historical
holdout verdict stands as recorded.

### 5.3 Live evidence
- Economic evidence = actual broker-marked, benchmark-relative net returns. Replay is a diagnostic.
- An anytime-valid confidence sequence on live alpha against the **2% hurdle**, with its target
  and dependence assumptions specified in the implementation spec.
- **Bench** (→ `dormant`) when the upper confidence bound of live alpha falls below zero.
- Execution faults (reconciliation breaks, duplicate orders, stale data) stop trading immediately,
  independent of evidence.
- Dormant strategies keep being scored on new data and may re-climb from the first step.

### 5.4 Capital ladder (USD)
The owner deposits USD; all limits, ledgers and reports are in USD.

| Step | 1 | 2 | 3 | 4 | 5 (cap) |
|---|---|---|---|---|---|
| Allocation | $600 | $900 | $1,350 | $2,000 | $3,000 |

- **Step up** (needs owner passkey approval) when all hold: at least one quarter on the current
  step; live evidence **not falsified** against the hurdle; drawdown within the step's band; next
  step below the strategy's measured capacity.
- **Step down** (automatic, no approval): −1 step at a 5% drawdown from the step's peak; halve at
  10%; account halt at 20% (existing layered policy). The tighter of the per-strategy and account
  rules binds. Peaks are cash-flow adjusted.
- Re-climbing after a step-down follows the same step-up rule.
- **Proof levels** — live confidence that alpha > hurdle at 97.5% — are reserved for decisions
  beyond the ladder: raising the per-strategy cap, funded deployment of a lane, client money.
- **Account ceilings:** $15,000 during the owner's current incubation period; $60,000 after a
  signed owner change. Changing any ceiling or cap is a signed policy change.
- Each approval is bound to the strategy's frozen identity, account, instrument list and exact USD
  amount.

### 5.5 Owner approval mechanism
- Primary: **passkey (WebAuthn)** on the owner's phone through the dashboard — one tap plus
  biometric. The server holds only a public key; agents cannot forge an approval.
- Backup: the existing SSH signature ceremony.
- Passwords and TOTP are rejected: the verifier must store the secret, which agents on the same
  host could read.

### 5.6 Payments
The owner approves every payment; there is no standing spend budget. The dashboard shows monthly
cost (data, LLM, VPS, fees) beside live P&L and alpha. The LLM bill is measured first.

---

## 6. Model-based strategies

- **ML:** the frozen object is the **recipe** — features, model class, fixed hyperparameters,
  training-window length and retrain schedule. The holdout runs walk-forward retraining exactly as
  live will. All tuning happens in train/validation and counts toward the pre-screen. Training must
  be deterministic (or within a stated tolerance); the gate re-trains a sample point to verify.
- **Model-derived text features** (LLM or encoder):
  - *Local task on anonymised input* (sentiment, tone, guidance direction; entity, ticker and date
    masked): holdout-eligible **only** when the model's training cutoff is verifiable and precedes
    the holdout, or the model is trained point-in-time, **and** a raw-vs-anonymised leak probe
    shows no systematic difference.
  - *Knowledge tasks* (implications, relevance, return prediction): shadow-only.
  - *Models with undisclosed or unverifiable cutoffs* (including hosted models such as TypeSafe
    Jev): shadow-only.
  - Hosted models additionally require an immutable score cache keyed by model version and input
    hash; a model version change is a new strategy.
- **Shadow qualification:** the strategy is computed on new data without capital until its live-
  style confidence sequence clears the hurdle, then enters probation.
- Reference: Glasserman & Lin (2023), arXiv:2309.17322 — anonymisation reduced bias from model
  knowledge in GPT sentiment signals.

---

## 7. Idea provenance

Every idea records its source, the source's publication date and the developing model. Ideas are
classed pre-holdout, post-holdout or agent-originated. Once enough live strategies exist, holdout
alpha versus live alpha is compared per class; a class with materially larger decay gets a stricter
live hurdle, decided by data and logged. No source-date gate rule is imposed now.

---

## 8. Ideation and the signal library

- **Unit of research = signal.** Ideas become signals in a library; strategies are frozen
  combinations of library signals. One frozen combination = one trial.
- **Admission** (deterministic, before compute): falsifiable mechanism (who loses money and why);
  expected direction and horizon; data feasibility with timestamped input coverage; duplicate
  screen = absolute per-date cross-sectional rank correlation on common coverage (0.8 flags,
  followed by top-bucket overlap and P&L similarity checks).
- **Library statistics:** train IC is diagnostic; combination candidates also need walk-forward IC
  stability, long-only top-bucket economics and turnover after costs.
- **Combination search** is the largest multiple-testing source: combination depth is capped and
  every evaluated subset, weighting and transform is logged and counted in the pre-screen.
- **Lineage ledger:** immutable source → idea → signal version → combination → evaluation links
  with idempotent reward events.
- **Budget allocation:** equal rotation across category × source-type arms until each arm has
  ~10 completed pulls; then Thompson sampling with pooled category/source effects, a cap on
  outstanding pulls per arm, batch updates and a randomized exploration floor. Reward decay is
  calibrated against the observed outcome lag. Owner Inbox ideas use a bounded priority queue.
- **Reward (staged):** a small capped credit for library admission; most weight on incremental
  contribution to a pre-screen survivor, credited by research-only leave-one-out reruns (mere
  inclusion earns nothing; ablations count as variants). Failures are classified — economic failure
  is penalised; missing data, infrastructure errors and untried signals are not. Rewards use
  train/validation outcomes only.
- **Data wishlist:** ideas blocked only by missing data are recorded and ranked by distinct
  experiments unlocked, PIT feasibility and cost, as evidence for owner purchase decisions.

---

## 9. Markets, side-agnostic core and the funded path

### 9.1 Market order
1. **US stocks, daily** — now. Best odds of a first proven edge; data and infrastructure exist.
2. **Futures** — a second research lane opens when the holdout gate is enforced in code and the
   first stock campaign runs on qualified data. Stock edges do not port; futures edges are
   researched natively. Intraday operation arrives here.
3. **Forex** — dropped.
4. **Client money** — only after ~3 years of audited live record, measured strategy capacity and
   legal clearance (licensing in Israel and any client jurisdiction). Until then the PRD's "no
   authority to manage client capital" stands.

Funded deployment of a futures strategy requires that strategy's live proof level (§5.4). A survey
of funded futures programs (rules, automation policy, eligibility for an Israeli resident, payout
reliability, data/platform requirements) precedes it and informs the account-rule format.

### 9.2 Side-agnostic core (build now, furnish stocks only)
- **Signed positions** everywhere; "long-only" becomes an instrument/account **policy** checked at
  one place with one error code. Today's short refusals (`algua/live/book_exposure.py`,
  `algua/backtest/portfolio.py`) are replaced by that policy check.
- **Instrument model:** asset class, multiplier, tick size, currency, margin rule, short policy,
  calendar. Stocks/ETFs use multiplier 1, USD, cash margin, no shorts.
- **Account rules as data:** one rule-set format expressing the layered drawdown policy, daily
  loss, exposure caps, the per-strategy ladder and future funded rules (trailing drawdown, daily
  loss limit, max contracts, flat-by time, consistency). Evaluated each tick; intraday evaluation
  arrives with futures.
- Nothing futures-specific is built now (no data adapter, rolls, CME calendar or broker).
- **Acceptance invariants** (owner does not review code; these tests are the safety net):
  1. existing stock strategies produce byte-identical backtests, orders and ledgers;
  2. cash plus marked positions is conserved through a simulated short round trip after fees;
  3. ledger-versus-broker difference is zero after long, short, partial-fill and restart scenarios;
  4. a negative weight on a long-only instrument is refused at exactly one place with one code in
     research, paper and live;
  5. the same rule set gives the same verdict in backtest and live on the same data.
- Delivery: a frozen interface contract first, then three parallel tracks (instrument model,
  research-side signed positions, account rules), then paper/live signed positions, then an
  integration step that runs all invariants. Agent review only.

---

## 10. Thesis review (PRD §29 made concrete)

A thesis review opens automatically at the first of:
1. 100 holdout trials on qualified data with zero passes while gate self-tests are green;
2. 18 months after gate enforcement with no strategy past probation;
3. 24 months of operating cost with no live strategy whose evidence is not falsified;
4. the 500-trial budget is exhausted.

These triggers start a diagnosis (power, funnel losses, data limits), not an automatic verdict —
zero passes in 100 trials is common even at a true 1% pass rate. The review ends in one recorded
decision: change approach (data, market, strategy class), change scale (cost, cadence), or stop.
Adding features is not an allowed outcome.

---

## 11. Migration

- **Build the new gate alongside the old, cut over, delete the old.** Removed after cutover:
  `paper promote`, the 63-session forward gate, forward certificates, the `forward_tested` stage,
  the 63-bar holdout floor and `Sharpe > 0` gate, the five-session qualification and the capped
  route's separate ceremony steps. Identity-bound probation/holdout evidence replaces the forward
  certificate **before** its precondition (`algua/registry/transitions.py`) is removed.
- **Kept:** layered account risk, SSH signing (as backup), single-use identities, the `t→t+1`
  rule, PIT checks, the JSON CLI contract.
- **Legacy research is contaminated** (built on data inside the new holdout). Existing strategies
  are retired as pre-gate. Legacy results — KB research runs, family notes, MLflow runs, idea-pool
  outcomes, VPS research records — are archived to the owner's private Drive with their trial
  counts and provenance, then removed from every agent-reachable location. Research worktrees are
  shallow so git history is not an easy path back. Ideas themselves are re-derivable and are not
  preserved for agents. This is "no direct path", not a sealed wall; gate self-tests and live
  evidence are the backstop.
- Running paper tenants are drained and retired after `fleet status` is checked.

---

## 12. Context-file and board updates (first implementation step)

- **PRD:** add this document's decisions as an owner amendment: vocabulary; evidence design; capital
  ladder and ceilings in USD (replacing §21's ₪ budget); payment rule; market order and stages
  (replacing §24 and §25's phase list with §13 below); §22 funded/external capital; §29 triggers.
- **CLAUDE.md, AGENTS.md, README, `docs/agent/*`, `.opencode/agents/*`, `.opencode/skills/*`:**
  adopt the vocabulary; describe the single route; mark each not-yet-enforced item as a target
  with its card; stop describing the strict/capped routes as current options once removed.
- Personal financial context never enters this public repository; only the capital rules do.
- **Todoist (Algua project):** retire cards built on the old route; add cards for every
  implementation item here, in the stage order of §13, with dependencies.

---

## 13. Stages

| Stage | Goal | Ends when |
|---|---|---|
| **1. Proven machine** | Qualified Sharadar history; holdout gate, blindness and self-tests enforced; migration done; side-agnostic core built in parallel; ideation/signal library | Gate enforced, self-tests green, first campaign running |
| **2. First edge** | Campaigns on qualified data → holdout pass → probation → first live step | First live strategy |
| **3. Proven edge** | Ladder climbs; 2–3 uncorrelated edges | A strategy reaches the proof level |
| **4. Funded** | Futures lane (opened at end of Stage 1) produces futures edges; funded program chosen; intraday risk | Funded payouts |
| **5. Scale** | More edges, funded accounts, ceiling increases | — |
| **6. External capital** | §9.1 prerequisites met | Licensed client money |

Work in progress: two tracks at a time — the Stage 1 critical path (data → gate → migration →
campaign) and the side-agnostic core — each internally parallelised against frozen interface
contracts.

---

## 14. Approaches considered

| Decision | Chosen | Rejected and why |
|---|---|---|
| Evidence of edge | Sealed historical holdout + live evidence | Paper forward economic gate (63 sessions): too slow to prove anything; tiered entry bars: an extra moving part |
| Multiple testing | Lifetime Bonferroni N=500 | Alpha-investing: complex, path-dependent; recomputed bars: could revoke a pass after money is in |
| Holdout window | Sliding 8 years | Expanding: research frozen on pre-2018 markets |
| "Good" | Alpha vs both benchmarks + beats SPY + hurdle + decay | Raw excess only: unfair to low-beta/long-short; alpha only: can lose to SPY in money |
| Holdout visibility | Nobody sees numbers | Owner sees failures: the owner becomes a leak |
| Live step-ups | Not falsified + time | Proof at every step: 5–10 years to the cap |
| Bar size | Daily stocks; intraday with futures | 4h stock bars: no extra evidence per year, no PIT intraday data, lopsided sessions |
| Market | Stocks → futures; forex dropped | Futures first: discards the near-finished stock pipeline |
| Legacy research | Archive to Drive, remove from agents | Keep visible: contaminates the holdout via memory |
| Ideation allocation | Equal rotation then Thompson sampling | Hand-set thesis weights; owner-set themes (recurring involvement) |

---

## 15. Clarifications (builder check, 2026-11-19)

Items marked *(call)* were settled by Claude without the owner; the owner can override.

1. **Data visibility by runtime.** *(call)* The research runtime reads only train and validation
   bars. Holdout bars **and the current incomplete year** (the next holdout year) are unreadable to
   research. The operator, paper and live runtimes read all bars; they do not do research. Research
   agents also cannot read lifecycle stages beyond `research`, probation or live results, because
   any of these reveals a holdout verdict. The dashboard shows them to the owner only.
2. **Variant counting for the pre-screen.** *(call)* Counted per strategy lineage (a lineage is
   rooted at the admitted signals/idea and inherits every derived variant). Every backtest,
   walk-forward or sweep the research CLI executes is logged with its lineage ID, on train or
   validation data alike — the CLI is the instrumentation point, so agent code edits cannot escape
   it. DSR is computed on the validation-period returns of the selected variant. Funnel-wide
   multiplicity is the holdout counter's job (§4.2), not the pre-screen's.
3. **Agent autonomy.** Agents may reserve trials, run the gate, and move `research → holdout →
   probation` autonomously, mirroring today's ceiling. The research worker's own ceiling stays at
   `research`. **The first live step ($600) needs the owner's passkey approval**, as do all
   step-ups; step-downs and benching never do.
4. **Decay-rule power.** *(call)* Simulation runs before the first trial. If the 6-of-8 rule rejects
   a true alpha that clears the other criteria more than 30% of the time, it is relaxed to 5 of 8.
   Whatever is chosen is fixed before the first trial and never changed while trials are counted.
5. **Legacy removal scope.** *(call, per the owner's "no direct path" decision)* Delete from the
   current tree and every runtime store; research worktrees are shallow; **no git history
   rewrite**. The Drive archive is produced by an owner-side session (not a research agent) before
   deletion.
6. **January slide.** *(call)* A recorded pass stands — it is a verdict on the window it was tested
   on. Frozen strategies that never took a trial must re-run the pre-screen on the new validation
   window. The trial counter never resets; the monthly cap is calendar-based.
7. **Passkey trust boundary.** *(call)* WebAuthn assertions are verified inside the platform
   (`algua/`), against public keys held with the existing approval anchor next to
   `approvers/allowed_signers`. `web/` only relays challenge and assertion; the platform never trusts
   a web-reported verdict.
8. **Ideation sequencing.** *(call)* The lineage ledger and signal admission are on the Stage 1
   critical path, because the pre-screen cannot count variants without them. The first campaign may
   run single-signal strategies; combination search and the bandit follow once the ledger exists.
9. **Payments.** *(call)* Policy plus the cost display only. Agents have no payment means, so no
   spending-approval feature is built.

## 16. Left to the builder

Exact tolerances where this document gives only intent (probation tracking tolerance details, cost
breach tolerance, confidence-sequence family), file/module layout, schema design, the OS-permission
mechanism for the holdout store, and test fixtures — each to be fixed in the component's
implementation spec and covered by tests before cutover.
