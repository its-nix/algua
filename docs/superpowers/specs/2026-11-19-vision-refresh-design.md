# Vision refresh — intraday futures for funded payouts

**Status:** Revision 6, 2026-11-26 — **superseded as the current statement by [docs/PRD.md](../../PRD.md)
(rewritten 2026-11-26); kept as decision history.** The owner agreed this direction (the desk,
per-strategy risk, the halt target); revision 5 was approved 2026-11-22. · **Owner:** Lior Nisimov
**Origin:** owner design session, 2026-11-16 → 2026-11-26, with Codex, Grok and Codex Astra reviews
(debate on futures, prop-rule simulation, two hostile reviews, seven architecture reviews). Revisions
4–6 apply Astra's reviews; revision 6 adds the profit-speed and stability review and the strategy-pool
review (§17).
**Companion diagram:** the "Algua Data Flow" artifact (private) shows the same design visually.
**Supersedes:** revision 5 (commit `926d107`) and the 2026-11-19 daily-stock draft (`1bbae69`).

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
**evidence**; funded accounts are a later **multiplier**. A funded pass is never evidence.

**Where speed comes from (revision 6).** Two things limit how fast money arrives: finding strategies
that are actually good (only ~1 in 13 distinct ideas is expected to pass the holdout), and collecting
enough independent forward evidence to trust them. The design therefore observes every candidate in
parallel for free, lets many strategies trade through **one desk** (§6.5), and makes generating
genuinely different ideas a first-class goal (§10).

### Goals
- Find intraday futures edges that survive realistic execution, judged on data research never saw.
- Optimise **net dollars per trading session after running costs**, not pass rates or attractive
  reward-to-risk ratios.
- Prefer edges that are **stable**: they survive small, pre-declared changes (§6.6).
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
6. **Live step 1 loss budget: $600** — now for the **desk pilot** (§6.5) rather than per strategy
   *(call, §16)*.
7. **No funded route → personal futures only.**
8. **Stage 0 is our own research** of funded routes; we don't wait on firms. Fallbacks in order:
   API bridge → TradingView → the owner sends orders by hand (last resort).
9. Stages: **research → holdout → paper → live → retired.** "Paper trading" replaces "shadow".
   Pilot and live are one stage, **live, with a ladder**. Funded is an extra account, not a stage.
10. **A strategy is an insert-only row;** evidence is appended immutably. Any change, including a
    single parameter, is a new row (no separate "freeze" step).
11. **The holdout stays,** as a blind screen (§6.2).
12. **The design lens (§3):** one structural rule instead of counters, ledgers, caps or adjustments.
    In particular: research never sees holdout results, and every trade is scored by one simulator.
13. Code is generic, clean where it matters, and as simple as possible.
14. USD everywhere; the owner approves every payment.
15. **The desk (2026-11-26):** strategies are advisors that propose trades; **one trusted executor
    owns the account** and decides which proposals trade. The **desk as a whole** — its members,
    priority order, risk per member and limits — is what qualifies for real money, is signed and is
    deployed. Version 1 has **one live MES slot**; more simultaneous trades come later on evidence.
16. **Risk per trade is chosen per strategy** within a dollar range *(range is a call: $20–$50)*; the
    simulator charges real costs, so tight-stop strategies survive only if their edge beats the
    larger cost share.
17. **Halt target:** the desk earns real money only while its predicted chance of hitting the
    drawdown halt within the next 20 sessions is **≤5%**, under dependence and cost stress.

---

## 3. The seven rules

Each rule replaces a set of special cases with one behaviour. A rule **prevents** a class of failure
by construction where it can and **reduces** it where it can't; the table says which.

