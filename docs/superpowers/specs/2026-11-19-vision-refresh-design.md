# Vision refresh — intraday futures for funded payouts

**Status:** Draft for owner approval · **Date:** 2026-11-21 (rewrite) · **Owner:** Lior Nisimov
**Origin:** owner design session ("roadmap"), 2026-11-16 → 2026-11-21, with Codex and Grok reviews,
a Codex-vs-Grok debate on futures, and a Codex simulation of prop-firm rules.
**Supersedes:** the 2026-11-19 draft of this file (commit `1bbae69`), whose daily-stock historical-
holdout design was rejected after outside review (§16).

This document records owner decisions that amend the [PRD](../../PRD.md). Once approved, the PRD,
operating guides and agent instructions are updated to match (§14). Until the code below is built and
accepted, operating guides keep describing what the code enforces **today**; every unbuilt item is a
target linked to its work card. Items marked **OPEN** need an owner answer (§15). Items marked
*(call)* were settled by Claude and can be overridden.

---

## 1. Intent

**North star: make the owner rich from trading profit, as soon as honestly possible.** The owner is a
capital allocator, not a reviewer: no human code review, no recurring decisions, one-tap approvals only
where real-money authority requires a human.

The binding constraint is capital, not ideas. A real edge on the owner's ~$15k earns little; funded
prop accounts give $50k–150k of trading size per account for a fee. Every funded program that allows
bots, accepts Israeli residents and is verified so far requires being **flat by the end of the trading
day**. So Algua becomes an **intraday futures system** whose product is a frozen strategy that:

```
history screen ─► freeze ─► shadow (no money) ─► personal pilot (real fills, small) ─► scale
                                                                   └─► funded accounts (payout multiplier)
```

The personal account is the **evidence**; funded accounts are the **multiplier**. A funded pass is never
evidence. Client money is out of scope until a multi-year audited record and legal clearance exist.

### Goals
- Find intraday futures edges that survive stressed costs on data generated **after** the freeze.
- Replay every candidate under each funded firm's exact rules, so "passes and stays funded" is measured
  before any fee is paid.
- Keep every loss cap in code; grow capital only on affirmative post-freeze evidence.
- Keep operating cost near **$150/month**.

### Non-goals
- Daily or multi-day stock trading (lane frozen, §12). Forex spot. Options. Crypto.
- Proving an edge by a deadline. No date lowers a bar.

### Anti-goals (failure even if it "works")
- Scaling the luckiest of many experiments without a repeat on new data.
- Treating backtests, leaderboards or challenge passes as proof.
- Any mechanism needing routine owner attention (including weekly logins, §10).
- Strategies whose risk is hidden (martingale, grid, averaging down, no stop).

---

## 2. Owner decisions recorded in this session

1. Cut operating cost to ~$150/month (measure current spend first).
2. Replace the "prove it on history" gate with a decision framework: small, capped, expiring real-money
   pilots buy information; scaling needs affirmative post-freeze evidence; size ≤ quarter Kelly.
3. Speed comes from **breadth** — redefined by the pivot as distinct futures markets and distinct
   setups, not daily stocks (the earlier "broad daily equities" item is superseded).
4. **Pivot:** Algua is built for intraday futures aimed at funded payouts; rebuilding machinery is
   acceptable.
5. The research engine searches **entry × exit × sizing** (stops, trailing stops, targets,
   reward-to-risk, win rate), under the honesty rules in §6.
6. USD everywhere; owner deposits USD. Owner approves every payment.
7. Passkey (WebAuthn) one-tap approvals; SSH signature as backup.

---

## 3. Vocabulary (minimal)

| Word | Meaning | Question it answers |
|---|---|---|
| **research** | Building and tuning on history (train + validation windows). Free iteration, every variant counted. | "Is it worth freezing?" |
| **freeze** | Code, parameters, cost model, rule set and scoring plan hashed. Any later change = new strategy. | "Is it the thing we're scoring?" |
| **shadow** | Frozen strategy runs on live market data with no money; every trade is scored. | "Does it work on data nobody had seen?" |
| **pilot** | Frozen strategy on the personal account at minimum size with a loss budget and expiry. | "Do real fills and costs match?" |
| **live** | Personal account above pilot size, scaled by evidence. | "Is it still good?" |
| **funded** | A live strategy also running on prop accounts. A deployment, not a stage. | "Does it pay out?" |
| **trial** | One frozen strategy entering shadow. Counted for life. | — |

