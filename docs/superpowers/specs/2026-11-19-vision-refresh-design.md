# Vision refresh — intraday futures for funded payouts

**Status:** Draft for owner approval · **Date:** 2026-11-22 (revision 3) · **Owner:** Lior Nisimov
**Origin:** owner design session, 2026-11-16 → 2026-11-22, with Codex, Grok and Codex Astra reviews
(debate on futures, prop-rule simulation, two hostile reviews, three architecture reviews).
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
Algua is an **intraday CME micro futures system**. The personal IBKR account produces the
**evidence**; funded accounts are a later **multiplier** on the same strategy. A funded pass is never
evidence.

### Goals
- Find intraday futures edges that survive realistic execution, judged on data research never saw.
- Keep the system small enough to build in about three weeks and run unattended.
- Keep every loss limit in code and at the broker; grow size only on evidence.
- Operating cost near **$150/month**.

### Non-goals
- Daily or multi-day stock trading (lane frozen, §13). Spot forex, options, crypto.
- Proving an edge by a deadline. No date lowers a bar.

### Anti-goals (failure even if it "works")
- Scaling the luckiest of many experiments.
- Treating backtests, leaderboards or challenge passes as proof.
- Machinery that manages a problem when one rule could make it impossible (§3).
- Hidden-risk strategies (martingale, grid, averaging down, no stop).
- Anything needing routine owner attention beyond the weekly broker login.

---

## 2. Owner decisions

1. Operating cost ~$150/month.
2. **Pivot:** Algua is built for intraday futures aimed at funded payouts; a **lean new core** replaces
   the old machinery rather than refactoring it.
3. Research searches **entry × exit × sizing** (stops, trailing stops, targets, reward-to-risk, win
   rate) under the honesty rules in §7.
4. **Flat by end of day** for every strategy, for now.
5. **Personal broker: IBKR**, with a weekly login.
6. **Live step 1 loss budget: $600 per strategy.**
7. **No funded route → personal futures only.**
8. **Stage 0 is our own research** of funded routes; we don't wait on firms. Fallbacks in order:
   API bridge → TradingView → the owner sends orders by hand (last resort).
9. Stages: **research → holdout → paper → live → retired.** "Paper trading" replaces "shadow".
   Pilot and live are one stage, **live, with a ladder**. Funded is an extra account of a live
   strategy, not a stage.
10. **A strategy is an insert-only row;** evidence is appended immutably. Any change is a new row
    (no separate "freeze" step).
11. **The holdout stays,** as a blind screen (§6.2).
12. **The design lens (§3):** one structural rule instead of counters, ledgers, caps or adjustments.
    In particular: research never sees holdout results, and every trade is scored by one simulator.
13. Code is generic, clean where it matters, and as simple as possible.
14. USD everywhere; the owner approves every payment.

---

## 3. The six rules

Each rule replaces a set of special cases with one behaviour that makes the problem impossible.

| # | Rule | What goes wrong without it | What it removes |
|---|---|---|---|
| 1 | **Information only flows outward.** Research hands strategies out through a one-way mailbox and never receives anything back: no holdout result, no paper/live numbers, no hint of which strategies trade. | Research tweaks a failed strategy and resubmits; a zero-edge idea retried 20 times passes a 5% test ~64% of the time. | Retry counters, "same idea" families, submission caps, pass-rate surveillance. |
| 2 | **Evidence is calculated, never hand-entered.** One simulator turns every signal (backtest, paper, live) into a full modeled trade; scores are always derived from it. | Separate paper and live scores with a correction between them. | Separate evidence streams, manual adjustments. |
| 3 | **If anything is uncertain, no new entries.** Exits and protection keep working. One trade in progress at a time. | A crash after sending a buy leads to a second buy: 2 contracts, protection on 1. | Per-failure special handling. |
| 4 | **Every open position has protection held at IBKR,** sent in one package with the entry. | A server crash leaves a position unprotected. | A separate watchdog trading engine. |
| 5 | **Change only while flat:** go-live, new versions, size steps and contract rolls happen only with no open position, as one signed, immutable package. | A new version inherits an unknown open trade; a roll forgets the old month. | Hand-over logic, stage-transition machinery. |
| 6 | **Real money sets the limits.** Loss limits, margin and funded drawdowns use actual fills and cash; simulated numbers only judge strategies. | The simulator says −$300, slippage made it −$450, and the $400 limit never fires. | Mixing two meanings of P&L. |

