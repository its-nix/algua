# Vision refresh — intraday futures for funded payouts

**Status:** Draft for owner approval · **Date:** 2026-11-21 (rewrite, revision 2) · **Owner:** Lior Nisimov
**Origin:** owner design session ("roadmap"), 2026-11-16 → 2026-11-21, with Codex and Grok reviews,
a Codex-vs-Grok debate on futures, a Codex simulation of prop-firm rules, a builder check, and a
second hostile Codex + Grok review (both: "approve Stage 0 only; fix the bars, hurdle and route").
**Supersedes:** the 2026-11-19 draft of this file (commit `1bbae69`), whose daily-stock historical-
holdout design was rejected after outside review (§16).

This document records owner decisions that amend the [PRD](../../PRD.md). Once approved, the PRD,
operating guides and agent instructions are updated to match (§14). Until the code below is built and
accepted, operating guides keep describing what the code enforces **today**; every unbuilt item is a
target linked to its work card. Items marked *(call)* were settled by Claude and can be
overridden by the owner (§15 lists them).

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
- Keep operating cost near **$150/month** (live market data from the broker, not a separate vendor).

### Non-goals
- Daily or multi-day stock trading (lane frozen, §12). Forex spot. Options. Crypto.
- Proving an edge by a deadline. No date lowers a bar.

### Anti-goals (failure even if it "works")
- Scaling the luckiest of many experiments without a repeat on new data.
- Treating backtests, leaderboards or challenge passes as proof.
- Any mechanism needing routine owner attention beyond the accepted weekly broker login (§10).
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
8. **No funded route → personal futures only.** If no firm confirms a bot-from-our-server route in
   writing by 2027-01-15, Algua continues as a personal intraday futures system with its own budget
   and stop date (§11); funded is revisited when a route appears.
9. **Flat by end of day for every strategy, personal included,** for now. Overnight strategies may be
   added later as new strategies with their own evidence.
10. **Personal broker: IBKR**, accepting a weekly login (§10).
11. **Pilot loss budget: $600 per strategy.**

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
*(call)* The owner chose "holdout" as a stage name in the earlier draft; with no historical gate that
stage disappears and `shadow` takes its place.

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
- **Session rule (owner decision):** every strategy is flat by its frozen cutoff, default **15:00 CT**
  *(call)* — before FundedNext's 15:10 CT and FTMO's 16:10 ET (15:10 CT) flat times. The cutoff and an
  entry blackout before it are part of the frozen identity; a different schedule is a new strategy.