**Lifecycle:** `idea → research → shadow → pilot → live → retired`, plus `dormant` (benched; can return).
**OPEN (§15.5):** the owner chose "holdout" as a stage name in the earlier draft; with no historical
gate that stage disappears. Proposed: `shadow` takes its place.

**Dropped:** holdout (as a gate), forward / forward-tested / forward certificate, strict and capped
routes, probation, the 63-bar floor, the five-session qualification, t ≥ 3.72, N = 500, the dual
benchmark, the decay rule, the "not falsified" ladder.

---

## 4. Markets and data

- **Instruments:** CME-group micro futures first (MES, MNQ, M2K, MYM, MGC, SIL, MCL, micro
  Treasury/FX futures where liquid). E-mini sizes only after evidence and only where a funded rule set
  needs them.
- **Breadth:** MES, MNQ, MYM and M2K move largely together; they count as close to one bet. Breadth
  comes from equity-index + rates + metals + energy + FX and from setups with different mechanisms.
- **Session rule:** every strategy is flat by a configurable time before the close (default 15 minutes
  before the earliest funded flat-by time). One frozen strategy therefore runs unchanged on personal
  and funded accounts.
- **Data:** minute (or finer) bars per contract with roll metadata from one vendor (Databento assumed
  *(call)*; historical spend capped at **$200** without a new owner approval). CME calendars,
  holidays and early closes. No survivorship or delisting problems exist for futures; continuous
  series are built from contracts with an explicit roll rule.
- **Windows:** history is split into train and validation for research only. History is a **screen**,
  never proof: intraday patterns are heavily published and known to AI models, so only post-freeze data
  counts as evidence.

---

## 5. Evidence design

### 5.1 Research (history)
Allowed freely on train/validation: walk-forward, sweeps, error analysis. Required before freeze:
1. **Stressed costs:** commission + ≥1 tick slippage per side on MES-class contracts (more on thinner
   ones), extra slippage on stops, opens, news and forced flat exits.
2. **Random-entry control:** the same exit and sizing on time-matched random entries. A strategy that
   does not beat its own random-entry control has no entry edge, whatever its win rate.
3. **Prop-rule replay:** intratrade equity replayed under each target firm's rule set (§7), giving
   estimated pass and first-payout probabilities.
4. **Deflated Sharpe** reported as advisory, with the lineage's full variant count.

### 5.2 Trial accounting
- The trial family is **entry × exit × sizing**. Every variant the research CLI runs is logged to its
  lineage, including discarded ones. Agents cannot run research outside the CLI.
- At most **6 strategies in shadow at once** *(call)*, chosen to differ in mechanism and market.
- Shadow results never flow back into research inputs, idea scorecards or bandit rewards until the
  strategy leaves shadow (pass or kill), to keep agents from tuning on shadow data.

### 5.3 Shadow scoring
- Unit: net dollar result per trade at pilot size, after stressed costs.
- Estimate: Bayesian posterior on expectancy per trade with a **skeptical prior** (most mass at ≤ 0;
  published intraday effects shrunk by about half). Prior, cost model, hurdle and horizon are frozen
  with the strategy.
- Dependence: trades are grouped into session blocks; uncertainty uses block bootstrap or clustered
  errors.
- **Enter pilot** when: ≥ 100 post-freeze trades *(call)*, posterior probability of positive net
  expectancy ≥ 70%, and the prop-rule replay of the shadow path does not breach.
- **Kill** when the posterior probability of positive net expectancy falls below 20%, or after 250
  trades without reaching the pilot bar.

### 5.4 Pilot (personal real money)
- Minimum size (one micro contract per signal).
- **Loss budget OPEN (§15.2)** and expiry of 90 sessions; hitting either ends the pilot automatically.
- Mechanics must hold: every order resolved, zero ledger/broker difference each session, flat by the
  rule time every day, one forced restart during an uncertain order survived, roll handled.
- Real-cost check: realised slippage and fees vs the frozen cost model; a material breach pauses the
  pilot.

### 5.5 Scale (live)
- Requires affirmative evidence on post-freeze trades (shadow + pilot combined): posterior 20th
  percentile of net expectancy per trade above the hurdle, where the hurdle covers fees, stressed
  slippage and the strategy's share of running costs.