What the rules do **not** remove (Astra, review 3): loss totals and equity peaks, fees, margin,
approval replay protection, the order journal, and the safety tests. Where possible these are
calculated from recorded facts rather than tracked separately.

---

## 4. Vocabulary and lifecycle

| Word | Meaning |
|---|---|
| **strategy row** | Code + settings + simulator version, hashed. Insert-only; any change is a new row. |
| **research** | Building and tuning on train + validation history, in a sandbox. |
| **holdout** | One blind test per row on a sealed 2-year window. A screen, not proof. |
| **paper** | The row runs on the IBKR paper account: real order handling, no money. Proves mechanics. |
| **live** | The row trades real money on IBKR, on a ladder of sizes. |
| **deployment package** | One signed, immutable bundle: row hash, account, contract, limits, expiry, one-time number. |
| **retired** | Terminal. A benched strategy is a halted deployment, not a separate stage. |

`idea → research → holdout → paper → live → retired`. The stage is **derived** from the row's appended
evidence and active deployment, not stored as separately managed state *(call)*.

---

## 5. Markets and data

- **Instruments:** CME micro futures. Version 1 trades **MES only**; MNQ, M2K, MYM, MGC, MCL and micro
  rates/FX follow. MES/MNQ/MYM/M2K are close to one bet; breadth comes from rates, metals, energy, FX
  and distinct mechanisms.
- **Session:** flat by **15:00 CT** by default *(call)* (before FundedNext's 15:10 CT and FTMO's
  16:10 ET). The daily close starts 5 minutes before the earlier of 15:00 or that day's early close.
  The cutoff is part of the row.
- **Data:** historical minute bars per contract from Databento, capped at **$200**. Live data from
  the IBKR CME subscription (Databento live at $199/month breaks the budget). Continuous series are
  for research only, never order prices. Every order names the exact contract (conId, expiry).
- **One session definition** (rule 5) drives data, contract choice and permitted exposure, shared by
  the backtester and the runner. UTC internally; Chicago time for schedules; clock-skew check.

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

Research runs sandboxed: no network beyond allowed sources, no live keys, no write access to running
code or signing files, **no read access to the trading database** (rule 1).

### 6.2 Holdout (blind screen)
- Fixed window: the latest 2 years, sealed until incubation ends; then the newest 2 years are sealed
  and the old window becomes research data.
- Judged by a separate process that alone reads the sealed files and writes only to the trading side.
- **Pass bar:** net profit after simulator costs at **5% one-sided** (session-aware statistics), and
  beats random entries. Too few trades: inconclusive, never extended after seeing results.
- **Blind:** research never learns the result (rule 1), so no shot counts or caps are needed. The
  owner steers research only by broad themes, never in response to a specific result.
- Duplicates are rejected by a hash of the **full package** (code + settings), so a parameter tweak
  counts as the same row.
- Honest limits: about 5% of zero-edge rows still pass; paper and live filter them. Sealing files
  cannot erase what papers or AI models already know about these markets.
- Why 5%, not Astra's earlier 1% with ≤10 candidates: at 500 holdout trades (SD 1.2R) a real +0.10R
  edge passes 59% of the time at 5% versus 32% at 1%; with no feedback, retries cannot inflate the
  false-pass rate.

### 6.3 The simulator (rule 2)
- Turns every signal into a **complete modeled position path**: entry eligibility, fills and
  non-fills (limit orders need the price to trade through), latency, slipped stops, fees, forced
  flat, and the worse outcome when a minute bar cannot order stop and target.
- Scores backtest, holdout, paper and live signals identically. A signal traded on both paper and live
  counts once. Evidence keeps its label (train, validation, holdout, post-holdout); uniform scoring
  does not make training results independent.
