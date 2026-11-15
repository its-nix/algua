# TradingAgents and Vibe-Trading compared with Algua

Observed: 2026-11-15. Source inspection and first-party publications only; no external application,
model, backtest, broker connection or test suite was executed. This note proposes research choices;
it changes no roadmap, gate, runtime, purchase or trading authority.

Pinned sources: [TradingAgents `9fa1196`](https://github.com/TauricResearch/TradingAgents/tree/9fa1196fffbcfd9de5146d2dd2869df84ab99838),
[Vibe-Trading `1dbe5d5`](https://github.com/HKUDS/Vibe-Trading/tree/1dbe5d515519565a47f0127b4e6d6fc4fbb5e4d2),
and Algua `f6e0995`. An implementation, a test assertion, a published experiment and an observed
real-money outcome are different evidence. GitHub interest does not establish active trading
adoption or profitable deployment. No audited live economic record was established in this review.

## Assessment

Keep Algua's separation between research signals and deterministic execution/risk, but shorten the
path from a research question to a measured result. TradingAgents offers a narrower analyst-signal
experiment worth testing. Vibe-Trading offers a much more complete research workbench and bounded
live-agent machinery than the phrase "chat trading demo" would suggest. Neither source establishes
that replacing Algua would produce a durable net-of-cost edge. Nor does Algua's architecture prove
it is operationally safer or economically better today.

| Dimension | TradingAgents | Vibe-Trading | Algua at the inspected baseline |
|---|---|---|---|
| Main usable unit | Ticker/date analysis, debate, structured rating and retained report | Agent workbench spanning research, saved backtests, paper accounts and broker connectors | Research factory plus deterministic engine, registry, frozen planner and supervisor |
| Decisions and authority | Portfolio Manager is an LLM synthesis step; current grid evaluator is explicitly not a portfolio/fill simulator | Agents can propose decisions; deterministic mandate/order/halt code bounds supported live writes | Signed live artifact/capital authority; deterministic portfolio/risk/execution. Broader strategy isolation and deployed recovery remain unaccepted |
| Honest evaluation | Decision alpha against a regional benchmark from a later close, not an executed portfolio return | Hash-frozen cost studies and train/select/freeze/test jobs; optional final holdout | Recorded identities, costs, next-bar rule and single-use holdout gates; qualified data and actual integrated acceptance remain unfinished |
| Learning and continuity | Resolved decision lessons with historical cutoff; graph checkpoint signatures | Versioned research artifacts, comparisons, resumable workers and persisted job results | Existing ledgers/KB and attempts; demonstrated useful reuse across actual cycles remains a milestone |
| Main lesson | Make an analyst output a small, measurable hypothesis | Make evidence, recovery and economic robustness easy to inspect through one coherent workflow | Complete and measure the daily loop before adding another architecture or market |

The table is an assessment of the specific paths below, not an exhaustive feature ranking.

## TradingAgents: useful scope and important limits

The final rating comes from the Portfolio Manager's model call, with typed output when supported
and a text fallback. The current `backtest.py` deliberately evaluates independent ticker/date
cells; it does not carry positions or supply order quantities, fills and a cash ledger. Its scoring
summary explicitly warns that text inputs are not archived and one model sampling is used per
cell. This makes it a useful research challenger rather than a replacement for Algua execution.
[Portfolio Manager source](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/agents/managers/portfolio_manager.py#L1-L8),
[evaluation scope and repeatability](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/backtest.py#L1-L14),
[scoring caveat](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/backtest.py#L119-L125).

It would be inaccurate to dismiss current TradingAgents as ignoring temporal correctness.
Historical runs withhold present-day Yahoo fundamentals, EDGAR facts are selected by filing date,
FRED requests bound observation/vintage dates, and past lessons are filtered by when their outcome
was resolved. Checkpoint identity includes graph choices and behavior-affecting settings. These
are concrete mechanisms and focused tests exist; their existence is not a newly reproduced pass.
[Historical data guards](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/date_window.py),
[EDGAR source](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/sec_edgar.py),
[FRED source](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/vendors/fred.py),
[memory cutoff and checkpoint identity](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/graph/trading_graph.py#L130-L168).

The original paper reports historical simulations, with the main evaluation spanning January–March
2024 and major technology equities. It reports comparisons with simple trading baselines. That is
research evidence to investigate, not a demonstration of sustained live profit, capacity or our
small-capital economics. Its experimental implementation should not be assumed identical to the
current source above. [Paper, experiment setting](https://arxiv.org/html/2412.20138v7#S5.SS1).

## Vibe-Trading: real engineering worth learning from

Vibe-Trading has deterministic pre-trade checks for permitted instruments/universe, notional,
exposure, leverage and daily counts. Its consent writer is separated from agent tools. Broker
profiles distinguish read-only, paper and supported live writes; availability is connector-specific.
Thus, "we enforce risk, they only ask an LLM" would be a false comparison. This inspection did not
validate the deployed host/credential threat model of those controls.
[Mandate enforcement](https://github.com/HKUDS/Vibe-Trading/blob/1dbe5d515519565a47f0127b4e6d6fc4fbb5e4d2/agent/src/live/enforcement.py#L1-L25),
[consent writer](https://github.com/HKUDS/Vibe-Trading/blob/1dbe5d515519565a47f0127b4e6d6fc4fbb5e4d2/agent/src/live/mandate/commit.py#L1-L18),
[broker capability matrix](https://github.com/HKUDS/Vibe-Trading/blob/1dbe5d515519565a47f0127b4e6d6fc4fbb5e4d2/guides/portfolio-and-brokers.md).

Research Lab freezes saved source/data identities and reruns numerical cost and parameter studies
without another model or broker call. Training selection is written before OOS execution. Its
documentation also distinguishes a real train/test study from merely slicing an existing equity
curve. It explicitly says window truncation does not certify arbitrary strategy causality, and the
final holdout is optional. These per-study protections are not equivalent to Algua's cross-run
single-use holdout/promotion authority.
[Research Lab contract](https://github.com/HKUDS/Vibe-Trading/blob/1dbe5d515519565a47f0127b4e6d6fc4fbb5e4d2/guides/research-lab.md#L9-L62),
[executed study path](https://github.com/HKUDS/Vibe-Trading/blob/1dbe5d515519565a47f0127b4e6d6fc4fbb5e4d2/agent/src/research_lab/studies.py),
[optional holdout setting](https://github.com/HKUDS/Vibe-Trading/blob/1dbe5d515519565a47f0127b4e6d6fc4fbb5e4d2/agent/src/research_lab/models.py#L50-L58).

Two especially relevant details are explicit model-training exposure on backtest run cards and
persisted model spending limits. Date-filtering external inputs cannot remove future knowledge
already embedded in model weights. Model usage can consume a small trading experiment's economics
even when no order is placed. Vibe's documentation acknowledges post-response budget overshoot and
unknown usage/pricing rather than calling its dollar limit exact.
[Training-exposure disclosure](https://github.com/HKUDS/Vibe-Trading/blob/1dbe5d515519565a47f0127b4e6d6fc4fbb5e4d2/guides/research.md#L169-L176),
[model-spending behavior](https://github.com/HKUDS/Vibe-Trading/blob/1dbe5d515519565a47f0127b4e6d6fc4fbb5e4d2/guides/portfolio-and-brokers.md#L283-L313).

Published breadth is not complete lifecycle evidence. Its discovery model states that only
backtest-stage rows are currently written in that subsystem; the other stage names reserve future
integration. This does not say that its separate live connector code is absent. Saved revision
hashes, study results and simulated account reconciliation remain different from verified live
strategy profitability. [Discovery-stage boundary](https://github.com/HKUDS/Vibe-Trading/blob/1dbe5d515519565a47f0127b4e6d6fc4fbb5e4d2/agent/src/strategy_discovery/models.py#L28-L43).

## What this exposes in Algua

1. **The economic feedback loop is slower than the engineering loop.** Algua's architecture
   explicitly retains unfinished data qualification, actual-cycle learning and integrated release
   acceptance. More source files, tests or framework roles will not establish an edge. The
   benchmark should be valid, reproducible economic conclusions per unit of wall time, model spend
   and human attention. This is a diagnosis of the evidenced delivery gap, not proof that another
   framework earns more. [Algua acceptance boundary](../architecture.md#implementation-and-acceptance-boundary).
2. **Breadth can be deferred too broadly.** Avoid making a complete multimodal runtime prerequisite
   to learning whether one narrow filing/news feature adds value. A prospective, read-only analyst
   experiment can collect honest new evidence while historical data and deployment are completed.
   It must remain exploratory, use actual availability times and recorded inputs/model/prompt/output
   identity, and confer no qualification/live credit. The existing context migration limits still
   apply. [Algua context boundary](../architecture.md#unified-context-and-finite-scores).
3. **The owner needs an intelligible research trace.** Link the economic question, cited inputs,
   numerical baseline, changed test, result, costs and next decision from an existing stable run ID.
   Vibe's persisted job/revision interfaces and TradingAgents' compact analyst report demonstrate
   the usability target. Reuse Algua's registry/KB/dashboard rather than add a second workbench.
   [Versioned artifact model](https://github.com/HKUDS/Vibe-Trading/blob/1dbe5d515519565a47f0127b4e6d6fc4fbb5e4d2/agent/src/research_artifacts/models.py),
   [Algua daily milestone](../PRD.md#25-development-sequence).

## Ranked proposals for discussion, not automatic implementation

1. Restore the existing loop, then run one small falsifiable comparison: simple numerical baseline,
   one analyst signal, and only then an added critic/debate. Predeclare symbols, horizon, decision
   time, cost budget and scoring. Prefer genuinely prospective observations when model training
   exposure or text vintages cannot be established. Use existing ledgers; no broker authority is
   needed to learn whether the signal merits further work.
2. Persist evidence once and reuse deterministic numerical evaluations for cheap sensitivity and
   ablation. Shared inputs and results should not be refetched/reasoned about for every role or
   parameter trial. Measure the extra information and cost of each role rather than assuming that
   a committee is better.
3. Prioritize a compact run/evidence/cost/failure trace in the operational dashboard. Keep missing
   observations distinct from a rejected hypothesis or a failed worker, and make interrupted work
   resume against compatible identities without replaying unknown effects.
4. Track model/data costs and elapsed time next to research yield. Keep research-time compute
   amortization separate from recurring inference costs of a deployed signal. Reuse and extend
   existing budgets only when observed gaps justify it.

Do not copy broker access into authored strategy code, use agent debate as a numerical risk gate,
introduce another authoritative experiment store, or relax evidence to reproduce an attractive
published return. Broad vendor fallback, a requested date or a source hash alone does not prove
historical membership, revision correctness or terminal economics. Keep real next-bar execution,
artifact identity, protected reviews and human live/capital authority.

## Limits and decision

This was a bounded source review, not a vulnerability audit or performance replication. Tests were
read as intended contracts, not run or counted as passes. The repositories' deployment claims,
vendor coverage, star rankings, model behavior and live returns were not independently verified.
Algua's deployed VPS/account state was not inspected here. Any adoption still needs license,
dependency and scoped integration review against the actual intended use.

Recommended direction: **retain Algua's engine and authority boundaries; make its research
experience smaller, faster and visibly evidence-driven.** Discuss a bounded analyst-signal
experiment alongside the daily engineering track before expanding the roadmap. Neither a rewrite
nor a blanket rejection of these projects is supported by the inspected evidence.