- Honest sample sizes: a 30% win-rate / +3R profile has a per-trade spread of ~1.8R and needs about
  **320–520 post-freeze trades** to confirm a +0.2R edge; high-win-rate profiles need fewer.
- **Wave-2 rule:** a strategy selected as the best of a batch repeats at the same size on new data
  before its first step up.
- Size ≤ quarter Kelly on the shrunk estimate; steps add one contract at a time; a step up needs owner
  passkey approval; step-downs and benching are automatic.

---

## 6. Payoff shape — what exits can and cannot do

- Stops, targets and trailing stops **reshape** the distribution of trade results; on a price path with
  no predictability they cannot create positive expectancy, and costs make it negative. An exit adds edge
  only when the trade's path predicts what comes next (trend persistence) or when it cuts costs.
- Low win rate with large winners is genuinely profitable where moves persist (futures trend following,
  multi-month evidence). Whether that survives a flat-by-close constraint is an open research question.
- Funded trailing-drawdown rules favour **smooth equity**. Codex's simulation of FundedNext 50K Rapid
  rules ($2,000 trailing drawdown, $1,000 daily loss, equal +0.20R expectancy, $400 risk per trade):

  | Profile | Breach before first payout once funded | Evaluation → first payout |
  |---|---|---|
  | 30% win rate, +3R winners | ~50% | ~22% |
  | 80% win rate, +0.5R winners | ~3% | ~94% |

- Consequence: research optimises net expectancy **and** funded survival. Low-win-rate trend strategies
  remain valid for the personal account; funded deployment prefers small risk per trade and high win
  rate.
- Leaderboards (Myfxbook, MQL5, Collective2, TradingView) are selection-biased idea sources, never
  evidence.

---

## 7. Funded accounts

