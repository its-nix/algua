# Vision refresh — intraday futures for funded payouts

**Status:** Approved by the owner 2026-11-22 (revision 5) · **Owner:** Lior Nisimov
**Origin:** owner design session, 2026-11-16 → 2026-11-22, with Codex, Grok and Codex Astra reviews
(debate on futures, prop-rule simulation, two hostile reviews, five architecture reviews). Revisions
4 and 5 apply Astra's reviews of revisions 3 and 4 (both "approve with fixes").
**Companion diagram:** the "Algua Data Flow" artifact (private) shows the same design visually.
**Supersedes:** revision 2 (commit `5e6d116`) and the 2026-11-19 daily-stock draft (`1bbae69`).

This document records owner decisions that amend the [PRD](../../PRD.md). Once approved, the PRD,
operating guides and agent instructions are updated to match (§15). Until the code below is built and
accepted, operating guides keep describing what the code enforces **today**. Items marked *(call)*
were settled by Claude and can be overridden by the owner (§16 lists them).

---

## 1. Intent

**North star: make the owner rich from trading profit, as soon as honestly possible.** The owner is a
capital allocator, not a reviewer: no human code review, no recurring decisions, one-tap signed
approvals only where real money requires a human.

The binding constraint is capital, not ideas. Funded prop accounts give $50k–150k of trading size for
a fee, and every verified bot-friendly firm requires being **flat by the end of the trading day**. So
Algua is an **intraday CME micro futures system**. Paper and the personal IBKR account produce the
**evidence**; funded accounts are a later **multiplier** on the same strategy. A funded pass is never
evidence.

### Goals
- Find intraday futures edges that survive realistic execution, judged on data research never saw.
- Optimise **net dollars per trading session after running costs**, not pass rates or attractive
  reward-to-risk ratios.
- Keep the system small enough to reach paper trading in about three weeks and run unattended.
- Keep every loss limit in code and at the broker; grow size only on evidence.
- Operating cost near **$150/month**.

### Non-goals
- Daily or multi-day stock trading (lane frozen, §13). Spot forex, options, crypto.
- Proving an edge by a deadline. No date lowers a bar.

### Anti-goals (failure even if it "works")
- Scaling the luckiest of many experiments.
- Treating backtests, leaderboards, holdout passes or challenge passes as proof.
- Machinery that manages a problem when one rule could prevent it (§3).
- Research-written code with any authority over money.
- Hidden-risk strategies (martingale, grid, averaging down, no stop).
- Anything needing routine owner attention beyond the weekly broker login.

---

## 2. Owner decisions

1. Operating cost ~$150/month.
2. **Pivot:** Algua is built for intraday futures aimed at funded payouts; a **lean new core** replaces
   the old machinery rather than refactoring it.
3. Research searches **entry × exit × sizing** (stops, trailing stops, targets, reward-to-risk, win
   rate) under the honesty rules in §6.
4. **Flat by end of day** for every strategy, for now.
5. **Personal broker: IBKR**, with a weekly login.
6. **Live step 1 loss budget: $600 per strategy.**
7. **No funded route → personal futures only.**
8. **Stage 0 is our own research** of funded routes; we don't wait on firms. Fallbacks in order:
   API bridge → TradingView → the owner sends orders by hand (last resort).
9. Stages: **research → holdout → paper → live → retired.** "Paper trading" replaces "shadow".
   Pilot and live are one stage, **live, with a ladder**. Funded is an extra account of a live
   strategy, not a stage.
10. **A strategy is an insert-only row;** evidence is appended immutably. Any change, including a
    single parameter, is a new row (no separate "freeze" step).
11. **The holdout stays,** as a blind screen (§6.2).
12. **The design lens (§3):** one structural rule instead of counters, ledgers, caps or adjustments.
    In particular: research never sees holdout results, and every trade is scored by one simulator.