- **Audit:** every real live order attempt, filled or not, is compared with the simulator's
  prediction. First review after ~30 live attempts, then continuously. If reality is worse, the
  simulator becomes more pessimistic (a new version) and all scores are recalculated; original
  decisions are never overwritten. A rescore can disqualify a strategy, never revive a retired one or
  raise its size. A large divergence stops new entries at once.
- Strategies decide from modeled state, not from actual fills, so rescoring a whole policy is exact.

### 6.4 Paper
- Same runner as live on the IBKR paper account. Proves mechanics: every order resolved, protection
  in place, flat by cutoff, restart and disconnect recovery.
- **Live step 1** after **≥10 clean paper sessions** and the owner's signed package.
- Paper signals count as evidence via the simulator; paper fills are not trusted (IBKR documents its
  simulator's limits).

### 6.5 Live ladder
- **Step 1:** 1 MES contract, **$600** loss budget, review at 90 sessions.
- **Step up** (one contract, signed package, while flat): ≥100 simulator-scored post-holdout trades
  (paper and live, each signal once) with the posterior 20th percentile of net expectancy above the
  hurdle (fees, stressed slippage and its share of running costs); simulator audit clean; partial-fill
  protection tested before any size above 1 contract.
- **Kill** when P(net expectancy > 0) falls below 20% after ≥60 trades. Steps down and halts are
  automatic. Size ≤ quarter Kelly, rounded down.
- Honest sample sizes: a 30% win-rate / +3R profile (SD ~1.8R) needs ~320–520 independent trades to
  confirm +0.2R; throughput comes from strategies trading several times per session and from unrelated
  markets.

---

## 7. Payoff shape — what exits can and cannot do

- Stops, targets and trailing stops **reshape** results; on an unpredictable path they cannot create
  expectancy, and costs make it negative. Hence the random-entry control.
- Funded trailing-drawdown rules favour smooth equity. Codex's simulation of FundedNext 50K Rapid at
  equal +0.20R and $400 risk: a 30%/+3R profile reaches the first payout ~22% of the time vs ~94%
  for 80%/+0.5R. Research optimises net expectancy **and** funded survival.
- Leaderboards (Myfxbook, MQL5, Collective2, TradingView) are idea sources, never evidence.

---

## 8. Capital and risk (rule 6)

- **Incubation budget *(call)*:** $15,000 maximum cumulative net loss, counting trading losses, fees,
  funded fees and running costs. Reaching it halts all trading and opens a thesis review (§12).
  Reserved: ~$3,600 operations, $1,000 funded fees, $200 data, leaving ~$10,200 for trading losses.
- **Planned risk ~$50 per trade** including stressed costs *(call)*: limits trigger action; fast
  markets, halts and limit moves can jump past them.
- **Account limits *(call)*:** daily loss $400 (no entries, flatten); halt at $1,500 below peak,
  restored only by signed approval; $600 per strategy at step 1; margin checked before entry and while
  holding. Peaks and totals derive from actual fills and survive restarts.
- **Quiet period:** no new live steps, step-ups or funded purchases from 2027-06-01 to 2027-08-31.
  Running strategies keep their automatic limits.
- **Approvals:** signed deployment packages (go-live, step-up, funded, limit restoration, payments).
  SSH signing from the phone first, tested before the first live order; passkey later *(call)*.
  Signer anchors live outside the agent-writable tree.
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
  permission, exact rules) — MES evidence does not certify another route.
- One challenge at a time, ≤$150 each, ≤$300 before the first payout, **$1,000 total** including
  renewals and resets. Buy only if replay under the firm's exact rules shows expected payouts ≥2× all
  fees after halving the payout estimate. Optimise payout, not pass rate.
- Payouts are not brokerage money: firms can void payouts and change terms.

---

## 10. Ideation

