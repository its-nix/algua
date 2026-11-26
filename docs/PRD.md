# Algua — Product Requirements (Vision of Record)

**Version:** 2026-11-26 · **Owner:** Lior Nisimov
**Replaces:** the previous 30-section PRD (stock-era; kept in git history) and its 2026-11-22 owner
amendment.
**Decision history:** [vision refresh design](superpowers/specs/2026-11-19-vision-refresh-design.md),
revisions 1–6 (2026-11-16 → 2026-11-26). It records why each choice was made; this PRD is the single
current statement.

> **Read this first (implementing agents).**
> 1. **None of the new core described here is built yet.** The repository today is a daily-stock
>    platform (Alpaca, `forward_tested`, capped-live ceremonies, research timers).
> 2. **Present permissions still come from `CLAUDE.md`, `AGENTS.md` and the operating guides**, which
>    describe today's code. Adopting this PRD changes **no** gate, capital setting, runtime control or
>    permission. A conflict is work to reconcile through review, never authorization to bypass a
>    control.
> 3. Those guides still cite the old PRD's section numbers (e.g. "PRD §25"). Updating them is the first
>    task in §24.
> 4. **You may never put a strategy or desk live.** Real money always requires the owner's signed
>    package (§12).

---

## 1. North star

**Make the owner rich from trading profit, as soon as honestly possible.**

Algua is a **mostly autonomous intraday CME micro-futures trading system**. Agents research
strategies; one honest evidence pipeline decides which deserve money; a tiny trusted executor trades
them on IBKR, flat every day; confirmed edges are later multiplied through funded prop accounts and,
much later, possibly outside capital.

The ultimate product is **net trading profit**. Software, agents, models, dashboards and data exist only
to produce it. Technical sophistication has no value unless it improves expected net profit, capital
scalability, risk, autonomy or research learning speed.

**Why intraday futures.** The binding constraint is capital, not ideas. On a $15k personal budget even
a strong edge earns little; funded prop accounts give $50k–150k of trading size for a fee, and every
verified bot-friendly firm requires being **flat by the end of the trading day**. Intraday also yields
evidence faster than daily trading, trades both directions, and avoids overnight gaps. Personal IBKR
trading produces the **evidence**; funded accounts are a later **multiplier**. A funded pass is never
evidence.

**Where speed comes from.** Two things limit how fast money arrives: (1) finding strategies that are
actually good — only ~1 in 13 distinct ideas is expected to pass the holdout under illustrative
assumptions — and (2) collecting enough independent forward evidence to trust them. So Algua observes
every candidate in parallel for free, lets many strategies trade through **one desk** (§9.5), and makes
generating genuinely different ideas a first-class goal (§13).

### Priority order (when objectives conflict)
1. Net profitability · 2. Capital scalability · 3. Risk control · 4. Autonomy · 5. Research learning
speed · 6. Code quality and simplicity · 7. Everything else.

### Roadmap admission test
Every roadmap item must say how it improves expected net profit, risk, capital scalability, autonomy or
research learning speed. If the answer is unclear, it doesn't belong.

---

## 2. Goals, non-goals, anti-goals

### Goals
- Find intraday futures edges that survive realistic execution, judged on data research never saw.
- Optimise **net dollars per trading session after running costs**, not pass rates or attractive
  reward-to-risk ratios.
- Prefer edges that are **stable**: they survive small, pre-declared changes (§9.6).
- Keep the system small enough to reach paper trading in about three weeks and run unattended.
- Keep every loss limit in code and at the broker; grow size only on evidence.
- Operating cost near **$150/month**.
- Operate unattended: target **72 hours without attention**, either operating correctly or reaching a
  predefined safe state on its own.

### Non-goals
- Daily or multi-day stock trading (lane frozen, §20). Spot forex, options, crypto, CFDs.
- Proving an edge by a deadline. **No date lowers a bar.**
- A SaaS, multi-tenant, social-trading, HFT or generic agent-framework product; infrastructure for its
  own sake; speculative dashboards, microservices or plugin systems.

### Anti-goals (failure even if it "works")
- Scaling the luckiest of many experiments.
- Treating backtests, leaderboards, holdout passes or challenge passes as proof.
- Machinery that manages a problem when one rule could prevent it (§6).
- Research-written code with any authority over money.
- Hidden-risk strategies: martingale, grid, averaging down, no stop. Also rejected: leveraged ETFs,
  short-volatility strategies, margin before evidence.
- Anything needing routine owner attention beyond the weekly broker login.

---

## 3. How the owner works with Algua

- **The owner is a capital allocator, not a reviewer or operator.** No human code review; agent review
  is sufficient. No recurring decisions. One-tap signed approvals only where real money requires a
  human (§12). The list of routine owner duties must shrink, never grow.
- **Agents may always reduce risk without permission** (halt, flatten, remove a desk member). Agents
  may never raise the capital entrusted to them or modify their own authority boundaries.
- **Inspect, don't ask.** Agents check the system themselves (VPS, registries, broker state) instead of
  asking the owner questions the system can answer.
- **Outside reviews before pivotal decisions:** independent reviewers from other providers (Codex
  "Astra" = gpt-6-astra, Grok) read the design and attack it; their findings are reconciled, not
  rubber-stamped.
- **The design lens (owner-endorsed):** prefer **one structural rule** — a one-way flow or a single
  source of truth that makes a failure impossible — over counters, ledgers, caps and special-case
  adjustments. When a rule can only reduce a failure, say so.
- **Code:** generic, clean where it matters, as simple as possible. "Small in concepts, not
  artificially small in lines." Prefer obvious code, explicit state, pure computation, typed contracts,
  narrow interfaces, established libraries, deterministic behaviour and deletion over accumulation.
  Avoid speculative abstractions, frameworks, hidden state, duplicated execution paths and premature
  distribution. New abstractions need demonstrated repeated need. *Ship the simplest clean
  implementation.*
- **Money:** USD everywhere. **The owner approves every payment**; there is no standing agent spending
  budget. The dashboard shows monthly operating cost next to trading P&L.
- **Privacy:** this repository is public. Personal context never enters it; only the capital rules do.
  No private Drive links, credentials, trade or account records in the repo.
- **Owner Inbox:** the owner drops ideas into the Inbox; agents never run Inbox intake themselves;
  trading, evidence and capital never read the Inbox.

---

## 4. Economic thesis and honest expectations

All figures are **illustrative scenarios under stated assumptions, not forecasts** (assumptions: ~5%
of distinct mechanisms have durable edges; holdout power 60%; false-pass 5%; genuine net edge
0.10–0.20R per trade; trade SD ~1.8R; R = planned risk; 20 sessions/month; 1.5× clustering).

- **Costs dominate small edges.** A MES round trip costs about **$3.70** (IBKR commission + exchange
  fees ≈ $1.22, plus one adverse tick on each leg = $2.50). That is ~7% of a $50 risk and ~19% of a
  $20 risk. Running costs ($150/month) add a hurdle of ~0.15R per trade at one trade a day, ~0.05R at
  three.