13. Code is generic, clean where it matters, and as simple as possible.
14. USD everywhere; the owner approves every payment.

---

## 3. The seven rules

Each rule replaces a set of special cases with one behaviour. A rule **prevents** a class of failure
by construction where it can and **reduces** it where it can't; the table says which.

| # | Rule | What goes wrong without it | Precise meaning and limits |
|---|---|---|---|
| 1 | **Information only flows outward.** Research hands rows out through a one-way mailbox and never receives anything back: no holdout result, no paper/live numbers, no hint of which strategies trade. | Research tweaks a failed strategy and resubmits; a zero-edge idea retried 20 times passes a 5% test ~64% of the time. | Prevents feedback-driven tuning. Does **not** prevent luck: of 20 independent zero-edge rows, ~64% of the time at least one passes. So a holdout pass earns paper observation only (§6.2). The **only** channel back is the global simulator version (market-wide cost parameters, never strategy-specific results). Logs, agent memory and maintenance work keep strategy outcomes out of research. |
| 2 | **Evidence is calculated, never hand-entered.** One simulator turns every signal into a full modeled trade; every score is derived from it. | Separate paper and live scores with a correction between them. | Prevents inconsistent scoring, not model error. There is **one canonical modeled episode stream** per row; real execution may skip an episode (e.g. while blocked) but never invents or repeats one, and each episode is scored once. Trades used to calibrate the simulator are never counted as confirmation. |
| 3 | **If anything is uncertain, no new entries.** | A crash after sending a buy leads to a second buy: 2 contracts, protection on 1. | **One execution episode owns every order, entries and exits, until every child order is terminal**, even after the position is closed (a stray sell must not open a short). The executor never sends a second exit while one's outcome is unknown and never re-enters to replace a position that was actually stopped out. |
| 4 | **Every open position has protection held at IBKR,** sent in one package with the entry, and **never removed while exposed.** **Every close goes through the episode's single exit authority.** | A server crash or a cancel-then-replace gap leaves a position unprotected; a separate "sell now" races the resting stop and reverses the position. | Stop, target, timed exit, daily-limit flatten, strategy flat and manual close all act **within the episode's exit OCA group** (a forced close is a market order joined to that group). Version 1 uses a fixed stop and target and never modifies them. Proven in week 1 and at commissioning (§11.3); nothing executes during a market halt. |
| 5 | **Change only while quiescent.** Go-live, new versions and size steps happen only with **zero positions, zero working orders and zero unresolved submissions**, under the execution lock. | A waiting order fills just after a new version starts; a restored second server trades alongside the first. | Each change is one signed, immutable package covering the complete executable identity (code, dependencies, settings, simulator version, account, contract family and roll schedule, limits). Scheduled rolls inside an active package happen while quiescent without a new signature. **One active executor:** a new or restored installation starts **disarmed**, fences the previous one, reconciles history and needs a fresh signed activation; trading authority is never restored from backup. |
| 6 | **Real money sets the limits.** Loss limits, margin and funded drawdowns use **marked account equity**: actual fills, open positions at current prices, accrued fees, adjusted for deposits and withdrawals. | The simulator says −$300, slippage made it −$450, and the $400 limit never fires. | Deposits and futures settlement never reset loss budgets or peaks. Budgets and peaks belong to the account and the incubation, not to a row, deployment or approval, so none of those resets them. A stale mark blocks new entries and alerts. Simulated numbers only judge strategies. |
| 7 | **Only answers cross into the executor.** Research-written strategy code runs unprivileged (no credentials, no network, no database writes); only its validated target crosses into a tiny trusted executor that holds the keys. | A buggy or malicious strategy touches the broker or the signing files. | **Validation contract:** side ∈ long/short/flat; finite, tick-aligned prices; stop on the correct side; approved contract; risk ≤ the package cap; fresh episode ID. Anything else is rejected and blocks entries. The worker runs under a timeout and resource limits; it can never delay the executor's exits. |