- **Verified so far (Nov 2026, firms' own pages):** FTMO Futures and FundedNext Futures permit
  automated trading and VPS use and do not list Israel as restricted; both require flat by end of day.
  Topstep's API requires orders from a personal device; Apex and Take Profit Trader ban bots; Tradeify
  restricts Israel. FTMO's CFD Swing account allows multi-day holds but trades CFDs, not this book.
- **Rule sets as data:** trailing/max drawdown (and how it trails), daily loss limit, flat-by time,
  contract caps, consistency rules, payout buffers and minimums, news restrictions. One format, evaluated
  per tick in replay, shadow and live; the same rule set gives the same verdict everywhere.
- **Deploy to funded** only when: the strategy is live with affirmative evidence (§5.5); replay of its
  post-freeze path under the exact rules gives a positive expected collectible payout after fees; the
  firm's current automation, VPS and country terms are confirmed in writing that week.
- **Copies across accounts** are allowed only where the firm's rules permit; they are modelled as
  breaching together on the same bad day. Per-firm account caps are verified before any multi-account
  projection is shown.
- **Fee cap OPEN (§15.3).** A failed challenge is not retried without a new replay.
- Payouts are not brokerage money: no customer protection; firms can void payouts; terms change. The
  owner handles tax reporting.

---

## 8. Ideation and the signal library

Kept from the earlier draft and retargeted to futures: ideas become library signals; strategies are
frozen combinations; deterministic admission (falsifiable mechanism, horizon, data feasibility,
duplicate screen); immutable lineage ledger; equal rotation across category × source arms, then
Thompson sampling with a randomized exploration floor; staged rewards using research-window outcomes
only; data wishlist. Owner Inbox ideas enter a bounded priority queue.

**First research batch** *(call)*: MES opening-to-close continuation (Codex's proposal) compared across
fixed-time exit, hard stop and volatility trailing stop at equal dollar risk, against random entries;
then one setup each in rates, metals and energy. Outside sources (including YouTube channels) feed
hypotheses only.

Seeds from the Algovibes channel review (2026-11-21; weak-to-moderate evidence, a seller of a paid
community with an incentive to debunk):
- The Zarattini/Aziz/Barbon (2024) intraday noise-band momentum strategy on NQ (30-minute checks,
  band/VWAP exit, flat at close) was the only intraday result that survived its random-direction
  control (t ≈ 2.6 over 1,564 trades, ~41% win rate). It failed on ES, YM and RTY; profits were
  concentrated in a few days; and its −$3,601 drawdown on one micro would have breached a ~$2,000
  funded trailing drawdown. Hypotheses: it stays positive on MNQ after 2024-05 net of 2 ticks; a
  half-size or daily-stop variant cuts funded breaches without erasing expectancy.
- Cautions adopted as research rules: placebo-test the random-entry control itself (a biased random
  benchmark made placebo exits look like +0.8% per trade); expect in-sample selections to collapse
  (31.5%/yr → 1.3%/yr out of sample in one replication); a zero-edge Topstep-style challenge still
  passes ~40% of the time, so measure payouts against fees, never pass rates.

**Model-derived features:** the earlier rules stand — anonymised local tasks only with a verifiable
cutoff and leak probe; knowledge tasks and models with unverifiable cutoffs are shadow-only, which in
this design means they can never skip shadow.

**Provenance:** every idea records its source, publication date and developing model.

---

## 9. Capital and risk

- **Account ceilings:** $15,000 total at risk during the incubation period; $60,000 after a signed
  owner change. Changing any ceiling or cap is a signed policy change.
- **Personal futures account:** a new IBKR account (or another futures broker; see §10). Futures need
  at least $2,000 equity plus margin.
- **Hard limits in code and at the broker:** per-strategy loss budget; account daily loss limit; account
  flatten at a fixed drawdown; broker-held protective stops behind every position; forced flat by the
  rule time.
- **No new pilots or step-ups from 2027-06-01 to 2027-08-31** (birth window). Running strategies keep
  their automatic stops.
- **Approvals:** passkey on the owner's phone for pilot start, step-ups, funded deployment and payments;
  SSH signature as backup. The server stores only public keys. Approval binds strategy identity,
  account, instruments and exact USD amount.
- **Honest expectation:** each MES round trip costs about $2.50–5; with ~$150/month running costs over
  ~500 trades a year, average gross profit per trade must exceed roughly **$6–9** to break even. Most
  intraday ideas are expected to fail; a plausible two-year outcome is a loss of a few thousand dollars
  and a clear "no".

---

## 10. Machinery to build

| Part | Notes |
|---|---|
| Instrument model + signed positions | Multiplier, tick, margin, sessions, roll rule; long/short everywhere. Existing short refusals become one policy check. |
| Futures data | Vendor adapter, contract history with rolls, continuous series, CME calendar with early closes. |
| Intraday loop | Bar-driven decision loop within the session, durable state, restart reconciliation against the broker, forced flat-by. |
| Personal broker adapter | **New**: the repo's only broker is Alpaca, which does not offer futures. IBKR is the default *(call)*. IBKR's Gateway needs periodic re-authentication; the design must remove that weekly owner action or switch broker. |
| Funded order route | **Stage-0 blocker.** FTMO Futures and FundedNext run on NinjaTrader, Tradovate or TradingView; Tradovate's API excludes prop accounts. The likely route is a NinjaTrader bridge on a Windows machine. Feasibility, cost and the firms' acceptance of it must be confirmed before any funded code. |
| Rule-set engine | One format for personal and funded rules; same verdict in replay, shadow, pilot and live. |
| Shadow scorer | Post-freeze trade ledger, Bayesian estimate, kill/enter decisions, owner dashboard view. |
| Cost meter | Monthly data, LLM, server and fee cost beside P&L. |

**Acceptance invariants** (the safety net, since the owner does not review code): cash plus marked
positions conserved through long and short round trips after fees; zero ledger-versus-broker difference
after long, short, partial-fill, roll and restart scenarios; flat at the rule time in every replayed and
live session; same rule-set verdict in replay and live on the same data; a strategy cannot trade without
a matching frozen identity and approval.

Rough effort *(call)*: 4–8 agent weeks to one IBKR micro contract through paper acceptance; 2–4 weeks per
funded route once the route is confirmed.

---

## 11. Thesis review

Opens automatically at the first of: 40 frozen trials with none reaching pilot; 12 months after the
intraday loop is accepted with no strategy past pilot; 24 months of running cost with no live strategy
above its hurdle. The review diagnoses (costs, data, power, funnel losses) and ends in one recorded
decision: change approach, change scale, or stop. Adding features is not an allowed outcome.

---

## 12. Migration

- **Daily stock lane: frozen** *(call)*. Code stays; timers and paid stock data stop; no new work.
  Delete later if unused for a year.
- The old gates (`paper promote`, forward certificates, `forward_tested`, the 63-bar floor, capped
  route ceremonies) are removed when the new lifecycle lands; identity-bound evidence replaces the
  forward certificate before its precondition in `algua/registry/transitions.py` is removed.
- Kept: layered account risk, SSH signing (backup), single-use identities, the `t → t+1` rule, the JSON
  CLI contract.
- Legacy stock research is archived to the owner's private Drive and removed from agent-reachable
  locations (as decided earlier); it does not touch futures research.
- Verified on the VPS on 2026-11-20: zero strategies in the research and paper registries; no
  paper/live operator units; only paper broker credentials. No draining is needed.

---

## 13. Stages and timeline

| When | Stage | Money at risk |
|---|---|---|
| Dec 2026 | **0. Verify and cut:** measure and cut cost to ~$150/month; confirm the funded order route, per-firm account caps, IBKR futures account and re-auth handling. | None |
| Dec 2026 – Feb 2027 | **1. Build:** data, instrument model, intraday loop, IBKR adapter, rule engine, shadow scorer. Research on history in parallel. | Data ≤ $200 |
| Feb – May 2027 | **2. Shadow → first pilots.** First frozen batch in shadow; pilots start when the bar is met and the start month is approved (§15.1). | Pilot budgets |
| Jun – Aug 2027 | **Birth window:** no new risk. | Running pilots only |
| Sep 2027 + | **3. Scale and funded:** wave-2 repeats; step-ups on evidence; first funded challenge if §7 holds. Honest earliest funded scaling: **month 9–12**. | Ladder + fee cap |

Work in progress: two parallel tracks against frozen interface contracts (data/loop/broker, and rule
engine/shadow scorer). Agent review only.

---

## 14. Context-file and board updates (after approval)

- **PRD:** owner amendment with this document's decisions (north star, market, vocabulary, evidence,
  capital in USD, funded path, stages, thesis triggers), replacing the stock-first phase list.
- **CLAUDE.md, AGENTS.md, README, `docs/agent/*`, `.opencode/agents/*`, `.opencode/skills/*`:** adopt the
  vocabulary; describe the stock lane as frozen; mark unbuilt items as targets with their cards.
- Personal financial context never enters this public repository; only the capital rules do.
- **Todoist (Algua):** retire old-route and stock-lane cards; add cards in §13 order with dependencies.

---

## 15. OPEN — owner decisions needed

1. **First personal pilot start:** month 1 (Grok), month 3 (Claude), or month 6 (Codex) after the
   machinery is accepted.
2. **Pilot loss budget per strategy:** $250 (Codex), $600 (earlier draft), or $2,000 (Grok).
3. **Funded fee cap over two years:** $300 (Codex), $1,000 (Grok), or $1,500.
4. **Personal broker:** IBKR (default), given its periodic re-authentication; or another futures broker
   with an unattended API.
5. **Stage name:** replace "holdout" with `shadow` (proposed), or another name.

---

## 16. Approaches considered

| Decision | Chosen | Rejected and why |
|---|---|---|
| What the system is for | Intraday futures for funded payouts | Daily stocks: cannot make the owner rich at $15k even with an edge; FTMO CFD Swing: CFDs, financing costs, thin universe |
| Evidence | Freeze, then score only post-freeze trades | Sealed 2018–2025 stock holdout: contaminated by AI-model knowledge and prior research; t ≥ 3.72 had almost no power |
| Scaling | Affirmative posterior evidence, wave-2 repeat, quarter Kelly | "Not falsified" ladder: lets a zero-edge strategy climb |
| Exits | Search entry × exit × sizing with a random-entry control | Exit tuning alone: cannot create edge on unpredictable paths |
| Funded payoff shape | Optimise for funded survival as well as expectancy | Leaderboard-style low win rate: ~22% evaluation-to-payout vs ~94% at equal expectancy |
| Funded route | Wait for a confirmed bot + server route | Home rig for Topstep: an internet outage near the close breaches the account and pages the owner |
| Personal futures timing | OPEN (§15.1) | — |

## 17. Left to the builder

Exact cost-stress parameters per contract, the Bayesian prior family, block length for dependence,
roll rule details, file and module layout, schema design, and test fixtures (FundedNext 50K Rapid rules
from Codex's simulation are the first rule-set fixture) — each fixed in its component spec and covered
by tests before acceptance.