| # | Rule | What goes wrong without it | Precise meaning and limits |
|---|---|---|---|
| 1 | **Information only flows outward.** Research hands rows out through a one-way mailbox and never receives anything back: no holdout result, no paper/live numbers, no hint of which strategies trade or sit on the desk. | Research tweaks a failed strategy and resubmits; a zero-edge idea retried 20 times passes a 5% test ~64% of the time. | Prevents feedback-driven tuning. Does **not** prevent luck: of 20 independent zero-edge rows, ~64% of the time at least one passes. So a holdout pass earns paper observation only (§6.2). The **only** channel back is the global simulator version (market-wide cost parameters, never strategy-specific results). Logs, agent memory and maintenance work keep strategy and desk outcomes out of research. |
| 2 | **Evidence is calculated, never hand-entered.** One simulator scores every candidate **and the executable desk policy**, including allocation, skipped signals and account limits. | Separate paper and live scores with a correction between them; a desk judged by adding up members that could never all have traded. | Prevents inconsistent scoring, not model error. There is **one canonical modeled episode stream** per row; real execution may skip an episode (e.g. slot busy, blocked) but never invents or repeats one, and each signal is counted once. Trades used to calibrate the simulator are never counted as confirmation. |
| 3 | **If anything is uncertain, no new entries.** **One execution owner controls each account and contract.** | A crash after sending a buy leads to a second buy: 2 contracts, protection on 1. Two strategies net to "flat" while one's stop is still working and later opens an unmanaged short. | Every order belongs to exactly one episode until every child order is terminal, even after the position is closed. Any unresolved account state (submissions, unknown fills, unexpected positions or orders) blocks new entries. The executor never sends a second exit while one's outcome is unknown and never re-enters to replace a position that was actually stopped out. |
| 4 | **Every actual exposure has protection held at IBKR,** sent in one package with the entry, and **never removed while exposed.** **Every close goes through the episode's single exit authority.** | A server crash or a cancel-then-replace gap leaves a position unprotected; a separate "sell now" races the resting stop and reverses the position. | Stop, target, timed exit, daily-limit flatten, strategy flat and manual close all act **within the episode's exit OCA group** (a forced close is a market order joined to that group). Virtual offsets between strategies never count as protection or flatness. Version 1 uses a fixed stop and target and never modifies them. Proven in week 1 and at commissioning (§11.3); nothing executes during a market halt. |
| 5 | **Change only while quiescent.** Go-live, new desk packages and size steps happen only with **zero positions, zero working orders and zero unresolved submissions** on the account, under the execution lock. | A waiting order fills just after a new version starts; a restored second server trades alongside the first. | Each change is one signed, immutable **desk package** covering the complete executable identity (code, dependencies, settings, simulator version, account, contract family and roll schedule, **membership, priority, risk per member**, limits). Being flat daily makes this cheap; there are no hot membership changes. Scheduled rolls inside an active package happen while quiescent without a new signature. **One active executor:** a new or restored installation starts **disarmed**, fences the previous one, reconciles history and needs a fresh signed activation; trading authority is never restored from backup. |
| 6 | **Real money sets the limits.** Admit an order only if the **stressed account state after every outstanding order could fill** stays above every equity floor and within margin. | The simulator says −$300, slippage made it −$450, and the $400 limit never fires; a pending entry fills after the limit was reached. | Floors: today's start −$400, peak −$1,500, and the incubation floor, all from **marked account equity** (actual fills, open positions at current prices, accrued fees, adjusted for deposits and withdrawals). Stress = additional loss from current marked equity, including pending submissions and closing costs, with a finite gap allowance — a stress bound, never an absolute guarantee. Budgets and peaks belong to the account and the incubation; no row, desk package or approval resets them, and deposits never do. A stale mark blocks new entries and alerts. Simulated numbers only judge strategies. |
| 7 | **Only answers cross into the executor.** Research-written strategy code runs unprivileged (no credentials, no network, no database writes) and only **proposes** validated trades; only the trusted executor allocates risk and submits orders. | A buggy or malicious strategy touches the broker or the signing files. | **Validation contract:** side ∈ long/short/flat; finite, tick-aligned prices; stop on the correct side; approved contract; risk ≤ the member's cap in the package; fresh episode ID. Anything else is rejected and blocks entries. The worker runs under a timeout and resource limits; it can never delay the executor's exits. |

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
| **paper** | Every holdout passer is **observed in parallel**: the simulator scores its signals on live prices (free, unlimited). The IBKR paper account runs the desk to prove order handling. |
| **desk** | The executable policy that turns members' proposals into orders: membership, fixed priority, risk per member, slots, limits. The unit that qualifies, is signed and trades. |
| **slot** | One trade the desk may hold at a time. Version 1 has one MES slot. |
| **live** | A row is live while it is a member of the signed live desk. |
| **desk package** | One signed, immutable bundle: complete executable identity, membership, account, contract, limits, expiry, one-time number. |
| **halted** | A desk stopped by a limit; it can resume only through a new signed package. |
| **retired** | Terminal. A retired row never trades again; a revised idea is a new row. |