What the rules do **not** remove: loss totals and equity peaks, fees, margin, approval replay
protection, the order journal, and the safety tests. Where possible these are calculated from recorded
facts rather than tracked separately.

---

## 4. Vocabulary and lifecycle

| Word | Meaning |
|---|---|
| **strategy row** | Code + settings + simulator version, hashed. Insert-only; any change, including a new simulator version, is a new row. |
| **research** | Building and tuning on train + validation history, in a sandbox. |
| **holdout** | One blind test per row on a sealed 2-year window. A screen, not proof. |
| **paper** | The row runs on the IBKR paper account: real order handling, no money. Proves mechanics and gathers cheap forward evidence. |
| **live** | The row trades real money on IBKR, on a ladder of sizes. |
| **deployment package** | One signed, immutable bundle: complete executable identity, account, contract, limits, expiry, one-time number. |
| **halted** | A deployment stopped by a limit; it can resume only through a new signed package. |
| **retired** | Terminal. A retired row never trades again; a revised idea is a new row. |

`idea → research → holdout → paper → live → retired`. The stage is **derived** from the row's appended
evidence and active deployment, not stored as separately managed state *(call)*.

---

## 5. Markets and data

- **Instruments:** CME micro futures. Version 1 trades **MES only**; MNQ, M2K, MYM, MGC, MCL and micro
  rates/FX follow. MES/MNQ/MYM/M2K are close to one bet; breadth comes from rates, metals, energy, FX
  and distinct mechanisms.
- **One dated session deadline** per trading day: the earlier of **15:00 CT** *(call)* and that day's
  early close. Every entry cutoff, entry-order expiry, the timed exit's release time (deadline − 5
  minutes) and the flat check derive from it. Outstanding entry orders are cancelled before closing.
  (15:00 CT is before FundedNext's 15:10 CT and FTMO's 16:10 ET.)
- **Data:** historical minute bars per contract from Databento, capped at **$200**. Live data from
  the IBKR CME subscription. One normalization contract for both; Databento and IBKR bars are compared
  on overlapping days before paper starts, and continuously after. Research qualification uses actual
  contract prices; continuous series are never execution prices. Every order names the exact contract
  (conId, expiry).
- One session definition drives data, contract choice and permitted exposure in the backtester and
  the executor. UTC internally; Chicago time for schedules; clock-skew check.

---

## 6. Evidence

### 6.1 Research
On train + validation only, freely: walk-forward, sweeps, error analysis. Required before handing a
row out:
1. Scored by the simulator (§6.3).
2. **Random-entry control:** the same exit and sizing on time-matched random entries; the control is
   itself placebo-tested. Not beating it means no entry edge, whatever the win rate.
3. **Prop-rule replay** at real size when a funded route exists (§9).
4. Deflated Sharpe, advisory.

**Sandbox (rule 1, rule 7):** research agents may reach an allowlist of web idea sources; strategy code
they write executes with **no network**, no credentials, no write access to running code or signing
files, and **no read access to the trading database**.

### 6.2 Holdout (blind screen)
- Fixed window: the latest 2 years, sealed until incubation ends; then the newest 2 years are sealed
  and the old window becomes research data. Research seeds never use data inside the sealed window.
- Judged by a separate process that alone reads the sealed files and writes only to the trading side;
  the strategy code runs unprivileged there too (rule 7).
- **Pass bar:** net profit after simulator costs at **5% one-sided**, with session-block statistics,
  and beats random entries. Too few trades: inconclusive, never extended after seeing results.
- **Blind:** research never learns the result (rule 1), so no shot counts or caps are needed. The
  owner steers research only by broad themes, never in response to a specific result.
- **Exact duplicates** (identical package hash) are rejected; any change is a new row and a new
  submission.
- **A pass earns paper observation only.** About 5% of zero-edge rows still pass, and the more rows
  are submitted the more lucky passes there are; size needs the forward evidence in §6.5. Sealing
  files cannot erase what papers or AI models already know about these markets.