- **One MES slot = income, not wealth.** A genuine +0.20R edge at 3 trades/day ≈ **$450/month** after
  running costs; +0.10R at 1 trade/day **loses** money after overhead.
- **Confirmation takes most of a year.** At +0.2R, 3 trades/day and clustering, ~600 forward trades
  (~10 months) give 80% power for one strategy. 100 trades is eligibility, not confirmation.
- **Desk simulations** (screened candidates, one live slot, 6 months): roughly **$100–300/month**;
  chance of hitting the $1,500 halt **~15–25%** in a bounded stop/target model and **~40–90%** in
  Astra's heavier-tailed model. An **unscreened** desk hits the halt **~65%** of the time in both.
- **Expected value** weighting by the chance candidates are real: about **$0 by end-2027, about
  +$1,000 by end-2028**. Real money comes from **scaling a confirmed desk** (more slots, funded
  accounts), likely late 2027 into 2028.
- **Most ideas fail.** A plausible outcome is a loss of a few thousand dollars and a clear "no".
- **Funded multiplier (later):** one confirmed edge can run on several funded accounts (FTMO allows
  copying the same strategy across one's own accounts; per-firm caps to verify). Illustration: 10%/year
  on a $50k account after the firm's cut ≈ $4k; five accounts ≈ $20k/year with only fees at risk.
- **Outside capital (long term, not now):** managing clients' money for fees is a bigger business than
  funded payouts, but only after a long, audited live record; this PRD grants no authority for it.

### AI thesis
AI multiplies research; it gets no statistical shortcut. LLM agents may research literature, generate
hypotheses, write strategies, analyse experiments and repair code. **Risk enforcement and execution
stay deterministic, inspectable and testable.** An AI component must beat simpler baselines on net
economic value. Where local or open models are economically equivalent, prefer them (the owner has a
local RTX 5070 Ti workstation and a VPS). Deterministic programs run numerical batches; no LLM call per
numerical trial. A model or prompt change that changes decisions is a new identity.

---

## 5. Vocabulary and lifecycle

| Word | Meaning |
|---|---|
| **strategy row** | Code + settings + simulator version, hashed. **Insert-only**; any change, including a single parameter or a new simulator version, is a new row. Evidence is appended immutably. There is no separate "freeze" step: every row is frozen by construction. |
| **research** | Building and tuning on train + validation history, in a sandbox. |
| **holdout** | One blind test per row on a sealed 2-year window. A screen, not proof. |
| **paper** | Every holdout passer is **observed in parallel**: the simulator scores its signals on live prices (free, unlimited). The IBKR paper account runs the desk to prove order handling. ("Paper trading" replaces the old word "shadow".) |
| **desk** | The executable policy that turns members' proposals into orders: membership, fixed priority, risk per member, slots, limits. The unit that qualifies, is signed and trades. |
| **slot** | One trade the desk may hold at a time. Version 1 has one MES slot. |
| **live** | A row is live while it is a member of the signed live desk. Live has a **ladder** of sizes; there is no separate "pilot" stage. |
| **desk package** | One signed, immutable bundle: complete executable identity, membership, account, contract, limits, expiry, one-time number. |
| **episode** | One trade from entry to every child order being terminal; it owns all its orders. |
| **halted** | A desk stopped by a limit; it can resume only through a new signed package. |
| **retired** | Terminal. A retired row never trades again; a revised idea is a new row. |
| **funded** | An extra account a confirmed desk/strategy may also trade. Not a stage. |
| **R** | Planned risk of one trade in dollars, including stressed costs. |

`idea → research → holdout → paper → live → retired`. A row leaving the live desk (futility or decay
alarm, §9.5) returns to paper observation. The stage is **derived** from the row's appended evidence and
the active desk package, not stored as separately managed state.

---

## 6. The seven rules

Each rule replaces a set of special cases with one behaviour. A rule **prevents** a class of failure by
construction where it can and **reduces** it where it can't; the table says which.

| # | Rule | What goes wrong without it | Precise meaning and limits |
|---|---|---|---|
| 1 | **Information only flows outward.** Research hands rows out through a one-way mailbox and never receives anything back: no holdout result, no paper/live numbers, no hint of which strategies trade or sit on the desk. | Research tweaks a failed strategy and resubmits; a zero-edge idea retried 20 times passes a 5% test ~64% of the time (5 tries: ~23%). | Prevents feedback-driven tuning. Does **not** prevent luck: of 20 independent zero-edge rows, ~64% of the time at least one passes. So a holdout pass earns paper observation only (§9.2). The **only** channel back is the global simulator version (market-wide cost parameters, never strategy-specific results). Logs, agent memory, idea scorecards and maintenance work keep strategy and desk outcomes out of research. |
| 2 | **Evidence is calculated, never hand-entered.** One simulator scores every candidate **and the executable desk policy**, including allocation, skipped signals and account limits. | Separate paper and live scores with a correction between them; a desk judged by adding up members that could never all have traded. | Prevents inconsistent scoring, not model error. There is **one canonical modeled episode stream** per row; real execution may skip an episode (slot busy, blocked) but never invents or repeats one, and each signal is counted once. Trades used to calibrate the simulator are never counted as confirmation. |
| 3 | **If anything is uncertain, no new entries.** **One execution owner controls each account and contract.** | A crash after sending a buy leads to a second buy: 2 contracts, protection on 1. Two strategies net to "flat" while one's stop is still working and later opens an unmanaged short. | Every order belongs to exactly one episode until every child order is terminal, even after the position is closed. Any unresolved account state (submissions, unknown fills, unexpected positions or orders) blocks new entries. The executor never sends a second exit while one's outcome is unknown and never re-enters to replace a position that was actually stopped out. |
| 4 | **Every actual exposure has protection held at IBKR,** sent in one package with the entry, and **never removed while exposed.** **Every close goes through the episode's single exit authority.** | A server crash or a cancel-then-replace gap leaves a position unprotected; a separate "sell now" races the resting stop and reverses the position. | Stop, target, timed exit, daily-limit flatten, strategy flat and manual close all act **within the episode's exit OCA group** (a forced close is a market order joined to that group). Virtual offsets between strategies never count as protection or flatness. Version 1 uses a fixed stop and target and never modifies them. Proven in week 1 and at commissioning (§16.3); nothing executes during a market halt. |
| 5 | **Change only while quiescent.** Go-live, new desk packages and size steps happen only with **zero positions, zero working orders and zero unresolved submissions** on the account, under the execution lock. | A waiting order fills just after a new version starts; a restored second server trades alongside the first. | Each change is one signed, immutable **desk package** covering the complete executable identity (code, dependencies, settings, simulator version, account, contract family and roll schedule, **membership, priority, risk per member**, limits). Being flat daily makes this cheap; there are no hot membership changes. Scheduled rolls inside an active package happen while quiescent without a new signature. **One active executor:** a new or restored installation starts **disarmed**, fences the previous one, reconciles history and needs a fresh signed activation; trading authority is never restored from backup. |
| 6 | **Real money sets the limits.** Admit an order only if the **stressed account state after every outstanding order could fill** stays above every equity floor and within margin. | The simulator says −$300, slippage made it −$450, and the $400 limit never fires; a pending entry fills after the limit was reached. | Floors: today's start −$400, peak −$1,500, and the incubation floor, all from **marked account equity** (actual fills, open positions at current prices, accrued fees, adjusted for deposits and withdrawals). Stress = additional loss from current marked equity, including pending submissions and closing costs, with a finite gap allowance — a stress bound, never an absolute guarantee. Budgets and peaks belong to the account and the incubation; no row, desk package or approval resets them, and deposits never do. A stale mark blocks new entries and alerts. Simulated numbers only judge strategies. |
| 7 | **Only answers cross into the executor.** Research-written strategy code runs unprivileged (no credentials, no network, no database writes) and only **proposes** validated trades; only the trusted executor allocates risk and submits orders. | A buggy or malicious strategy touches the broker or the signing files. | **Validation contract:** side ∈ long/short/flat; finite, tick-aligned prices; stop on the correct side; approved contract; risk ≤ the member's cap in the package; fresh episode ID. Anything else is rejected and blocks entries. The worker runs under a timeout and resource limits; it can never delay the executor's exits. |

What the rules do **not** remove: loss totals and equity peaks, fees, margin, approval replay
protection, the order journal, and the safety tests. Where possible these are calculated from recorded
facts rather than tracked separately.

---

## 7. Owner decisions (binding)

1. Operating cost ~$150/month (cheaper model mix for routine agent work, fewer cycles; measure the
   actual VPS and LLM bill first).
2. **Pivot:** Algua is built for intraday futures aimed at funded payouts; a **lean new core** replaces
   the old machinery rather than refactoring it.
3. Research searches **entry × exit × sizing** (stops, trailing stops, targets, reward-to-risk, win
   rate) under the honesty rules in §9.
4. **Flat by end of day** for every strategy, for now.
5. **Personal broker: IBKR**, with a weekly login.
6. **Live step 1 loss budget: $600 for the whole desk pilot** (owner-confirmed 2026-11-26).
7. **No funded route → personal futures only.**
8. **Stage 0 is our own research** of funded routes; we don't wait on firms. Fallbacks in order: API
   bridge → TradingView → the owner sends orders by hand (last resort). No home rig.
9. Stages: **research → holdout → paper → live → retired.** Pilot and live are one stage, live, with a
   ladder. Funded is an extra account, not a stage.
10. **A strategy is an insert-only row;** evidence is appended immutably.
11. **The holdout stays,** as a blind screen (§9.2). The stage is called `holdout` (not
    `passed_holdout`).
12. **The design lens:** one structural rule instead of counters, ledgers, caps or adjustments.
13. Code is generic, clean where it matters, and as simple as possible.
14. USD everywhere; the owner approves every payment.
15. **The desk:** strategies are advisors that propose trades; **one trusted executor owns the
    account** and decides which proposals trade. The **desk as a whole** — members, priority order,
    risk per member and limits — qualifies for real money, is signed and is deployed. Version 1 has
    **one live MES slot**; more simultaneous trades come later on evidence.
16. **Risk per trade is chosen per strategy** within **$20–$50** (owner-confirmed
    2026-11-26); the simulator charges real costs, so tight-stop strategies survive only if their edge
    beats the larger cost share.
17. **Halt target:** the desk earns real money only while its predicted chance of hitting the drawdown
    halt within the next 20 sessions is **≤5%**, under dependence and cost stress.
18. **Old research results** (pre-migration run reports, metrics, MLflow runs, idea-pool outcomes, VPS
    research records) are archived to the owner's access-controlled Drive and removed from every
    agent-reachable place (§20).
19. **Signing:** SSH signatures from the phone first; passkey later. No password/TOTP (the verifier
    must not hold a secret).

---

## 8. Markets and data

- **Instruments:** CME micro futures. Version 1 trades **MES only**; MNQ, M2K, MYM, MGC, MCL and micro
  rates/FX follow. MES/MNQ/MYM/M2K are close to one bet (MES and MNQ move together ~90% of the time);
  breadth comes from rates, metals, energy, FX and distinct mechanisms. **After version 1**, one
  economically different market (rates, gold or oil) is admitted to research and paper observation
  before any multi-market execution: two independent searches roughly double the chance of discovery.
- **One dated session deadline** per trading day: the earlier of **15:00 CT** and that day's early close.
  Every entry cutoff, entry-order expiry, the timed exit's release time (deadline − 5 minutes) and the
  flat check derive from it. Outstanding entry orders are cancelled before closing. (15:00 CT is before
  FundedNext's 15:10 CT and FTMO's 16:10 ET.)
- **Data:** historical minute bars per contract from **Databento**, capped at **$200**. Live data from the
  **IBKR CME subscription** (Databento live CME, ~$199/month, is not used). One normalization contract
  for both; Databento and IBKR bars are compared on overlapping days before paper starts, and
  continuously after. Research qualification uses actual contract prices; continuous series are never
  execution prices. Every order names the exact contract (conId, expiry).
- One session definition drives data, contract choice and permitted exposure in the backtester and the
  executor. UTC internally; Chicago time for schedules; clock-skew check.
- Bar size does not shorten the holdout: confidence grows with edge × √(independent bets), not with the
  number of bars.

---

## 9. Evidence

### 9.1 Research
On train + validation only, freely: walk-forward, sweeps, error analysis (validation exists exactly so
agents can learn why something failed and try again without touching the holdout). Required before
handing a row out:
1. Scored by the simulator (§9.3), at the row's own risk per trade with real costs.
2. **Random-entry control:** the same exit and sizing on time-matched random entries with the same side
   mix; the control is itself placebo-tested (a badly built random benchmark once made meaningless
   exits look like +0.8% per trade). Not beating it means no entry edge, whatever the win rate.
3. **Stability in research** (§9.6): parameter plateau and deletion survival on research windows.
4. **Prop-rule replay** at real size when a funded route exists (§11).
5. Deflated Sharpe, advisory.

**Sandbox (rules 1 and 7):** research agents may reach an allowlist of web idea sources; strategy code
they write executes with **no network**, no credentials, no write access to running code or signing
files, and **no read access to the trading database**.

### 9.2 Holdout (blind screen)
- Fixed window: the latest 2 years, sealed until incubation ends; then the newest 2 years are sealed and
  the old window becomes research data. No yearly rolling. Research seeds never use data inside the
  sealed window.
- Judged by a separate process (its own locked-down user: no logs, network or backups exposing sealed
  data) that alone reads the sealed files and writes only to the trading side; the strategy code runs
  unprivileged there too (rule 7).
- **Pass bar:** net profit after simulator costs at **5% one-sided**, with session-block statistics,
  beats random entries, and passes deletion survival (§9.6). Too few trades: **inconclusive**, never
  extended after seeing results.
- **Blind:** research never learns the result (rule 1), so no shot counts or caps are needed. **The owner
  sees pass / fail / inconclusive only, never the numbers**, and steers research only by broad themes,
  never in response to a specific result.
- **Leak monitor:** the dashboard shows the holdout **pass rate**; a rate well above what luck plus a
  plausible genuine share explains signals leakage.
- **Exact duplicates** (identical package hash) are rejected; any change is a new row and a new
  submission.
- **A pass earns paper observation only.** About 5% of zero-edge rows still pass; under illustrative
  assumptions only ~39% of passers are genuine. Sealing files cannot erase what papers or AI models
  already know about these markets; forward evidence is the real defence.
- Why 5%, not 1% with ≤10 candidates: at 500 holdout trades (SD 1.2R) a real +0.10R edge passes 59% of
  the time at 5% versus 32% at 1% (independent-trade approximation; session dependence lowers both).
  Astra's stricter alternative (batches of ≤10 families with a Holm correction, then new data) was
  rejected because it would exhaust the holdout after one batch.

### 9.3 The simulator (rule 2)
- Turns every signal into a **complete modeled position path**: entry eligibility, fills and non-fills
  (limit orders need the price to trade through), latency, slipped stops, fees, forced flat, and the
  worse outcome when a minute bar cannot order stop and target.
- Also runs the **desk policy**: which proposals the slot takes under the fixed priority, which are
  skipped, and the account limits. The desk is judged on this modeled stream, never on the sum of
  members that could not all have traded.
- Strategies decide from modeled state, so the simulator version is part of the row: a new simulator
  version makes **new rows**, deployed only through a quiescent signed package. Replaying old rows under
  the new version is diagnostic only; it never confers fresh qualification.
- **Calibration only on predefined mismatch:** at scheduled review points the audit compares real orders
  with the simulator; the simulator is recalibrated **only** if a pre-declared mismatch criterion is met.
  Otherwise the frozen simulator stays, so forward evidence keeps accumulating. Calibration data are
  never reused as confirmation; neither the freeze date nor the winning calibration may be chosen after
  seeing confirmation data.
- Scores backtest, holdout, paper and live signals identically. A signal traded on both paper and live
  counts once. Evidence keeps its label (train, validation, holdout, forward).
- **Audit:** every real live order attempt, filled or not, is compared with the simulator. First review
  after ~30 live attempts, then at scheduled points. A rescore can disqualify a strategy, never revive a
  retired one or raise its size. A large divergence stops new entries at once.

### 9.4 Paper
- **Parallel observation:** every holdout passer is observed by the simulator on live prices from the
  day it passes. There is no limit on how many rows are observed at once, and no row waits for another.
  Ten rows needing 100 sessions finish in 100 sessions, not 1,000.
- **IBKR paper account:** runs the same executor and the candidate desk policy to prove mechanics: every
  order resolved, protection in place, flat by deadline, restart and disconnect recovery. Paper fills
  themselves are not trusted (IBKR documents its paper simulator's limits). Paper keeps running
  alongside live.
- **Live step 1** after **≥10 clean paper sessions**, the commissioning run (§16.3) and the owner's signed
  desk package.

### 9.5 The desk, its admission and the statistics
**Unit.** Members propose; the desk decides. Real money is admitted, scaled and stopped for the **desk
policy**, scored by the simulator on fresh forward sessions with running costs charged once.

**Member checkpoint.** A row is considered for desk membership after **≥100 forward trades** after the
last calibration freeze, with its stability checks passing (§9.6). 100 trades is an information
checkpoint, **not a ticket**: a row joins only if the resulting desk still passes admission.

**Admission to real money** (signed desk package, while quiescent):
- the skeptical posterior supports **positive net dollars per month** for the desk after running costs;
  and
- the predicted probability of hitting the $1,500 drawdown halt within the next **20 sessions is ≤5%**
  (decision 17), under member dependence, +1 adverse tick on every entry and exit, and the stop-gap
  allowance.

**Step 1 (desk pilot):** one MES slot, **$600 loss budget**. $600 validates execution and the simulator,
not edge: 100 trades of a 1.8R-SD strategy swing about ±$900 at $50 risk.

**Scaling** (a second slot, more contracts, funded accounts): needs selection-controlled confirmation.
Each further slot also needs margin (§10) and its own commissioning; sizes above 1 contract per trade
need partial-fill protection designed and tested first. Size ≤ quarter Kelly on a skeptical edge
estimate, rounded down. **Slow up, fast down:** steps down and halts are automatic; steps up need
evidence and a signature.

**Leaving the desk.** An **anytime-valid economic futility test** (is the row's net expectancy credibly
below its hurdle?) and a **live decay alarm** (§9.6) remove a member at the next quiescent point; it
returns to paper observation. There is **no automatic retirement at 250 trades**: modest real edges need
600–1,000+ trades. A row is retired when futility rejects it or it is superseded. Statistics cannot
remove weak members cheaply (detecting −0.07R can take thousands of trades), so the checkpoint, not
futility, is the main filter.

**Selection.** Blindness does not solve selection: with 100 zero-edge submissions, a 5% holdout and a 20%
forward pass rate, there is a ~63% chance of at least one false promotion; repeated looks make it worse.
The protocol therefore has **one error budget for the whole pipeline**. Never scale the winner of a
batch without fresh confirmation.

**The statistics component spec — fixed before the evidence component is built (first spec of the build
plan), not left to the builder:**
- Estimand: **net dollars per session** for the desk and expectancy per trade for each row; a fixed
  overhead allocation that cannot improve by creating more rows.
- Joint session blocks across **all** rows, keeping overlapping signals, market correlation and serial
  dependence, including zero-trade days.
- Skeptical prior, likelihood, heavy-tail assumptions, look schedule and minimum information (not just
  trade counts).
- One selection-aware promotion rule: lifetime false-scaling probability **≤5%**, with error weights
  pre-allocated across candidates and anytime-valid tests within rows.
- The halt-probability model behind the 20-session target; holdout and control tests; the stability
  predicates (§9.6); calibration partitions; treatment of new simulator versions; the mismatch criterion
  that triggers recalibration.
- Pipeline simulations reporting false scaling, power, calendar delay, drawdown and dollars under zero
  edges, weak edges, concentrated profits, decay and model error, against numeric acceptance targets.

**One bet, not many:** rows on the same market with related mechanisms are not independent evidence. The
desk gets **no diversification credit at admission**; dependence is measured for the halt model
(effective independent bets ≈ N / (1 + (N−1)ρ); at ρ = 0.25, 20 members ≈ 3.5 bets).

### 9.6 Stability — the policy must survive pre-declared changes
One organizing rule: **qualify the declared policy under predefined perturbations, not only its fitted
path.** Every neighbourhood, block and regime is declared before results are seen.

| Check | Where | Rule |
|---|---|---|
| Parameter plateau | Research | Each tunable number ±20%: ≥80% of valid neighbours profitable after costs, and their median ≥50% of the chosen setting. |
| Deletion survival | Research, holdout, forward | Still profitable after removing the best 5% of sessions, and after removing any one quarter; profitable in ≥3 of 4 chronological blocks. Unsupported blocks = insufficient evidence. |
| Regimes | Research, holdout, forward | Volatility, trend and session slices and the strategy's trading domain declared in advance, using only information available before entry; deletion survival applies across sufficiently populated slices. A specialist need not profit outside its domain. |
| Cost stress | Before admission and scaling | Still above the hurdle with +1 adverse tick on entry **and** exit (+$2.50 per MES trade), at intended size. |
| Decay alarm | Live | A pre-declared one-sided CUSUM on session-level excess profit, aimed at deterioration to the hurdle, with ≤5% false alarms over 250 sessions. An alarm removes the member at the next quiescent point; paper observation continues. |

These rules deliberately reject some legitimate tail-dependent strategies (for example, a momentum idea
whose profit came from a few days).

### 9.7 ML strategies and model-derived features (later phases; rules fixed now)
- **ML: the row is the recipe, not the weights.** Features, model type, fixed hyperparameters, training
  window and the **retrain schedule** are hashed together. Holdout and paper run the recipe exactly as
  live would, retraining walk-forward on data available at each moment. All tuning happens in train +
  validation and every variant is a row. Same recipe + same data → same model (or within a stated
  tolerance on GPUs), verified by re-training a sample point.
- **Model-derived features (e.g. LLM text scores)** leak when the model can tell *who and when* **and**
  the task needs world knowledge. Classes: local task on anonymized input (eligible if it passes the leak
  probe); knowledge task (not holdout-eligible); point-in-time model trained only on pre-holdout text
  (eligible).
- **Leak probe:** score a sample of holdout-period texts raw and anonymized; **any** systematic
  difference reclassifies the feature (Glasserman & Lin 2023, arXiv:2309.17322, found outside knowledge
  distorts GPT sentiment in either direction; anonymization helped).
- **Models with an unverifiable training cutoff** (hosted, closed models such as TypeSafe AI's "Jev"
  System One) qualify **only through forward paper evidence**, never the holdout.
- **Frozen score cache:** every text is scored once and stored immutably with model version and input
  hash; backtest, holdout, paper and live read the cache; a new model version means a new row. Losing the
  vendor means the strategy leaves the desk safely.
- Historical point-in-time news is a separate later data purchase; text strategies wait until after the
  first price-based edge.

---

## 10. Capital and risk (rule 6)

- **Incubation budget:** **$15,000 maximum cumulative net loss through 2028-12-31**, counting trading
  losses, fees, funded fees and running costs. Reaching it halts all trading and opens a thesis review
  (§19). Reserved: ~$3,750 operations (25 months at $150), $1,000 funded fees, $200 data, leaving
  **~$10,050** for trading losses.
- **Account funding:** the live account holds enough cash for the desk's slots at IBKR's current margin
  plus a stress reserve (at least IBKR's $2,000 minimum equity); deposits stay within the $15,000
  ceiling. Margin cash is not spent budget. IBKR's published intraday MES margin is about **$2,000 per
  contract** (indicative, not an account quote; full overnight ~$2,900–3,200), so the incubation can carry
  **about four simultaneous MES trades at most**; version 1 uses one. Margin is per contract whatever the
  stop distance.
- **Risk per trade:** chosen per strategy within **$20–$50** including stressed costs; the member's cap is
  part of the desk package. Limits trigger action; fast markets, halts and limit moves can jump past them.
- **Account rule (rule 6):** an order is admitted only if the stressed post-fill account state stays above
  today's start −$400, peak −$1,500 and the incubation floor, and within margin. Pending orders count.
  Daily −$400: no entries, flatten. **Halt at $1,500 below peak**, restored only by signed approval. $600
  desk-pilot budget at step 1. All from marked equity; peaks survive restarts and are not reset by
  deposits or new packages. (At $50 risk the halt is 30 full losses; at $20, 75.)
- **Quiet period:** from **2027-06-01 to 2027-08-31** no new deployments, step-ups or funded purchases. The
  running desk continues with its automatic limits, including the rolls its package already authorizes.
  This can delay a qualified desk by up to three months; that cost is accepted.
- **Restore:** a restored installation starts disarmed (rule 5); backups never carry trading authority,
  unused approvals or a lifted halt.

---

## 11. Funded accounts (a later, separate qualification)

- **Verified (Nov 2026):** FTMO Futures and FundedNext Futures allow bots and a VPS, don't restrict
  Israeli residents, require flat by end of day, and run on NinjaTrader / Tradovate / TradingView.
  Tradovate's API excludes prop accounts. Topstep's API needs a personal device (poor fit; home rig
  rejected — an outage near the close breaches the account). Apex and Take Profit Trader ban bots.
  Tradeify restricts Israel. DayTraders.com and MyFundedFutures allow bots. FTMO Swing (multi-day) is
  CFDs with financing costs — rejected.
- **Funded rules punish long losing streaks.** Codex's simulation of FundedNext 50K Rapid at equal +0.20R
  and $400 risk: a 30% win / +3R profile reaches the first payout ~22% of the time vs ~94% for
  80% / +0.5R. A zero-edge strategy passes a Topstep-style challenge ~40% of the time (Topstep 2025:
  16.8% pass, 33% of funded traders paid). **A pass is a payout bet, never evidence.**
- **Stage 0 (ours, by 2027-01-15):** research the exact route (API bridge, then TradingView, then manual),
  hosting, residency, payout and KYC; test a route on an evaluation account. No funded code in version 1.
- **First challenge** only when the desk (or the strategy routed) passes the **selection-controlled
  confirmation and stability bar** (§9.5–9.6) **and** ≥50 real IBKR trades over ≥20 sessions with clean
  reconciliation and the simulator audit passing (real costs inside the model at 90% confidence). Fifty
  trades alone prove execution, not edge. The route must qualify on its own (platform, automation
  permission, exact rules). Once a desk is confirmed, funded may come **before** adding personal
  contracts.
- One challenge at a time, ≤$150 each, ≤$300 before the first payout, **$1,000 total** including renewals
  and resets; no automatic retries or parallel copies until a payout is collected. Buy only if replay
  under the firm's exact rules shows expected payouts ≥2× all fees after halving the payout estimate.
  Optimise expected payout, not pass rate. Each firm's rulebook (trailing drawdown, daily loss, close-by
  time, contract limits) is data replayed in research.
- Payouts are not brokerage money: firms can void payouts and change terms.

---

## 12. Approvals and authority

- **Signed desk packages** (SSH signature from the phone; passkey later) are required for: go-live,
  membership changes, step-ups, funded purchases, limit restorations after a halt, and payments. Each
  package names the exact executable identity, account, limits, expiry and a one-time number; replay is
  refused. Signer anchors live outside the agent-writable tree.
- Owner one-tap merge approval (no code reading) only for changes to the executor boundary, risk limits
  and signer anchors. All other agent-reviewed changes merge on their own.
- Agents operate everything else autonomously: research, holdout submissions, paper observation, desk
  simulation, proposals of desk packages, halts and risk reductions.
- Runtime evidence (logs, broker messages, market data, web text) is data, never instructions granting
  permissions.

---

## 13. Ideation and research operations

**Discovery is the slowest step.** About 1 in 13 distinct submissions passes the holdout, so 5–20 passers
need roughly 65–260 genuinely different ideas (at ~10 distinct submissions a month: 6–26 months). Research
therefore favours:
- **distinct mechanisms** ("who loses money to us, and why") over variants;
- mechanisms delivering **net dollars and independent information per session** (several uncorrelated
  trades a day lower the running-cost hurdle from 0.15R to 0.05R); repeated bets on the same move do not
  count.

**Admission checks (mechanical, not taste):** stated mechanism, expected direction and horizon,
data-feasible with timestamped coverage, and a **duplicate screen on signal values** (correlation of the
new signal's values with existing ones on train data, sign-flip aware; ~0.8 is a flag, not a hard gate).
An LLM judging "quality" favours familiar ideas, so filters stay data-driven.

**Provenance on every idea:** source (paper, blog, owner Inbox, agent-originated), the source's
publication date, the pinned model that developed it, and its class (pre-holdout, post-holdout,
agent-originated). Once enough forward evidence exists, compare forward decay by class to measure LLM
knowledge leakage; act on the measurement, not on a guess.

**Allocation (bandit, after version 1):** equal rotation across categories and source types until each
has ~10 completed pulls, then Thompson sampling with a cap on outstanding pulls per arm and a randomized
exploration floor. Rewards use **research-window outcomes only** (never holdout, paper or live — rule 1),
mostly from validation contribution; credit goes only to components that helped, measured by removal
tests (which are themselves rows). Failures are classified: economic failure is penalized; missing data,
infrastructure errors or "never tried" are not. The Inbox has a bounded priority queue. The existing
idea scorecard must stop reading gate outcomes.

**Every evaluated variant, combination, weighting and transform is a row**, so the table itself is the
count of everything tried. A data wishlist ranks data purchases by distinct experiments unlocked,
point-in-time feasibility and cost.

**First research batch:** MES open-to-close continuation with one fixed stop and target, against random
entries. Seed from the Algovibes review: the Zarattini/Aziz/Barbon (2024) noise-band intraday momentum
(survived its random-direction control on NQ only, 1,564 trades, 41% win rate; failed on S&P, Dow and
Russell; profit concentrated in a few days, so it must pass deletion survival; its −$3,601 drawdown on one
micro would breach a $2,000 funded trailing limit), retested on **MES research windows only**, with a
daily-stop variant. Other markets wait until after version 1.

**Agent runtime:** research agents run through OpenCode via the single invocation seam
(`.opencode/scripts/run_agent.sh`); the owner steers through the category list and the source registry.

---

## 14. Payoff shape — what exits can and cannot do

- Stops, targets and trailing stops **reshape** results; on an unpredictable path they cannot create
  expectancy, and costs make it negative (a −1R stop / +3R target hits the target ~25% of the time on pure
  noise). Hence the random-entry control.
- **Costs do not shrink with the stop:** ~$3.70 per MES round trip is ~7% of a $50 risk but ~19% of a $20
  risk.
- Low-win-rate trend strategies are allowed on the personal account; funded accounts favour smooth equity.
  At a 30% win rate, confirming +0.2R needs ~320–520 independent trades.
- Leaderboards (Myfxbook, MQL5, Collective2, TradingView) show survivors; they are idea sources, never
  evidence (in a complete Taiwan dataset fewer than 1% of day traders reliably beat fees).

---

## 15. Operations and owner surfaces

- **Phone:** push alerts (weekly IBKR login needed, limit hit, mismatch, program down) and signing.
- **Dashboard** (existing `web/` PWA over the JSON CLI): desk state and P&L, marked equity vs floors,
  monthly operating cost next to P&L, holdout pass rate (leak monitor), paper observation progress, Inbox.
  No holdout numbers.
- **Command line:** every action is a JSON command, for agents and the owner (kept from today).
- **Unattended operation:** systemd, execution lock, outside heartbeat, off-server backups with tested
  restore; full reconciliation after restarts, the daily reset and the weekly login. Target 72 hours
  unattended or a predefined safe state.
- **Self-repair (later):** incidents become deduplicated issues with reproduction, regression test, minimal
  fix, independent agent review and verification; prefer fixes that remove states and special cases.

---

## 16. The system

### 16.1 Components (version 1)

| Layer | Parts |
|---|---|
| Outside | IBKR (paper + live accounts), market data, the owner's phone |
| Trusted (holds the keys) | **Executor (desk):** tiny; receives validated proposals from all members, picks by the package's fixed priority when the slot is free, applies the account rule, sends orders with protection, journals, reconciles. Same code for paper and live. |
| Unprivileged | **Strategy worker** (runs every member's code; no network, credentials or database writes) · **Backtester** (research sandbox) · **Holdout judge** (reads only the sealed files) · **Paper observer** (simulator-scores every holdout passer on live prices) |
| Core (pure functions) | Strategy interface (closed bars → proposal with stop and target) · **Simulator** (rows and desk policy) · **Account rule** (stressed post-fill, marked equity) · **Evidence statistics** (§9.5–9.6) |
| Storage | Parquet price files (train / validation / sealed holdout) · one SQLite database (trading side only; research can't read it) |
| Control | JSON command line, systemd, execution lock, outside heartbeat, off-server backups with tested restore |

Version 1 scope: **one desk with one MES slot, many observed rows, one IBKR account, fixed stop and target
per trade.** IBKR client library: `ib_async`. Deferred: a second slot and simultaneous trades, trailing
stops, sizes above 1 contract, Kelly sizing, the idea bandit, funded executors and fixtures, multi-market
research, ML and text features. Deleted: per-strategy accounts or budgets, multi-account coordination, a
separate watchdog engine, the old gates and ceremonies.

### 16.2 The executor loop
- Each minute: read the bar and IBKR's positions and orders → strategy worker returns every member's
  proposal → if the slot is free and nothing is unresolved, take the highest-priority valid proposal →
  account rule → send one order package with protection → record. Skipped proposals are recorded as
  skipped, matching the simulator.
- Also reacts instantly to broker events (fills, rejections, cancels, disconnects) and to a timer, so a
  rejected stop is noticed in seconds, not at the next bar.
- **Order journal** (rule 3): intent ID written before sending; broker IDs; deduplicated executions;
  commissions. IBKR's state alone cannot tell "nothing happened" from "entry and stop both filled", and
  IBKR reports positions per account and contract, not per strategy, so episode ownership comes from the
  journal.
- **One execution episode** owns all its orders until each is resolved; unresolved submissions block new
  entries; a real stop-out ends the episode and is never "replenished" toward the modeled target.
- Protection is never modified while exposed (rule 4). Every close, including the daily-limit flatten and
  a strategy's flat target, is a market order joined to the episode's exit OCA group.
- Manual changes or broker liquidation: block entries, alert, and keep owning the episode until every
  child order is terminal (cancel orphaned exits once the position is confirmed zero); never undo a manual
  flatten.
- After restarts, the daily reset and the weekly login: full reconciliation before trading resumes.

### 16.3 Protection at IBKR (rule 4)
- **Construction, verified on paper in week 1:** entry parent plus three opposite-side children (stop,
  limit target, market order with Good-After-Time = that day's deadline − 5 minutes) sharing `parentId`
  and one exit-only OCA group in "block" mode; the final child transmits. Never put the entry in the exit
  group. Confirm every leg is acknowledged, the dormant timed child doesn't interfere, and rejections and
  cancels behave (a rejected member does not cancel the others). Also prove the **forced-close protocol**:
  a market order joined to the same OCA group closes the position and cancels the resting stop and target
  without ever reversing it, including existing fills, pending cancels, delayed acknowledgements, a
  rejected child and a gateway outage. Block mode protects only within one group; it is not account-wide
  protection. (IBKR documents each piece — TimeCondition, GAT, OCA, brackets — but not this exact
  combination on CME micros; GTD only expires an order, it does not flatten.)
- **Commissioning run:** paper cannot certify production behaviour, so before unattended operation a short,
  signed, owner-aware run on the live account at 1 MES confirms the same construction live. A second slot
  needs its own commissioning.
- **Fallback:** ordinary bracket plus an executor-sent timed close, which loses crash-proof timed exits. It
  remains a **live blocker** unless the owner explicitly accepts it in a signed decision.
- Nothing executes during a market halt.

### 16.4 Edge cases (minimal fixes)

| Group | Fix |
|---|---|
| Orders and fills | 1 contract (exits activate only after a full fill); blocked OCA; one episode owns its orders; one slot in v1, so no opposite-side overlaps; never replenish after a stop-out |
| Surprises at the broker | Whole-account check; unexpected state blocks entries and alerts; never undo a manual flatten |
| Competing proposals | Fixed priority in the package; skipped proposals recorded identically by simulator and executor |
| Data and clock | Stale or missing bars block signals, never exits; validate timestamps, duplicates, gaps; next-bar execution (`t → t+1`); Databento vs IBKR overlap checks |
| Session deadline | One dated deadline drives cutoffs, expiries and the timed exit; early closes included |
| Contract rolls | Exact contract on every order; chosen at session start; switched only while quiescent; no trading near expiry |
| Fast markets and margin | Per-member risk cap; stressed account rule with gap allowance; margin checks before entry and while holding; funded margin reserve; limits are triggers, not guarantees |
| Program and server | Execution lock; one armed executor; broken database stops entries (IBKR holds exits); tested restore |
| Evidence | Simulator models non-fills, full paths and the desk policy; whole-policy replay; calibration ≠ confirmation |
| Code and secrets | Strategy code unprivileged (rule 7); holdout judge locked down; packages signed with expiry and one-time number |

### 16.5 Safety tests before the first real order
1. **Crash anywhere:** kill the executor before, during and after sending, and mid-trade; shut down the
   gateway through the timed exit. Nothing duplicates; the position stays protected and is flat on time.
2. **Exits and races:** stop/target/timed exit together, a daily-limit flatten while the stop rests, a
   manual flatten leaving orphaned exits, rejections, an outstanding entry at the deadline, an early-close
   day. Never overfill or reverse; never replenish after a stop; rejections block and alert.
3. **Same decisions:** identical bars into backtester and executor across gaps, a roll and a DST change;
   two members proposing in the same minute resolve by priority identically in simulator and executor; a
   simulator change replays the whole policy exactly; unfilled and skipped attempts are kept.
4. **Limits, boundaries and backups:** restart after a losing day; a pending entry that would breach a
   floor under stress is refused; deposit without resetting peaks; restore an old backup (starts disarmed;
   no old approval, halt-lift or peak comes back); a second installation tries to trade; replay an old
   approval; edit a limit or membership unsigned; strategy code returns an invalid proposal, hangs, or
   tries to reach the network, credentials or database; research tries to read a holdout or desk result.
   All refused or preserved.

---

## 17. Build plan

About **3 weeks to a paper prototype with two agents** (history side, broker side); unattended live
follows the commissioning run, not the calendar. Specs come first: modules have been weakly specified
before, and that hurt results.

- **Before/alongside week 1:** the **statistics component spec** (§9.5) — written, simulated under
  zero-edge and weak-edge pipelines, and reviewed before the evidence component is coded.
- **Week 1:** broker side starts day 1 with the IBKR protection construction (§16.3) and phone signing;
  history side builds Databento data, normalization and the simulator; research starts on history.
- **Week 2:** executor (desk with one slot) and strategy worker on IBKR paper with one fixed
  stop-and-target strategy; paper observer for all holdout passers.
- **Week 3:** the four safety tests, then paper trading.

**Build rules:** the stock lane may break; the empty research registry may be reset after archiving.
Small runnable slices with focused checks; agent review; parallelize what is parallelizable against
frozen shared interfaces, with planned integration. Keep sandboxing, reconciliation and recovery in the
first slice. Kept from today: the JSON CLI contract, SSH signing, the `t → t+1` rule, and the recovery
principle of `algua/execution/live_ledger.py` (not its Alpaca assumptions).

---

## 18. Timeline

| When | Stage | Money at risk |
|---|---|---|
| Dec 2026 – 15 Jan 2027 | **0. Verify:** cut cost; measure VPS/LLM spend; our own funded-route research; open and fund the IBKR futures account and data | None |
| Dec 2026 (~3 weeks) | **1. Build** to a paper prototype (§17); statistics spec first; research on history from week 1 | Data ≤ $200 |
| Jan 2027 | **2. Paper** (≥10 clean sessions) → commissioning run → **desk pilot** if a desk passes admission | $600 desk pilot |
| Feb – May 2027 | **3. Discovery and parallel forward evidence;** desk membership grows by signed packages | Within account limits |
| Jun – Aug 2027 | **Quiet period:** no new deployments, steps or purchases | Running desk only |
| Sep 2027 – Dec 2028 | Confirmation; second slot, funded and more contracts on evidence; second market in research | Within the $15k budget |

No date lowers a bar.

---

## 19. Thesis review (when to stop)

Opens automatically at the first of: the incubation loss budget is reached; **12 months after paper
starts** with no desk passing admission (a fixed observation deadline, not a submission count);
**2028-12-31** without a live desk above its hurdle. It ends in one recorded decision: change approach,
change scale, or stop. **Adding features is not an allowed outcome.**

---

## 20. Migration from today's repository

- **Daily stock lane: frozen.** Timers and paid stock data (Sharadar) stop; code deleted later if unused.
- The old gates (`paper promote`, forward certificates, `forward_tested`, the 63-bar holdout floor and
  63-session forward gate, capped-route ceremonies, `dormant`) are removed once the new core enforces its
  rules; until then they stay as the operating guides describe.
- **Old research results are archived to the owner's Drive** and removed from every agent-reachable place:
  KB run reports and family notes, MLflow runs, idea-pool recorded outcomes, VPS research records. Ideas
  themselves may be re-researched from scratch. Research worktrees are shallow so git history is not a
  direct path back. This is "no direct path", not a sealed wall; forward evidence is the backstop.
- Verified on the VPS on 2026-11-20: zero strategies in the registries; no paper/live operator units; only
  paper broker credentials. Re-check immediately before cutover.

---

## 21. Superseded — do not resurrect

Agents will meet these in old docs, code and history. They are **replaced**:

| Old idea | Replaced by |
|---|---|
| Daily long-only US stocks, Alpaca, Sharadar, SPY/equal-weight alpha benchmarks | Intraday CME micro futures on IBKR (§1, §8) |
| ₪ amounts; ₪2k→₪10k ladder; $600→$3,000 per-strategy ladder; ₪50k/₪200k and $15k/$60k ceilings | $15k incubation loss budget, desk admission, slow-up/fast-down (§9.5, §10) |
| 63-session paper gate, forward certificates, `forward_tested`, `passed_holdout`, `dormant`, "probation", "freeze", "shadow", "pilot" stage | research → holdout → paper → live → retired; insert-only rows (§5) |
| Lifetime trial counter N=500, t≈3.72 Bonferroni, deflated-Sharpe pre-screen as a gate, sliding holdout, Holm batches of ≤10 | Blind fixed 2-year holdout at 5% as a screen; selection handled by one pipeline error budget (§9.2, §9.5) |
| 97.5% funded trigger; "not falsified + time" ladder; 70% confidence pilot | Desk admission + selection-controlled confirmation; funded after confirmation + 50 real trades (§11) |
| Kill at 20% after 60 trades / retire at 250 trades | Anytime-valid futility + CUSUM decay alarm (§9.5–9.6) |
| One strategy live at a time; serialized observation | The desk; parallel paper observation (§9.4–9.5) |
| Independent strategies each with a daily risk budget | One executor owns the account; stressed post-fill account rule (§6 rule 6) |
| Fixed ~$50 risk per trade | $20–$50 chosen per strategy (§10) |
| Calendar recalibration at every month end | Recalibration only on a predefined mismatch (§9.3) |
| TOTP / password approvals; per-step passkey ceremonies | SSH-signed desk packages; passkey later (§12) |
| Funded go/no-go requiring written firm confirmation; home rig | Our own route research and fallbacks (§11) |

---

## 22. Claude's calls for the owner to check

1. Incubation budget $15,000 cumulative net loss through 2028-12-31, including running costs and fees.
2. Daily loss $400; halt at $1,500 below peak.
3. ~~Risk per trade $20–$50~~ — confirmed by the owner 2026-11-26 (decision 16).
4. ~~$600 for the desk pilot~~ — confirmed by the owner 2026-11-26 (decision 6).
5. Funded fee cap $1,000; one challenge at a time; ≤$150 each.
6. Session deadline: the earlier of 15:00 CT and the early close.
7. Live data from IBKR; history from Databento ≤ $200.
8. Holdout bar 5% one-sided; member checkpoint at ≥100 forward trades; anytime-valid futility and a CUSUM
   decay alarm instead of the 250-trade expiry; lifetime false-scaling ≤5%.
9. Stability thresholds: ±20% plateau with 80%/50%; best-5% and any-quarter deletion; 3 of 4 blocks;
   +1 tick each way.
10. Stage derived from evidence rather than stored.
11. Owner one-tap merge approval only for the executor boundary, risk limits and signer anchors.
12. Stock lane frozen and allowed to break; empty registry may be reset after archiving.
13. SSH signing first; passkey later.
14. Version 1: one slot, fixed stop and target; a second slot, trailing stops and sizes above 1 contract
    are deferred.

---

## 23. Approaches considered

| Decision | Chosen | Rejected and why |
|---|---|---|
| What the system is for | Intraday futures for funded payouts | Daily stocks: can't make the owner rich at $15k; FTMO Swing CFDs: financing costs, thin list |
| Architecture | Lean new core, tiny trusted executor, broker-held exits | Refactor of the stock platform; Astra's first design (too slow, too much machinery) |
| Code authority | Strategy code unprivileged; only proposals cross (rule 7) | "Pure functions" inside the credentialed runner: unenforced |
| Holdout leakage | Blind holdout (rule 1) | Per-idea shot counts; ≤10 candidates at 1% (rejects about half of real +0.10R edges that pass at 5%); Holm batches |
| Paper vs live evidence | One simulator scores every signal and the desk (rule 2) | Separate scores; paired gap adjustments |
| How many strategies trade | **The desk:** many members, one executor, one slot first, the desk qualifies as a whole | One strategy live at a time (serializes evidence and income); independent strategies each with its own daily budget (the owner's first proposal; Astra's pool review found margin fits only ~4 MES, the $1,500 halt binds long before the daily budget, netted strategies can leave a working stop that opens an unmanaged position, and unscreened pools halt ~65% of the time) |
| Entry to real money | Parallel paper observation, 100-trade checkpoint, desk admission with a ≤5% 20-session halt target | Every holdout passer trades (only ~39% genuine; nulls bleed ~$3.70 a trade) |
| Risk per trade | Per strategy, $20–$50, real costs charged | Fixed $20 (costs eat ~19% of R; loses money in simulation unless the edge per R is larger); fixed $50 |
| Retirement | Anytime-valid futility + decay alarm | Fixed 250-trade expiry (discards modest real edges) |
| Execution truth | Broker state + small journal + one episode | Broker state alone (ambiguous after downtime); full order framework |
| Exits | Entry × exit × sizing with a random-entry control | Exit tuning alone: cannot create edge |
| Funded route | Our own research; API → TradingView → manual | Waiting on firms' confirmation; home rig for Topstep |
| Stages | Research → holdout → paper → live (ladder) | Separate pilot and funded stages; a "freeze" step |
| Personal broker | IBKR with a weekly login | Tradovate API (unverified for unattended use); Alpaca (no futures) |
| Holdout window | Fixed 2 years, refreshed once at incubation end | Yearly rolling (overlap, not a clean retest) |

---

## 24. Next steps for the implementing agent (in order)

1. **Context sweep:** update `CLAUDE.md`, `AGENTS.md`, `README.md`, `docs/architecture.md`,
   `docs/agent/*`, `.opencode/*` (skills, categories) and comments citing old PRD sections, so they point
   to this PRD, adopt its vocabulary and seven rules, and mark unbuilt items as targets. Present
   permissions stay as enforced until the new core replaces them.
2. **Build plan** (superpowers:writing-plans) with the **statistics component spec first**, then the
   week 1–3 slices (§17).
3. **Todoist (Algua board):** retire old-route and stock-lane cards; add Stage 0 and build cards in §18
   order (including: measure VPS and LLM spend; funded route research; IBKR account and data).
4. Stage 0 tasks in parallel (§18).

---

## 25. Left to the builder

Exact simulator parameters per contract, the stop-gap allowance, roll timing, module layout, schema and
test fixtures, each fixed in its component spec and covered by tests. Funded rule-set fixtures
(FundedNext 50K Rapid first) wait for the funded milestone. The evidence statistics are **not** left to the
builder (§9.5).

---

## 26. The standard

Algua succeeds when it discovers edges we did not already know, judges them honestly, turns the validated
ones into controlled positions, detects when its trading or its software is failing, needs little routine
human attention, and converts that into growing real-world capital and net profit.

**Make money. Preserve knowledge. Control risk. Automate everything else.**