- **Data:** historical minute bars per contract with roll metadata from Databento (usage-based;
  capped at **$200** without a new owner approval). **Live data comes from the IBKR account's CME
  subscription** *(call)*, because Databento's live CME plan ($199/month) alone breaks the budget.
  Replay uses minute bars with conservative intrabar ordering (stop before target; trailing-drawdown
  peak taken at the bar's worst point) *(call)*; tick data is bought only if measured replay-versus-
  live disagreement requires it. Raw contract data, roll decisions, rule versions and seeds are pinned
  so every decision can be reproduced. CME calendars,
  holidays and early closes. No survivorship or delisting problems exist for futures; continuous
  series are built from contracts with an explicit roll rule.
- **Windows:** history is split into train and validation for research only. History is a **screen**,
  never proof: intraday patterns are heavily published and known to AI models, so only post-freeze data
  counts as evidence.

---

## 5. Evidence design

### 5.1 Research (history)
Allowed freely on train/validation: walk-forward, sweeps, error analysis. Required before freeze:
1. **Stressed costs:** commission and exchange fees (~$1.22 per MES round turn at IBKR) plus ≥1 tick
   slippage per side on MES-class contracts (more on thinner ones), extra slippage on stops, opens,
   news and forced flat exits.
2. **Random-entry control:** the same exit and sizing on time-matched random entries; the control itself
   is placebo-tested. A strategy that does not beat its control has no entry edge, whatever its win rate.
3. **Prop-rule replay** (when a funded route exists): intratrade equity replayed under the target
   firm's full rule set (§7) **at the contract count and dollar risk that would actually be sent to
   that firm**, giving estimated pass, first-payout and collectible-dollar figures.
4. **Deflated Sharpe** reported as advisory, with the lineage's full variant count.

### 5.2 Trial accounting
- The trial family is **entry × exit × sizing**. Every variant the research CLI runs is logged to its
  lineage, including discarded ones; agents cannot run research outside the CLI. Ideas taken from
  published or online sources record that source, since their search happened outside Algua.
- At most **6 strategies in shadow at once** *(call)*, chosen to differ in mechanism and market. Agents
  freeze strategies, fill shadow slots and kill strategies on their own.
- Shadow and pilot results never flow back into research inputs, idea scorecards or bandit rewards
  while the strategy or any descendant is still being scored; dates a researcher has seen are burned
  for descendants' confirmation.

### 5.3 Shadow
- Unit: result per trade in R and in dollars at one micro, net of the cost model in §5.1. Running
  costs are charged at scale and funded decisions, not per trade.
- Fills are simulated internally under the stressed cost model on live broker data *(call)*; the IBKR
  paper account is used for mechanics only (§5.4).
- Estimate: Bayesian posterior on expectancy per trade with a **skeptical prior frozen in the
  component spec before the first freeze**; trades are grouped into session blocks.
- **Calibration before the first pilot:** the whole rule (entry bar, kill rule, repeated looks,
  correlated variants) is simulated under zero-edge and weak-edge campaigns; the zero-edge pilot-entry
  rate and the expected number of false pilots per year are published on the dashboard.
- **Enter pilot** (an explicit, capped information buy — roughly 30% of zero-edge strategies are
  expected to get in): ≥ 100 post-freeze trades over ≥ 40 sessions, posterior P(net expectancy > 0)
  ≥ 70%, and, if a funded route exists, a passing replay for at least one target firm.
- **Kill** when P(net expectancy > 0) falls below 20% after at least 60 trades, or after 250 trades
  without reaching the pilot bar.
- Shadow keeps scoring throughout pilot and live.

### 5.4 Paper acceptance and pilot
- **Paper acceptance (once per executor version, before any cash order):** on the IBKR paper account,
  every order resolved; zero ledger/broker difference each session; partial fills; disconnect and
  stale-feed recovery; flat by cutoff every day; forced restart during an uncertain order; roll handled.
- **Pilot:** one micro contract per signal on the personal account; **$600 loss budget** and **90
  sessions**; either ends the pilot automatically. Starting a pilot needs the owner's signed approval.
- Real-cost check: realised fees and slippage against the frozen model; a material breach pauses the
  pilot.
- **Expiry without a verdict** returns the strategy to shadow-only; it may start a second pilot (new
  approval) once it again meets the entry bar on trades after the first pilot ended. Maximum two pilots
  per strategy.

### 5.5 Scale (live)
- **Pilot → live is the first step-up** and needs owner approval.
- The scale decision uses **only trades after the pilot-entry decision** (shadow and pilot together),
  so the streak that crossed the entry bar is not counted twice.
- Requires: posterior 20th percentile of net expectancy above the hurdle, where the hurdle covers fees,
  stressed slippage and the strategy's share of running costs at the intended size; at least 100 real
  pilot fills matched to the cost model.
- **Wave-2 rule:** the batch is the set of strategies that entered pilot in the same calendar quarter;
  the one selected for scaling must re-meet the pilot bar on ≥ 100 trades taken after its selection.
- Honest sample sizes: a 30% win-rate / +3R profile (per-trade spread ~1.8R) needs about **520
  independent trades** for 80% power on a +0.2R edge; clustering and a positive hurdle need more. At
  one trade per session that is about two years, so throughput comes from strategies that trade
  several times per session and from unrelated markets.
- Size ≤ quarter Kelly on the shrunk estimate, rounded **down** to whole contracts; steps add one
  contract; step-ups need owner approval; step-downs and benching are automatic.

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
  Both run on NinjaTrader, Tradovate or TradingView. Tradovate's retail API excludes prop accounts;
  Topstep's API requires orders from a personal device; Apex and Take Profit Trader ban bots; Tradeify
  restricts Israel. FTMO's CFD Swing account allows multi-day holds but trades CFDs, not this book.
- **Stage 0 go/no-go (deadline 2027-01-15):** a firm confirms in writing the exact route (most likely
  NinjaTrader with a NinjaScript executor on a Windows server), hosting, Israeli residency, copying
  across accounts, payout and KYC workflow; then a demonstration on the actual account type shows
  unattended order, cancel, reconnect and flatten. No funded code is written before this passes. If it
  fails, Algua is personal-futures-only (§2.8).
- **Two executors:** the Python executor (IBKR) and, if the route passes, a NinjaScript executor.
  Order-level parity tests between them run before any fee is paid.
- **Rule sets as data:** trailing/max drawdown (and how it trails), daily loss limit, flat-by time,
  contract caps, consistency and news rules, payout buffers, minimums and caps. One format, the same
  verdict in replay, shadow and live.
- **Deploy to funded** only when: the strategy is live with affirmative evidence (§5.5); replay of its
  post-entry path under the exact rules at the size to be sent gives positive expected collectible
  dollars after fees, the firm's split, payout buffers and a haircut for discretionary voids; the
  firm's current terms are confirmed in writing that week.
- **Copies across accounts** only where the firm permits; modelled as breaching together on the same
  bad day; no cross-account hedging. Per-firm account caps are verified before any multi-account
  projection is shown.
- **Fees:** cap **$1,000 over two years including monthly evaluation subscriptions and resets**
  *(call)*; subscriptions are cancelled the day an attempt ends; no retry without a new replay.
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

- **Incubation budget *(call)*: $15,000 maximum cumulative net loss over the incubation period,**
  counting realised and open trading losses, broker and exchange fees, funded-program fees and Algua's
  running costs. Reaching it halts all trading and opens a thesis review. Money deposited at the
  broker is also capped at $15,000. Raising either needs a signed owner change; the earlier $60k
  escalation is removed from the incubation policy.
- **Account limits *(call)*:** personal account daily loss limit **$400** (no new entries, open
  positions flattened); account flatten and halt at **$1,500** below its peak, restored only by owner
  approval. Per-strategy pilot budget **$600** (owner decision). Concurrent pilots are limited so the
  sum of open pilot budgets fits the remaining incubation budget.
- **Hard limits in code and at the broker:** broker-held protective stops behind every position;
  forced flat by the cutoff; a trade whose single micro would exceed the remaining allowance is skipped.
  Drawdown state is durable across restarts.
- **No new pilots or step-ups from 2027-06-01 to 2027-08-31** (birth window). Running strategies keep
  their automatic stops.
- **Approvals:** the owner signs pilot start, step-ups, funded deployment, limit restoration and
  payments. The existing SSH signature serves first pilots; passkey (WebAuthn) replaces it as the
  primary method later *(call)*. The server stores only public keys; signer anchors live outside the
  agent-writable tree. Approval binds strategy identity, account, instruments and exact USD amount.
- **Honest expectation:** most intraday ideas are expected to fail; a plausible two-year outcome is a
  loss of a few thousand dollars and a clear "no".

---

## 10. Machinery to build

| Part | Notes |
|---|---|
| Instrument model + signed positions | Multiplier, tick, margin, sessions, roll rule; long/short everywhere. Existing short refusals become one policy check. |
| Futures data | Vendor adapter, contract history with rolls, continuous series, CME calendar with early closes. |
| Intraday loop | Bar-driven decision loop within the session, durable state, restart reconciliation against the broker, forced flat-by. |
| Personal broker adapter | **New**: the repo's only broker is Alpaca, which does not offer futures. IBKR (owner decision). IB Gateway needs a manual login about weekly: the dashboard pushes a reminder; while unauthenticated, no new entries are taken and broker-held stops protect open positions. |
| Funded executor | Only after the Stage 0 go/no-go (§7): NinjaScript executor on a Windows server with parity tests. |
| Paper acceptance harness | Scenario runner for §5.4 on the IBKR paper account. |
| Rule-set engine | One format for personal and funded rules; same verdict in replay, shadow, pilot and live. |
| Shadow scorer | Post-freeze trade ledger, Bayesian estimate, kill/enter decisions, owner dashboard view. |
| Cost meter | Monthly data, LLM, server and fee cost beside P&L. |

**Acceptance invariants** (the safety net, since the owner does not review code): cash plus marked
positions conserved through long and short round trips after fees; zero ledger-versus-broker difference
after long, short, partial-fill, roll and restart scenarios; flat at the rule time in every replayed and
live session; same rule-set verdict in replay and live on the same data; a strategy cannot trade without
a matching frozen identity and approval.

Rough effort *(call)*: 4–8 agent weeks to one IBKR micro contract through paper acceptance; 2–4 weeks
for a funded executor once the route is confirmed.

**Build rules *(call)*:** the stock lane may break — shared contracts (lifecycle, registry, risk,
ledgers, bar schema) change freely and stock-only code and tests are deleted rather than kept green;
the research registry (zero strategies) may be reset after its database is archived. Agent-reviewed
changes merge on their own, except changes to the live-money wall, risk limits and signer anchors,
which also need the owner's one-tap merge approval (no code reading). The old gates are deleted only
after the new lifecycle's evidence ledger is enforcing.

---

## 11. Thesis review

Opens automatically at the first of: the incubation loss budget is reached; 40 frozen trials with
none reaching pilot; 12 months after paper acceptance with no strategy past pilot; 24 months of
running cost with no live strategy above its hurdle; in personal-futures-only mode, **2028-12-31**
without a live strategy above its hurdle. The review diagnoses (costs, data, power, funnel losses)
and ends in one recorded decision: change approach, change scale, or stop. Adding features is not an
allowed outcome.

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
| Dec 2026 – 15 Jan 2027 | **0. Verify and cut:** measure and cut cost to ~$150/month; funded-route go/no-go (§7) including Israeli KYC, payout and tax workflow; open IBKR futures account and confirm data and login handling; per-firm account caps. | None |
| Dec 2026 – Mar 2027 | **1. Build:** data, instrument model, intraday loop, IBKR adapter, rule engine, shadow scorer, paper acceptance. Research on history in parallel. | Data ≤ $200 |
| Mar – May 2027 | **2. Shadow → paper acceptance → first pilots.** | $600 per pilot |
| Jun – Aug 2027 | **Birth window:** no new pilots or step-ups. | Running pilots only |
| Sep 2027 – 2028 | **3. Scale, then funded.** Wave-2 repeats and step-ups on evidence; a first funded attempt only after a strategy is live with affirmative evidence. | Ladder + $1,000 fee cap |

**Honest timing:** confirming an edge needs hundreds of independent post-entry trades. A strategy
trading several times per session could be scaled in late 2027; at one trade per session, scaling and
any funded attempt land in **2028**. No date lowers a bar.

Work in progress: two parallel tracks against frozen interface contracts (data/loop/broker, and rule
engine/shadow scorer). Agent review only, except the protected changes in §10.

---

## 14. Context-file and board updates (after approval)

- **PRD:** owner amendment with this document's decisions (north star, market, vocabulary, evidence,
  capital in USD, funded path, stages, thesis triggers), replacing the stock-first phase list.