- Why 5%, not 1% with ≤10 candidates: at 500 holdout trades (SD 1.2R) a real +0.10R edge passes 59%
  of the time at 5% versus 32% at 1% (independent-trade approximation; session dependence lowers both).

### 6.3 The simulator (rule 2)
- Turns every signal into a **complete modeled position path**: entry eligibility, fills and
  non-fills (limit orders need the price to trade through), latency, slipped stops, fees, forced
  flat, and the worse outcome when a minute bar cannot order stop and target.
- Strategies decide from modeled state, so the simulator version is part of the row: a new simulator
  version makes **new rows**, deployed only through a quiescent signed package. Replaying old rows
  under the new version is diagnostic only; it never confers fresh qualification. Original decisions
  are kept, never overwritten.
- **Calibration schedule, declared in advance:** recalibration happens only at fixed calendar points
  (e.g. month ends) on the preceding block; promotions are judged only on later, untouched blocks.
  Neither the freeze date nor the winning calibration may be chosen after seeing confirmation data.
- Scores backtest, holdout, paper and live signals identically. A signal traded on both paper and live
  counts once. Evidence keeps its label (train, validation, holdout, forward).
- **Audit:** every real live order attempt, filled or not, is compared with the simulator. First
  review after ~30 live attempts, then continuously. If reality is worse, a new, more pessimistic
  simulator version is calibrated at the next scheduled point and frozen, and strategies move to it
  as new rows. **Trades used for calibration
  are not confirmation:** step-up evidence counts only forward trades after the last calibration
  freeze. A rescore can disqualify a strategy, never revive a retired one or raise its size. A large
  divergence stops new entries at once.

### 6.4 Paper
- Same executor as live on the IBKR paper account. Proves mechanics: every order resolved, protection
  in place, flat by deadline, restart and disconnect recovery.