`idea → research → holdout → paper → live → retired`. A row leaving the live desk (futility or decay
alarm, §6.5) returns to paper observation. The stage is **derived** from the row's appended evidence
and the active desk package, not stored as separately managed state *(call)*.

---

## 5. Markets and data

- **Instruments:** CME micro futures. Version 1 trades **MES only**; MNQ, M2K, MYM, MGC, MCL and micro
  rates/FX follow. MES/MNQ/MYM/M2K are close to one bet; breadth comes from rates, metals, energy, FX
  and distinct mechanisms. **After version 1**, one economically different market (rates, gold or oil)
  is admitted to research and paper observation before any multi-market execution: two independent
  searches roughly double the chance of discovery.
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
1. Scored by the simulator (§6.3), at the row's own risk per trade with real costs.
2. **Random-entry control:** the same exit and sizing on time-matched random entries; the control is
   itself placebo-tested. Not beating it means no entry edge, whatever the win rate.
3. **Stability in research** (§6.6): parameter plateau and deletion survival on research windows.
4. **Prop-rule replay** at real size when a funded route exists (§9).
5. Deflated Sharpe, advisory.

**Sandbox (rule 1, rule 7):** research agents may reach an allowlist of web idea sources; strategy code
they write executes with **no network**, no credentials, no write access to running code or signing
files, and **no read access to the trading database**.

### 6.2 Holdout (blind screen)
- Fixed window: the latest 2 years, sealed until incubation ends; then the newest 2 years are sealed
  and the old window becomes research data. Research seeds never use data inside the sealed window.
- Judged by a separate process that alone reads the sealed files and writes only to the trading side;
  the strategy code runs unprivileged there too (rule 7).
- **Pass bar:** net profit after simulator costs at **5% one-sided**, with session-block statistics,
  beats random entries, and passes deletion survival (§6.6). Too few trades: inconclusive, never
  extended after seeing results.
- **Blind:** research never learns the result (rule 1), so no shot counts or caps are needed. The
  owner steers research only by broad themes, never in response to a specific result.
- **Exact duplicates** (identical package hash) are rejected; any change is a new row and a new
  submission.
- **A pass earns paper observation only.** About 5% of zero-edge rows still pass; under illustrative
  assumptions only ~39% of passers are genuine. Sealing files cannot erase what papers or AI models
  already know about these markets.
- Why 5%, not 1% with ≤10 candidates: at 500 holdout trades (SD 1.2R) a real +0.10R edge passes 59%
  of the time at 5% versus 32% at 1% (independent-trade approximation; session dependence lowers both).

### 6.3 The simulator (rule 2)
- Turns every signal into a **complete modeled position path**: entry eligibility, fills and
  non-fills (limit orders need the price to trade through), latency, slipped stops, fees, forced
  flat, and the worse outcome when a minute bar cannot order stop and target.
- Also runs the **desk policy**: which proposals the slot takes under the fixed priority, which are
  skipped, and the account limits. The desk is judged on this modeled stream, never on the sum of
  members that could not all have traded.
- Strategies decide from modeled state, so the simulator version is part of the row: a new simulator
  version makes **new rows**, deployed only through a quiescent signed package. Replaying old rows
  under the new version is diagnostic only; it never confers fresh qualification.
- **Calibration only on predefined mismatch:** at scheduled review points the audit compares real
  orders with the simulator; the simulator is recalibrated **only** if a pre-declared mismatch
  criterion is met. Otherwise the frozen simulator stays, so forward evidence keeps accumulating.
  Calibration data are never reused as confirmation; neither the freeze date nor the winning
  calibration may be chosen after seeing confirmation data.
- Scores backtest, holdout, paper and live signals identically. A signal traded on both paper and live
  counts once. Evidence keeps its label (train, validation, holdout, forward).