- **CLAUDE.md, AGENTS.md, README, `docs/agent/*`, `.opencode/agents/*`, `.opencode/skills/*`:** adopt the
  vocabulary; describe the stock lane as frozen; mark unbuilt items as targets with their cards.
- Personal financial context never enters this public repository; only the capital rules do.
- **Todoist (Algua):** retire old-route and stock-lane cards; add cards in §13 order with dependencies.

---

## 15. Claude's calls for the owner to check

Owner decisions are in §2. These were settled by Claude and can be overridden:
1. Stage name `shadow` replaces `holdout`.
2. Incubation budget = $15,000 cumulative net loss including running costs and fees; $60k escalation
   removed from the incubation policy.
3. Personal account daily loss $400; account flatten and halt at $1,500 below peak.
4. Funded fee cap $1,000 over two years, subscriptions included.
5. Default cutoff 15:00 CT for every strategy.
6. Live data from the IBKR subscription; historical data from Databento ≤ $200.
7. Shadow entry ≥ 100 trades over ≥ 40 sessions at 70% (an information buy); kill below 20% after 60
   trades or at 250 trades; maximum 6 strategies in shadow; maximum two pilots per strategy.
8. Owner one-tap merge approval for changes to the live-money wall, risk limits and signer anchors;
   everything else merges on agent review.
9. The stock lane may break during the rebuild; the empty registry may be reset after archiving.
10. SSH signature for first pilots; passkey later.

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
| Funded route missing | Continue as personal futures only, with a stop date | Revert to daily stocks: cannot make the owner rich; home rig for Topstep: outages breach the account |
| Overnight holding | Flat by cutoff for every strategy, for now | Overnight on personal: more edges but a second evidence track and gap risk |
| Personal broker | IBKR with a weekly login | Tradovate API: needs a live account plus add-on and stays unverified for unattended use |
| Live data | Broker subscription | Databento live: $199/month breaks the budget |

## 17. Left to the builder

Exact cost-stress parameters per contract, the Bayesian prior family, block length for dependence,
roll rule details, file and module layout, schema design, and test fixtures (FundedNext 50K Rapid rules
from Codex's simulation are the first rule-set fixture) — each fixed in its component spec and covered
by tests before acceptance.