- **The cheap evidence source.** Paper signals are scored by the simulator and count as forward
  evidence; paper fills themselves are not trusted (IBKR documents its simulator's limits). Paper
  keeps running alongside live.
- **Live step 1** after **≥10 clean paper sessions**, the commissioning run (§11.3) and the owner's
  signed package.

### 6.5 Live ladder and statistics
- **Step 1:** 1 MES contract, **$600** loss budget, review at 90 sessions. $600 is 12R at $50 risk;
  100 trades of a 1.8R-SD strategy swing about ±$900 by chance, so **step 1 validates execution and
  the simulator; the edge verdict comes mainly from simulator-scored forward evidence** (paper and
  live, each signal once).
- **Step up** (one contract, signed package, while quiescent): ≥100 forward trades after the last
  calibration freeze, with the posterior 20th percentile of **net expectancy** above the hurdle. Net
  expectancy is already after simulator fees and slippage; **the hurdle adds only the strategy's share
  of running costs** (no double-charging). Roughly an 80% one-sided bar: a strategy exactly at the
  hurdle passes ~20% of the time; one 0.2R above it passes ~61% at 100 trades. Simulator audit clean.
- **Sizes above 1 contract are a follow-on milestone** (partial-fill protection designed and tested
  first). Until then the ladder's only step is step 1.
- **Kill** when P(net expectancy > 0) falls below 20% after ≥60 forward trades, or after 250 forward
  trades without reaching the step-up bar. The 20% rule alone is permissive (only ~20% of zero-edge
  strategies trigger it at the first look). The 250-trade expiry is an **economic patience limit,
  not statistical disproof**: a real +0.1R edge needs ~900 independent trades for 80% power (+0.2R:
  ~230), so it will discard some modest profitable edges.
- Repeated looks and selection among many rows raise false promotions beyond any single-look figure;
  the protocol is judged by simulating the whole pipeline, not one test.
- **Fixed before the evidence component is built, not left to the builder:** the prior, session-block
  dependence handling, the evaluation schedule (when looks happen), calibration and confirmation
  blocks, and the hurdle formula. They are the **first component spec of the build plan**, simulated
  under zero-edge and weak-edge pipelines.
- **One bet, not many:** rows on the same market with related mechanisms are not independent
  evidence or diversification. Beyond version 1, capital is admitted against aggregate exposure per
  market and strategy dependence, not the number of passing rows.
- Size ≤ quarter Kelly, rounded down. Steps down and halts are automatic.

---

## 7. Payoff shape — what exits can and cannot do

- Stops, targets and trailing stops **reshape** results; on an unpredictable path they cannot create
  expectancy, and costs make it negative. Hence the random-entry control.
- Funded trailing-drawdown rules favour smooth equity. Codex's simulation of FundedNext 50K Rapid at
  equal +0.20R and $400 risk: a 30%/+3R profile reaches the first payout ~22% of the time vs ~94%
  for 80%/+0.5R. Research optimises net dollars per session **and** funded survival.
- Leaderboards (Myfxbook, MQL5, Collective2, TradingView) are idea sources, never evidence.

---

## 8. Capital and risk (rule 6)

- **Incubation budget *(call)*:** $15,000 maximum cumulative net loss through **2028-12-31**,
  counting trading losses, fees, funded fees and running costs. Reaching it halts all trading and
  opens a thesis review (§12). Reserved: ~$3,750 operations (25 months at $150), $1,000 funded fees,
  $200 data, leaving **~$10,050** for trading losses.
- **Account funding:** the live account holds enough cash for 1 MES at IBKR's current margin plus a
  stress reserve (at least IBKR's $2,000 minimum equity); deposits stay within the $15,000 ceiling.
  Margin cash is not spent budget; losses are measured from marked equity.
- **Planned risk ~$50 per trade** including stressed costs *(call)*: limits trigger action; fast
  markets, halts and limit moves can jump past them.
- **Account limits *(call)*:** daily loss $400 (no entries, flatten); halt at $1,500 below peak,
  restored only by signed approval; $600 per strategy at step 1; margin checked before entry and while
  holding. All from marked equity; peaks survive restarts and are not reset by deposits.
- **Quiet period:** from 2027-06-01 to 2027-08-31 no new deployments, step-ups or funded purchases.
  Running strategies continue with their automatic limits, including the rolls their packages
  already authorize.
- **Restore:** a restored installation starts disarmed (rule 5); backups never carry trading
  authority, unused approvals or a lifted halt.
- **Approvals:** signed deployment packages (go-live, step-up, funded, limit restoration, payments).
  SSH signing from the phone, tested in week 1; passkey later *(call)*. Signer anchors live outside
  the agent-writable tree.
- **Honest expectation:** most ideas fail; a plausible outcome is a loss of a few thousand dollars and
  a clear "no".

---

## 9. Funded accounts (a later, separate qualification)

- **Verified so far (Nov 2026):** FTMO Futures and FundedNext Futures allow bots and VPS, don't
  restrict Israel, require flat by end of day, run on NinjaTrader / Tradovate / TradingView.
  Tradovate's API excludes prop accounts; Topstep's API needs a personal device; Apex and Take Profit
  Trader ban bots; Tradeify restricts Israel.
- **Stage 0 (ours, by 2027-01-15):** research the exact route (API bridge, then TradingView, then
  manual), hosting, residency, payout and KYC. No funded code in version 1.
- **First challenge** only after ≥50 real IBKR trades over ≥20 sessions with clean reconciliation
  and the simulator audit passing; the route must qualify on its own (platform, automation
  permission, exact rules). MES evidence does not certify another route.
- One challenge at a time, ≤$150 each, ≤$300 before the first payout, **$1,000 total** including
  renewals and resets. Buy only if replay under the firm's exact rules shows expected payouts ≥2× all
  fees after halving the payout estimate. Optimise payout, not pass rate.
- Payouts are not brokerage money: firms can void payouts and change terms.

---

## 10. Ideation

Kept from earlier drafts, retargeted to futures: ideas with a stated mechanism ("who loses money to
us, and why"), provenance on every idea, an owner Inbox, and a deterministic duplicate screen. Bandit
rewards use **research-window outcomes only** (rule 1); the bandit itself waits until after version 1.

**First research batch** *(call)*: MES open-to-close continuation with one fixed stop and target at
equal dollar risk, against random entries. Seed from the Algovibes review: the Zarattini/Aziz/Barbon
(2024) noise-band momentum (survived its random-direction control on NQ only; its drawdown would
breach a ~$2,000 funded trailing limit), retested on **MES research windows only** (before the
sealed holdout), with a daily-stop variant. Other markets wait until after version 1.

---

## 11. The system

### 11.1 Components (version 1)

| Layer | Parts |
|---|---|
| Outside | IBKR (paper + live accounts), market data, the owner's phone |
| Trusted (holds the keys) | **Executor / runner:** tiny; receives validated targets, sends orders with protection, journals, reconciles, enforces the risk check. Same code for paper and live. |
| Unprivileged | **Strategy worker** (runs strategy code; no network, credentials or database writes) · **Backtester** (research sandbox) · **Holdout judge** (reads only the sealed files) |
| Core (pure functions) | Strategy interface (closed bars → target with stop and target) · **Simulator** · **Risk check** (marked equity) |
| Storage | Parquet price files (train / validation / sealed holdout) · one SQLite database (trading side only; research can't read it) |
| Control | JSON command line (kept from today), systemd, execution lock, outside heartbeat, off-server backups with tested restore |

Version 1 scope: **one strategy, one MES contract, one IBKR account, fixed stop and target.**
Deferred: trailing stops, sizes above 1 contract, Kelly sizing, the idea bandit, funded executors and
fixtures, multi-market research. Deleted: portfolio allocation, multi-account coordination, a
separate watchdog engine, the old gates and ceremonies.

### 11.2 The executor loop
- Each minute: read the bar and IBKR's positions and orders → strategy worker returns a target →
  risk check → send the difference as one order package with protection → record.
- Also reacts instantly to broker events (fills, rejections, cancels, disconnects) and to a timer.
- **Order journal** (rule 3): intent ID written before sending; broker IDs; deduplicated executions;
  commissions. IBKR's state alone cannot tell "nothing happened" from "entry and stop both filled".
- **One execution episode** owns all its orders until each is resolved; unresolved submissions block
  new entries; a real stop-out ends the episode and is never "replenished" toward the modeled target.
- Protection is never modified while exposed (rule 4). Every close, including the daily-limit
  flatten and a strategy's flat target, is a market order joined to the episode's exit OCA group.
- Manual changes or broker liquidation: block entries, alert, and keep owning the episode until every
  child order is terminal (cancel orphaned exits once the position is confirmed zero); never undo a
  manual flatten.
- After restarts, the daily reset and the weekly login: full reconciliation before trading resumes.

### 11.3 Protection at IBKR (rule 4)
- **Construction, verified on paper in week 1:** entry parent plus three opposite-side children
  (stop, limit target, market order with Good-After-Time = that day's deadline − 5 minutes) sharing
  `parentId` and one exit-only OCA group in "block" mode; the final child transmits. Never put the
  entry in the exit group. Confirm every leg is acknowledged, the dormant timed child doesn't
  interfere, and rejections and cancels behave. Also prove the **forced-close protocol**: a market
  order joined to the same OCA group closes the position and cancels the resting stop and target
  without ever reversing it, including when a child is rejected and during a gateway outage.
- **Commissioning run:** paper cannot certify production behaviour, so before unattended operation a
  short, signed, owner-aware run on the live account at 1 MES confirms the same construction live.
- **Fallback:** ordinary bracket plus an executor-sent timed close, which loses crash-proof timed
  exits. It remains a **live blocker** unless the owner explicitly accepts it in a signed decision.
- Nothing executes during a market halt.

### 11.4 Edge cases (minimal fixes)

| Group | Fix |
|---|---|
| Orders and fills | 1 contract (exits activate only after a full fill); blocked OCA; one episode owns its orders; never replenish after a stop-out |
| Surprises at the broker | Whole-account check; unexpected state blocks entries and alerts |
| Data and clock | Stale or missing bars block signals, never exits; validate timestamps, duplicates, gaps; next-bar execution; Databento vs IBKR overlap checks |
| Session deadline | One dated deadline drives cutoffs, expiries and the timed exit; early closes included |
| Contract rolls | Exact contract on every order; chosen at session start; switched only while quiescent; no trading near expiry |
| Fast markets and margin | $50 planned risk; margin checks; funded margin reserve; limits are triggers, not guarantees |
| Program and server | Execution lock; broken database stops entries (IBKR holds exits); tested restore |
| Evidence | Simulator models non-fills and full paths; whole-policy replay; calibration ≠ confirmation |
| Code and secrets | Strategy code unprivileged (rule 7); holdout judge locked down; packages signed with expiry and one-time number |

### 11.5 Safety tests before the first real order
1. **Crash anywhere:** kill the executor before, during and after sending, and mid-trade; shut down
   the gateway through the timed exit. Nothing duplicates; the position stays protected and is flat on
   time.
2. **Exits and races:** stop/target/timed exit together, a daily-limit flatten while the stop rests,
   a manual flatten leaving orphaned exits, rejections, an outstanding entry at the deadline, an
   early-close day. Never overfill or reverse; never replenish after a stop; rejections block and
   alert.
3. **Same decisions:** identical bars into backtester and executor across gaps, a roll and a DST
   change; a simulator change replays the whole policy exactly; unfilled attempts are kept.
4. **Limits, boundaries and backups:** restart after a losing day; deposit without resetting peaks;
   restore an old backup (starts disarmed; no old approval, halt-lift or peak comes back); a second
   installation tries to trade; replay an old approval; edit a limit unsigned; strategy code returns
   an invalid target, hangs, or tries to reach the network, credentials or database; research tries
   to read a holdout result. All refused or preserved.

### 11.6 Build
About **3 weeks to a paper prototype with two agents** (history side, broker side); unattended live
follows the commissioning run, not the calendar.
- **Week 1:** broker side starts day 1 with the IBKR protection construction and phone signing;
  history side builds price data, normalization and the simulator; research starts on history.
- **Week 2:** executor and strategy worker on IBKR paper with one fixed stop-and-target strategy.
- **Week 3:** the four safety tests, then paper trading.

**Build rules *(call)*:** the stock lane may break; the empty research registry may be reset after
archiving. Agent-reviewed changes merge on their own, except changes to the executor boundary, risk
limits and signer anchors, which need the owner's one-tap merge approval (no code reading).

---

## 12. Thesis review

Opens automatically at the first of: the incubation loss budget is reached; **12 months after paper
starts** with no strategy passing the step-up bar (a fixed observation deadline, not a submission
count); **2028-12-31** without a live strategy above its hurdle. It ends in one recorded decision: change approach, change
scale, or stop. Adding features is not an allowed outcome.

---

## 13. Migration

- **Daily stock lane: frozen** *(call)*. Timers and paid stock data stop; code deleted later if unused.
- The old gates (`paper promote`, forward certificates, `forward_tested`, the 63-bar floor, capped
  route ceremonies) are removed once the new core enforces its rules.
- Kept: the JSON CLI contract, SSH signing, the `t → t+1` rule, the recovery principle of
  `algua/execution/live_ledger.py` (not its Alpaca assumptions).
- Verified on the VPS on 2026-11-20: zero strategies in the registries; no paper/live operator units;
  only paper broker credentials.

---

## 14. Timeline

| When | Stage | Money at risk |
|---|---|---|
| Dec 2026 – 15 Jan 2027 | **0. Verify:** cut cost; our own funded-route research; open and fund the IBKR futures account and data | None |
| Dec 2026 (~3 weeks) | **1. Build** to a paper prototype (§11.6); research on history from week 1 | Data ≤ $200 |
| Jan 2027 | **2. Paper** (≥10 clean sessions) → commissioning run → **live step 1** | $600 per strategy |
| Feb – May 2027 | **3. Forward evidence;** size-up milestone; first funded challenge only after ≥50 real trades | Fee caps |
| Jun – Aug 2027 | **Quiet period:** no new deployments, steps or purchases | Running strategies only |
| Sep 2027 – Dec 2028 | Scale and funded on evidence | Within the $15k budget |

No date lowers a bar.

---

## 15. Context-file and board updates (after approval)

- **PRD:** owner amendment with this document's decisions.
- **CLAUDE.md, AGENTS.md, README, `docs/agent/*`, `.opencode/*`:** adopt the vocabulary and seven
  rules; mark unbuilt items as targets with their cards.
- Personal context never enters this public repository; only the capital rules do.
- **Todoist (Algua):** retire old-route and stock-lane cards; add Stage 0 and build cards in §14 order.

---

## 16. Claude's calls for the owner to check

1. Incubation budget $15,000 cumulative net loss through 2028-12-31, including running costs and fees.
2. Daily loss $400; halt at $1,500 below peak; ~$50 planned risk per trade.
3. Funded fee cap $1,000; one challenge at a time; ≤$150 each.
4. Session deadline: the earlier of 15:00 CT and the early close.
5. Live data from IBKR; history from Databento ≤ $200.
6. Holdout bar 5% one-sided; step up after ≥100 forward trades at the posterior 20th percentile; kill
   below 20% after 60 trades or at 250 trades.
7. Stage derived from evidence rather than stored.
8. Owner one-tap merge approval only for the executor boundary, risk limits and signer anchors.
9. Stock lane frozen and allowed to break; empty registry may be reset after archiving.
10. SSH signing first; passkey later.
11. Version 1 uses a fixed stop and target; trailing stops and sizes above 1 contract are deferred.

---

## 17. Approaches considered

| Decision | Chosen | Rejected and why |
|---|---|---|
| What the system is for | Intraday futures for funded payouts | Daily stocks: can't make the owner rich at $15k |
| Architecture | Lean new core, tiny trusted executor, broker-held exits | Refactor of the stock platform; Astra's first design (too slow, too much machinery) |
| Code authority | Strategy code unprivileged; only targets cross (rule 7) | "Pure functions" inside the credentialed runner: unenforced |
| Holdout leakage | Blind holdout (rule 1) | Per-idea shot counts; ≤10 candidates at 1% (rejects about half of real +0.10R edges that pass at 5%) |
| Paper vs live evidence | One simulator scores every signal (rule 2) | Separate scores; paired gap adjustments |
| Execution truth | Broker state + small journal + one episode | Broker state alone (ambiguous after downtime); full order framework |
| Exits | Entry × exit × sizing with a random-entry control | Exit tuning alone: cannot create edge |
| Funded route | Our own research; API → TradingView → manual | Waiting on firms' confirmation; home rig for Topstep |
| Stages | Research → holdout → paper → live (ladder) | Separate pilot and funded stages; a "freeze" step |
| Personal broker | IBKR with a weekly login | Tradovate API (unverified for unattended use); Alpaca (no futures) |

## 18. Left to the builder

Exact simulator parameters per contract, roll timing, module layout, schema and test fixtures, each
fixed in its component spec and covered by tests. Funded rule-set fixtures (FundedNext 50K Rapid
first) wait for the funded milestone. The evidence statistics are **not** left to the builder (§6.5).