- **Audit:** every real live order attempt, filled or not, is compared with the simulator. First
  review after ~30 live attempts, then at scheduled points. A rescore can disqualify a strategy, never
  revive a retired one or raise its size. A large divergence stops new entries at once.

### 6.4 Paper
- **Parallel observation:** every holdout passer is observed by the simulator on live prices from the
  day it passes. There is no limit on how many rows are observed at once, and no row waits for
  another. Ten rows needing 100 sessions finish in 100 sessions, not 1,000.
- **IBKR paper account:** runs the same executor and the candidate desk policy to prove mechanics:
  every order resolved, protection in place, flat by deadline, restart and disconnect recovery. Paper
  fills themselves are not trusted (IBKR documents its simulator's limits). Paper keeps running
  alongside live.
- **Live step 1** after **≥10 clean paper sessions**, the commissioning run (§11.3) and the owner's
  signed desk package.

### 6.5 The desk, its admission and the statistics
**Unit.** Members propose; the desk decides. Real money is admitted, scaled and stopped for the
**desk policy**, scored by the simulator on fresh forward sessions with running costs charged once.

**Member checkpoint.** A row is considered for desk membership after **≥100 forward trades** after
the last calibration freeze, with its stability checks passing (§6.6). 100 trades is an information
checkpoint, **not a ticket**: a row joins only if the resulting desk still passes admission.

**Admission to real money** (signed desk package, while quiescent):
- the skeptical posterior supports **positive net dollars per month** for the desk after running
  costs; and
- the predicted probability of hitting the $1,500 drawdown halt within the next **20 sessions is
  ≤5%** (owner decision 17), under member dependence, +1 adverse tick on every entry and exit, and the
  stop-gap allowance.

**Step 1 (desk pilot):** one MES slot, **$600 loss budget** for the pilot *(call)*. $600 validates
execution and the simulator, not edge: 100 trades of a 1.8R-SD strategy swing about ±$900 at $50
risk.

**Scaling** (a second slot, more contracts, funded accounts): needs selection-controlled
confirmation. Each further slot also needs margin (§8) and its own commissioning; sizes above 1
contract per trade need partial-fill protection designed and tested first.

**Leaving the desk.** An **anytime-valid economic futility test** (is the row's net expectancy
credibly below its hurdle?) and a **live decay alarm** (§6.6) remove a member at the next quiescent
point; it returns to paper observation. There is **no automatic retirement at 250 trades**: modest
real edges need 600–1,000+ trades. A row is retired when futility rejects it or it is superseded.
Statistics cannot remove weak members cheaply, so the checkpoint, not futility, is the main filter.

**Honest power.** At +0.2R gross edge, 3 trades/day and 1.5× clustering, ~600 forward trades (~10
months) give 80% power for a single row; 100 trades is eligibility, not confirmation.

**Selection.** Blindness does not solve selection: with 100 zero-edge submissions, a 5% holdout and
a 20% forward pass rate, there is a ~63% chance of at least one false promotion. Repeated looks make
it worse. The protocol therefore has **one error budget for the whole pipeline**.

**Fixed before the evidence component is built (first spec of the build plan), not left to the
builder:**
- Estimand: **net dollars per session** for the desk and expectancy per trade for each row; a fixed
  overhead allocation that cannot improve by creating more rows.
- Joint session blocks across **all** rows, keeping overlapping signals, market correlation and serial
  dependence, including zero-trade days.
- Skeptical prior, likelihood, heavy-tail assumptions, look schedule and minimum information (not just
  trade counts).
- One selection-aware promotion rule: lifetime false-scaling probability **≤5%**, with error weights
  pre-allocated across candidates and anytime-valid tests within rows.
- The halt-probability model behind the 20-session target; holdout and control tests; the stability
  predicates (§6.6); calibration partitions; treatment of new simulator versions.
- Pipeline simulations reporting false scaling, power, calendar delay, drawdown and dollars under
  zero edges, weak edges, concentrated profits, decay and model error, against numeric acceptance
  targets.

**One bet, not many:** rows on the same market with related mechanisms are not independent evidence.
The desk gets **no diversification credit at admission**; dependence is measured for the halt model.
Size ≤ quarter Kelly, rounded down. Steps down and halts are automatic.

### 6.6 Stability — the policy must survive pre-declared changes
One organizing rule: **qualify the declared policy under predefined perturbations, not only its
fitted path.** Every neighbourhood, block and regime is declared before results are seen.

| Check | Where | Rule |
|---|---|---|
| Parameter plateau | Research | Each tunable number ±20%: ≥80% of valid neighbours profitable after costs, and their median ≥50% of the chosen setting. |
| Deletion survival | Research, holdout, forward | Still profitable after removing the best 5% of sessions, and after removing any one quarter; profitable in ≥3 of 4 chronological blocks. Unsupported blocks = insufficient evidence. |
| Regimes | Research, holdout, forward | Volatility, trend and session slices and the strategy's trading domain declared in advance, using only information available before entry; deletion survival applies across sufficiently populated slices. A specialist need not profit outside its domain. |
| Cost stress | Before admission and scaling | Still above the hurdle with +1 adverse tick on entry **and** exit (+$2.50 per MES trade), at intended size. |
| Decay alarm | Live | A pre-declared one-sided CUSUM on session-level excess profit, aimed at deterioration to the hurdle, with ≤5% false alarms over 250 sessions. An alarm removes the member at the next quiescent point; paper observation continues. |

These rules deliberately reject some legitimate tail-dependent strategies (for example, a momentum
idea whose profit came from a few days).

---

## 7. Payoff shape — what exits can and cannot do

- Stops, targets and trailing stops **reshape** results; on an unpredictable path they cannot create
  expectancy, and costs make it negative. Hence the random-entry control.
- **Costs do not shrink with the stop.** A round trip costs about $3.70 on MES (fees plus one adverse
  tick on each leg): ~7% of a $50 risk but ~19% of a $20 risk. Tight stops need a much larger edge
  per unit of risk.
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
- **Account funding:** the live account holds enough cash for the desk's slots at IBKR's current
  margin plus a stress reserve (at least IBKR's $2,000 minimum equity); deposits stay within the
  $15,000 ceiling. Margin cash is not spent budget. IBKR's published intraday MES margin is about
  $2,000 per contract (indicative, not an account quote), so the incubation can carry **about four
  simultaneous MES trades at most**; version 1 uses one.
- **Risk per trade:** chosen per strategy within **$20–$50** including stressed costs *(call)*; the
  member's cap is part of the desk package. Limits trigger action; fast markets, halts and limit moves
  can jump past them.
- **Account rule (rule 6):** an order is admitted only if the stressed post-fill account state stays
  above today's start −$400, peak −$1,500 and the incubation floor, and within margin. Pending orders
  count. Daily −$400: no entries, flatten. Halt at $1,500 below peak, restored only by signed
  approval. $600 desk-pilot budget at step 1. All from marked equity; peaks survive restarts and are
  not reset by deposits or new packages.
- **Quiet period:** from 2027-06-01 to 2027-08-31 no new deployments, step-ups or funded purchases.
  The running desk continues with its automatic limits, including the rolls its package already
  authorizes. This can delay a qualified desk by up to three months; that cost is accepted.
- **Restore:** a restored installation starts disarmed (rule 5); backups never carry trading
  authority, unused approvals or a lifted halt.
- **Approvals:** signed desk packages (go-live, membership changes, step-up, funded, limit
  restoration, payments). SSH signing from the phone, tested in week 1; passkey later *(call)*.
  Signer anchors live outside the agent-writable tree.
- **Honest expectation (illustrative, not forecasts):**
  - One MES slot can earn useful income, not wealth: a genuine +0.20R edge at 3 trades a day is about
    **$450/month** after running costs.
  - A screened one-slot desk earns roughly **$100–$300/month** in Claude's simulation; an unscreened
    desk hits the halt **~65%** of the time within six months in both Claude's and Astra's models.
  - The chance of a screened desk hitting the halt within six months is **~15–25%** (bounded
    stop/target model) to **~40–90%** (Astra's heavier-tailed model); the 20-session target exists
    because the models disagree.
  - Weighting by the chance candidates are real, expected profit is near **$0 by end-2027 and about
    +$1,000 by end-2028**. Real money comes from scaling a confirmed desk (more slots, funded accounts),
    likely late 2027 into 2028. Most ideas fail; a plausible outcome is a loss of a few thousand
    dollars and a clear "no".

---

## 9. Funded accounts (a later, separate qualification)

- **Verified so far (Nov 2026):** FTMO Futures and FundedNext Futures allow bots and VPS, don't
  restrict Israel, require flat by end of day, run on NinjaTrader / Tradovate / TradingView.
  Tradovate's API excludes prop accounts; Topstep's API needs a personal device; Apex and Take Profit
  Trader ban bots; Tradeify restricts Israel.
- **Stage 0 (ours, by 2027-01-15):** research the exact route (API bridge, then TradingView, then
  manual), hosting, residency, payout and KYC. No funded code in version 1.
- **First challenge** only when the desk (or the strategy routed) passes the **selection-controlled
  confirmation and stability bar** (§6.5–6.6) **and** ≥50 real IBKR trades over ≥20 sessions with clean
  reconciliation and the simulator audit passing. Fifty trades alone prove execution, not edge. The
  route must qualify on its own (platform, automation permission, exact rules). Once a desk is
  confirmed, funded may come **before** adding personal contracts.
- One challenge at a time, ≤$150 each, ≤$300 before the first payout, **$1,000 total** including
  renewals and resets. Buy only if replay under the firm's exact rules shows expected payouts ≥2× all
  fees after halving the payout estimate. Optimise payout, not pass rate.
- Payouts are not brokerage money: firms can void payouts and change terms.

---

## 10. Ideation

**Discovery is the slowest step.** Under illustrative assumptions about 1 in 13 distinct submissions
passes the holdout, so 5–20 passers need roughly 65–260 genuinely different ideas. Research therefore
favours **distinct mechanisms** ("who loses money to us, and why") over variants, and mechanisms that
deliver **net dollars and independent information per session** (several uncorrelated trades a day
lower the running-cost hurdle from 0.15R at one trade a day to 0.05R at three). Repeated bets on the
same move do not count.

Kept from earlier drafts, retargeted to futures: provenance on every idea, an owner Inbox, and a
deterministic duplicate screen. Bandit rewards use **research-window outcomes only** (rule 1); the
bandit itself waits until after version 1.

**First research batch** *(call)*: MES open-to-close continuation with one fixed stop and target,
against random entries. Seed from the Algovibes review: the Zarattini/Aziz/Barbon (2024) noise-band
momentum (survived its random-direction control on NQ only; its profit was concentrated in a few days,
so it must pass deletion survival), retested on **MES research windows only** (before the sealed
holdout), with a daily-stop variant. Other markets wait until after version 1 (§5).

---

## 11. The system

### 11.1 Components (version 1)

| Layer | Parts |
|---|---|
| Outside | IBKR (paper + live accounts), market data, the owner's phone |
| Trusted (holds the keys) | **Executor (desk):** tiny; receives validated proposals from all members, picks by the package's fixed priority when the slot is free, applies the account rule, sends orders with protection, journals, reconciles. Same code for paper and live. |
| Unprivileged | **Strategy worker** (runs every member's code; no network, credentials or database writes) · **Backtester** (research sandbox) · **Holdout judge** (reads only the sealed files) · **Paper observer** (simulator-scores every holdout passer on live prices) |
| Core (pure functions) | Strategy interface (closed bars → proposal with stop and target) · **Simulator** (rows and desk policy) · **Account rule** (stressed post-fill, marked equity) · **Evidence statistics** (§6.5–6.6) |
| Storage | Parquet price files (train / validation / sealed holdout) · one SQLite database (trading side only; research can't read it) |
| Control | JSON command line (kept from today), systemd, execution lock, outside heartbeat, off-server backups with tested restore |

Version 1 scope: **one desk with one MES slot, many observed rows, one IBKR account, fixed stop and
target per trade.** Deferred: a second slot and simultaneous trades, trailing stops, sizes above 1
contract, Kelly sizing, the idea bandit, funded executors and fixtures, multi-market research.
Deleted: per-strategy accounts or budgets, multi-account coordination, a separate watchdog engine,
the old gates and ceremonies.

### 11.2 The executor loop
- Each minute: read the bar and IBKR's positions and orders → strategy worker returns every member's
  proposal → if the slot is free and nothing is unresolved, take the highest-priority valid proposal →
  account rule → send one order package with protection → record. Skipped proposals are recorded as
  skipped, matching the simulator.
- Also reacts instantly to broker events (fills, rejections, cancels, disconnects) and to a timer.
- **Order journal** (rule 3): intent ID written before sending; broker IDs; deduplicated executions;
  commissions. IBKR reports positions per account and contract, not per strategy, so episode ownership
  comes from the journal.
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
  interfere, and rejections and cancels behave (a rejected member does not cancel the others). Also
  prove the **forced-close protocol**: a market order joined to the same OCA group closes the position
  and cancels the resting stop and target without ever reversing it, including existing fills, pending
  cancels, delayed acknowledgements, a rejected child and a gateway outage. Block mode protects only
  within one group; it is not account-wide protection.
- **Commissioning run:** paper cannot certify production behaviour, so before unattended operation a
  short, signed, owner-aware run on the live account at 1 MES confirms the same construction live.
  A second slot needs its own commissioning.
- **Fallback:** ordinary bracket plus an executor-sent timed close, which loses crash-proof timed
  exits. It remains a **live blocker** unless the owner explicitly accepts it in a signed decision.
- Nothing executes during a market halt.

### 11.4 Edge cases (minimal fixes)

| Group | Fix |
|---|---|
| Orders and fills | 1 contract (exits activate only after a full fill); blocked OCA; one episode owns its orders; one slot in v1, so no opposite-side overlaps; never replenish after a stop-out |
| Surprises at the broker | Whole-account check; unexpected state blocks entries and alerts |
| Competing proposals | Fixed priority in the package; skipped proposals recorded identically by simulator and executor |
| Data and clock | Stale or missing bars block signals, never exits; validate timestamps, duplicates, gaps; next-bar execution; Databento vs IBKR overlap checks |
| Session deadline | One dated deadline drives cutoffs, expiries and the timed exit; early closes included |
| Contract rolls | Exact contract on every order; chosen at session start; switched only while quiescent; no trading near expiry |
| Fast markets and margin | Per-member risk cap; stressed account rule with gap allowance; margin checks; funded margin reserve; limits are triggers, not guarantees |
| Program and server | Execution lock; broken database stops entries (IBKR holds exits); tested restore |
| Evidence | Simulator models non-fills, full paths and the desk policy; whole-policy replay; calibration ≠ confirmation |
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
   change; two members proposing in the same minute resolve by priority identically in simulator and
   executor; a simulator change replays the whole policy exactly; unfilled and skipped attempts are
   kept.
4. **Limits, boundaries and backups:** restart after a losing day; a pending entry that would breach a
   floor under stress is refused; deposit without resetting peaks; restore an old backup (starts
   disarmed; no old approval, halt-lift or peak comes back); a second installation tries to trade;
   replay an old approval; edit a limit or membership unsigned; strategy code returns an invalid
   proposal, hangs, or tries to reach the network, credentials or database; research tries to read a
   holdout or desk result. All refused or preserved.

### 11.6 Build
About **3 weeks to a paper prototype with two agents** (history side, broker side); unattended live
follows the commissioning run, not the calendar. The **statistics component spec** (§6.5) is written
first, alongside week 1.
- **Week 1:** broker side starts day 1 with the IBKR protection construction and phone signing;
  history side builds price data, normalization and the simulator; research starts on history.
- **Week 2:** executor (desk with one slot) and strategy worker on IBKR paper with one fixed
  stop-and-target strategy; paper observer for all holdout passers.
- **Week 3:** the four safety tests, then paper trading.

**Build rules *(call)*:** the stock lane may break; the empty research registry may be reset after
archiving. Agent-reviewed changes merge on their own, except changes to the executor boundary, risk
limits and signer anchors, which need the owner's one-tap merge approval (no code reading).

---

## 12. Thesis review

Opens automatically at the first of: the incubation loss budget is reached; **12 months after paper
starts** with no desk passing admission (a fixed observation deadline, not a submission count);
**2028-12-31** without a live desk above its hurdle. It ends in one recorded decision: change approach,
change scale, or stop. Adding features is not an allowed outcome.

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
| Dec 2026 (~3 weeks) | **1. Build** to a paper prototype (§11.6); statistics spec first; research on history from week 1 | Data ≤ $200 |
| Jan 2027 | **2. Paper** (≥10 clean sessions) → commissioning run → **desk pilot** if a desk passes admission | $600 desk pilot |
| Feb – May 2027 | **3. Discovery and parallel forward evidence;** desk membership grows by signed packages | Within account limits |
| Jun – Aug 2027 | **Quiet period:** no new deployments, steps or purchases | Running desk only |
| Sep 2027 – Dec 2028 | Confirmation; second slot, funded and more contracts on evidence | Within the $15k budget |

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
2. Daily loss $400; halt at $1,500 below peak.
3. Risk per trade chosen per strategy within **$20–$50**.
4. The $600 step-1 budget applies to the **desk pilot**, not to each strategy.
5. Funded fee cap $1,000; one challenge at a time; ≤$150 each.
6. Session deadline: the earlier of 15:00 CT and the early close.
7. Live data from IBKR; history from Databento ≤ $200.
8. Holdout bar 5% one-sided; member checkpoint at ≥100 forward trades; anytime-valid futility and a
   CUSUM decay alarm instead of the 250-trade expiry; lifetime false-scaling ≤5%.
9. Stability thresholds: ±20% plateau with 80%/50%; best-5% and any-quarter deletion; 3 of 4 blocks;
   +1 tick each way.
10. Stage derived from evidence rather than stored.
11. Owner one-tap merge approval only for the executor boundary, risk limits and signer anchors.
12. Stock lane frozen and allowed to break; empty registry may be reset after archiving.
13. SSH signing first; passkey later.
14. Version 1: one slot, fixed stop and target; a second slot, trailing stops and sizes above 1
    contract are deferred.

---

## 17. Approaches considered

| Decision | Chosen | Rejected and why |
|---|---|---|
| What the system is for | Intraday futures for funded payouts | Daily stocks: can't make the owner rich at $15k |
| Architecture | Lean new core, tiny trusted executor, broker-held exits | Refactor of the stock platform; Astra's first design (too slow, too much machinery) |
| Code authority | Strategy code unprivileged; only proposals cross (rule 7) | "Pure functions" inside the credentialed runner: unenforced |
| Holdout leakage | Blind holdout (rule 1) | Per-idea shot counts; ≤10 candidates at 1% (rejects about half of real +0.10R edges that pass at 5%) |
| Paper vs live evidence | One simulator scores every signal and the desk (rule 2) | Separate scores; paired gap adjustments |
| How many strategies trade | **The desk:** many members, one executor, one slot first, the desk qualifies as a whole | One strategy live at a time (serializes evidence and income); **independent strategies each with its own daily budget** (owner's first proposal, Astra pool review: margin fits only ~4 MES, the $1,500 halt binds long before the daily budget, netted strategies can leave a working stop that opens an unmanaged position, and unscreened pools halt ~65% of the time) |
| Entry to real money | Parallel paper observation, 100-trade checkpoint, desk admission with a ≤5% 20-session halt target | Every holdout passer trades (only ~39% genuine; nulls bleed ~$3.70 a trade) |
| Retirement | Anytime-valid futility + decay alarm | Fixed 250-trade expiry (discards modest real edges) |
| Execution truth | Broker state + small journal + one episode | Broker state alone (ambiguous after downtime); full order framework |
| Exits | Entry × exit × sizing with a random-entry control | Exit tuning alone: cannot create edge |
| Funded route | Our own research; API → TradingView → manual | Waiting on firms' confirmation; home rig for Topstep |
| Stages | Research → holdout → paper → live (ladder) | Separate pilot and funded stages; a "freeze" step |
| Personal broker | IBKR with a weekly login | Tradovate API (unverified for unattended use); Alpaca (no futures) |

## 18. Left to the builder

Exact simulator parameters per contract, the stop-gap allowance, roll timing, module layout, schema
and test fixtures, each fixed in its component spec and covered by tests. Funded rule-set fixtures
(FundedNext 50K Rapid first) wait for the funded milestone. The evidence statistics are **not** left
to the builder (§6.5).