Kept from earlier drafts, retargeted to futures: ideas with a stated mechanism ("who loses money to
us, and why"), provenance on every idea, an owner Inbox, and a deterministic duplicate screen. Bandit
rewards use **research-window outcomes only** (rule 1).

**First research batch** *(call)*: MES open-to-close continuation across fixed-time exit, hard stop
and volatility trailing stop at equal dollar risk, against random entries. Seeds from the Algovibes
review: the Zarattini/Aziz/Barbon (2024) noise-band momentum on NQ (survived its random-direction
control on NQ only; its drawdown would breach a ~$2,000 funded trailing limit), tested on MNQ after
2024-05 net of 2 ticks, plus a half-size variant.

---

## 11. The system

### 11.1 Components (version 1)
One codebase, one machine, one broker:

| Layer | Parts |
|---|---|
| Outside | IBKR (paper + live accounts), market data, the owner's phone |
| Program | **Backtester** (research sandbox; holdout judged separately) · **Runner** (paper and live, same code) · **Command line** (JSON, kept from today) |
| Core (pure functions) | **Strategy** (closed bars → target with stop and target) · **Risk check** (actual fills and cash) · **Simulator** |
| Storage | Parquet price files (train / validation / sealed holdout) · one SQLite database (trading side only; research can't read it) |
| Operations | systemd, one-runner lock per account, outside heartbeat, off-server backups with tested restore |

Version 1 scope: **one strategy, one MES contract, one IBKR account.** Deleted from version 1:
portfolio allocation, multi-account coordination, sizing math beyond 1 contract, funded executors,
a separate watchdog engine, the old gates and ceremonies.

### 11.2 The runner
- Each minute: read the bar and IBKR's positions and orders → strategy target → risk check → send the
  difference as one order with protection attached → record fills.
- Also reacts instantly to broker events (fills, rejections, cancels, disconnects) and to a timer.
- **Order journal** (rule 3): intent ID written before sending; broker IDs; deduplicated executions;
  commissions. IBKR's state alone cannot tell "nothing happened" from "entry and stop both filled".
  Any unresolved submission blocks new entries. One entry episode at a time.
- Exit orders are classified separately from position changes and replaced only after IBKR confirms
  the cancel.
- Manual changes or broker liquidation: block entries, alert; never undo a manual flatten.
- After restarts, the daily reset and the weekly login: full reconciliation before trading resumes.

### 11.3 Protection at IBKR (rule 4)
Construction to verify on the paper account in **days 1–3**: entry parent plus three opposite-side
children (stop, limit target, market order with Good-After-Time ~14:55 CT) sharing `parentId` and one
exit-only OCA group in "block" mode; the final child transmits. Never put the entry in the exit
group. Confirm every leg is acknowledged and that the dormant timed child doesn't interfere.
**Fallback:** ordinary bracket plus a runner-sent timed close, which loses crash-proof timed exits;
not accepted silently. Nothing executes during a market halt.

### 11.4 Edge cases (minimal fixes)

| Group | Fix |
|---|---|
| Orders and fills | 1 contract (exits activate only after a full fill); blocked OCA; classify exits; serialize changes |
| Surprises at the broker | Whole-account check; unexpected state blocks entries and alerts |
| Data and clock | Stale or missing bars block signals, never exits; validate timestamps, duplicates, gaps; act on the next bar |
| Contract rolls | Exact contract on every order; choose at session start; switch only while flat; no trading near expiry |
| Fast markets | $50 planned risk; margin checks; limits are triggers, not guarantees |
| Program and server | One-runner lock; broken database stops entries (IBKR holds exits); tested restore |
| Evidence | Simulator models non-fills and full paths; versioned rescoring; worse-case intrabar ordering |
| Approvals and secrets | Research sandboxed; holdout judge locked down; packages signed with expiry and one-time number |

### 11.5 Safety tests before the first real order
1. **Crash anywhere:** kill the runner before, during and after sending, and mid-trade; shut down the
   gateway through the timed exit. Nothing duplicates; the position stays protected and is flat on time.
2. **Exits and races:** stop/target/timed exit together, rejections. Never overfill; rejections block
   and alert.
3. **Same decisions:** identical bars into backtester and runner across gaps, a roll and a DST change;
   rescoring after a simulator change reproduces exactly; unfilled attempts are kept.
4. **Limits, backups and leaks:** restart after a losing day, restore and replay, replay an old
   approval, edit a limit unsigned, try to read a holdout result from research. All refused or
   preserved.

### 11.6 Build
About **3 weeks with two agents in parallel** (history side, broker side): week 1 shared types, price
data, simulator and backtester (research starts on history immediately); week 2 runner on IBKR paper
with attached protection; week 3 the four safety tests, then paper trading. Days 1–3 include the
IBKR protection test.

**Build rules *(call)*:** the stock lane may break; the empty research registry may be reset after
archiving. Agent-reviewed changes merge on their own, except changes to the live-money wall, risk
limits and signer anchors, which need the owner's one-tap merge approval (no code reading).

---

## 12. Thesis review

Opens automatically at the first of: the incubation loss budget is reached; 40 holdout submissions
with none reaching live step 2; 12 months after paper starts with no strategy past step 1; in
personal-futures-only mode, **2028-12-31** without a live strategy above its hurdle. It ends in one
recorded decision: change approach, change scale, or stop. Adding features is not an allowed outcome.

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
| Dec 2026 – 15 Jan 2027 | **0. Verify:** cut cost; our own funded-route research; open the IBKR futures account and data | None |
| Dec 2026 (~3 weeks) | **1. Build** (§11.6); research on history from week 1 | Data ≤ $200 |
| Jan 2027 | **2. Paper → live step 1** after ≥10 clean sessions | $600 per strategy |
| Feb – May 2027 | **3. Ladder** on evidence; first funded challenge only after ≥50 real trades | Ladder + fee caps |
| Jun – Aug 2027 | **Quiet period:** no new steps or purchases | Running strategies only |
| Sep 2027 onward | Scale and funded on evidence | Within the $15k budget |

No date lowers a bar.

---

## 15. Context-file and board updates (after approval)

- **PRD:** owner amendment with this document's decisions.
- **CLAUDE.md, AGENTS.md, README, `docs/agent/*`, `.opencode/*`:** adopt the vocabulary and six
  rules; mark unbuilt items as targets with their cards.
- Personal context never enters this public repository; only the capital rules do.
- **Todoist (Algua):** retire old-route and stock-lane cards; add Stage 0 and build cards in §14 order.

---

## 16. Claude's calls for the owner to check

1. Incubation budget $15,000 cumulative net loss including running costs and fees.
2. Daily loss $400; halt at $1,500 below peak; ~$50 planned risk per trade.
3. Funded fee cap $1,000; one challenge at a time; ≤$150 each.
4. Default cutoff 15:00 CT.
5. Live data from IBKR; history from Databento ≤ $200.
6. Holdout bar 5% one-sided; kill below 20% after 60 trades; step up after ≥100 post-holdout trades.
7. Stage derived from evidence rather than stored.
8. Owner one-tap merge approval only for the live-money wall, risk limits and signer anchors.
9. Stock lane frozen and allowed to break; empty registry may be reset after archiving.
10. SSH signing first; passkey later.

---

## 17. Approaches considered

| Decision | Chosen | Rejected and why |
|---|---|---|
| What the system is for | Intraday futures for funded payouts | Daily stocks: can't make the owner rich at $15k |
| Architecture | Lean new core, one program, broker-held exits | Refactor of the stock platform; Astra's first design (too slow, too much machinery) |
| Holdout leakage | Blind holdout (rule 1) | Per-idea shot counts; ≤10 candidates at 1% (rejects two thirds of real +0.10R edges) |
| Paper vs live evidence | One simulator scores every signal (rule 2) | Separate scores; paired gap adjustments |
| Execution truth | Broker state + small journal | Broker state alone (ambiguous after downtime); full order framework |
| Exits | Entry × exit × sizing with a random-entry control | Exit tuning alone: cannot create edge |
| Funded route | Our own research; API → TradingView → manual | Waiting on firms' confirmation; home rig for Topstep |
| Stages | Research → holdout → paper → live (ladder) | Separate pilot and funded stages; a "freeze" step |
| Personal broker | IBKR with a weekly login | Tradovate API (unverified for unattended use); Alpaca (no futures) |

## 18. Left to the builder

Exact simulator parameters per contract, the Bayesian prior, block length for dependence, roll timing,
module layout, schema and fixtures (FundedNext 50K Rapid rules are the first rule-set fixture), each
fixed in its component spec and covered by tests.
