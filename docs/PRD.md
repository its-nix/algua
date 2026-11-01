# Algua — Vision of Record

**Status:** North Star / product vision of record  
**Owner:** Lior Nisimov  
**Purpose:** Define what Algua is optimizing for, what it should become, and the constraints future development must respect.

When an implementation plan, architecture proposal, issue, agent decision, or feature conflicts with this document, either the implementation changes or this document is deliberately amended.

The October 2026 owner-approved direction is reconciled below without replacing the original
30 sections. Requirements describe the product target; shipped slices and remaining limitations
are distinguished in [architecture](architecture.md). Implementation evidence is inspected at
`a062a66` (including merged PRs #719–#726), not a certification of deployed services or accounts.
The [September reconciliation](vision-reconciliation.md) remains dated context; newer source
and tests establish the implementation status stated here. This document grants no new permissions.

---

# 1. North Star

Algua is a **mostly autonomous quantitative trading company**.

Its purpose is to continuously:

1. discover market inefficiencies,
2. formulate falsifiable trading hypotheses,
3. test them honestly,
4. preserve everything learned,
5. deploy validated strategies,
6. combine weakly correlated edges into portfolios,
7. operate them safely with minimal human intervention,
8. learn from trading and software failures,
9. repair and improve its own codebase,
10. scale successful strategies across personal and compatible external capital.

The ultimate product is **net trading profit**.

The software, research infrastructure, agents, models, dashboards, datasets and automation exist to produce that outcome.

Technical sophistication has no intrinsic value if it does not improve:

- expected net P&L,
- capital scalability,
- risk,
- autonomy, or
- research learning rate.

Algua is a **personally funded quantitative investing system**: a high-throughput, multimodal
research factory discovers and evaluates diverse strategies, while a deterministic portfolio and
execution engine allocates limited capital among independently credible edges. Initial account
ownership is personal. Compatible external capital remains the separately gated expansion in §22;
this direction grants no authority to manage client capital.

---

# 2. Priority order

When objectives conflict, optimize in this order:

1. **Net profitability**
2. **Capital scalability**
3. **Risk control**
4. **Autonomy**
5. **Research learning rate**
6. **Code quality and simplicity**
7. Everything else

Clean engineering is an important enabler, but Algua is not a software architecture project.

---

# 3. Economic thesis

Algua does not attempt to compete with large funds by copying their operating model.

Its advantage can come from opportunities that are attractive to relatively small capital but too capacity-constrained, operationally inconvenient, short-lived, or economically insignificant for very large institutions.

Candidate sources of edge include:

- institutional and whale-flow effects,
- event-driven information,
- cross-sectional effects,
- momentum,
- mean reversion,
- liquidity effects,
- volatility structure,
- fundamental mispricing,
- news and filing interpretation,
- market microstructure,
- behavioral effects,
- alternative-data signals,
- ML-derived patterns,
- LLM-derived structured information,
- and new hypotheses discovered by the research system.

No single thesis is privileged permanently.

Algua should search broadly while demanding strong evidence before allocating meaningful capital.

**Volatility is not mispricing.**

A market or asset should be targeted because there is a plausible mechanism that could create exploitable expected value after costs, not simply because its price moves frequently.

---

# 4. AI and LLM thesis

AI is a force multiplier for Algua, not a substitute for statistical discipline.

LLMs may participate in:

- literature and web research,
- hypothesis generation,
- strategy design,
- feature discovery,
- financial-report interpretation,
- news interpretation,
- structured extraction from unstructured information,
- coding,
- experiment analysis,
- anomaly investigation,
- incident repair,
- experiment-memory synthesis,
- and research prioritization.

ML, deep learning and LLM-derived signals are first-class strategy capabilities.

However:

**portfolio construction, risk enforcement and execution remain deterministic, inspectable and testable.**

An AI component receives no statistical shortcut because it is intelligent or pretrained.

It must demonstrate incremental economic value against credible simpler baselines.

Where local/open models produce economically equivalent results, prefer them to paid remote models.

Model choice is ultimately based on measured value, not ideology.

OpenCode supplies multi-model, role-scoped research agents for hypothesis creation, strategy
authorship and interpretation. Deterministic Algua programs perform numerical batches and parameter
sweeps; an LLM call per numerical trial is unnecessary. Training occurs outside inference and
produces pinned, versioned model artifacts with training cutoffs. A model or prompt change that
changes decisions needs new artifact identity and evaluation.

---

# 5. One Algua, not prod Algua versus dev Algua

There is **one product, one repository and one architecture**.

There is no separately maintained production fork.

Development continues while trading operates.

The distinction is between:

- the evolving codebase, and
- immutable strategy/software artifacts currently entrusted with capital.

The running system may intentionally execute an older approved artifact while development moves forward.

That is not duplicated development. It is reproducibility.

A strategy that generated evidence must be executable as the same artifact later.

Changes produce new artifacts rather than silently mutating existing ones.

---

# 6. Architecture

Algua should remain understandable as a clean flow:

```mermaid
flowchart LR
    D[Market & Alternative Data]
    S[Point-in-Time Data Store]
    R[Research & Ideation]
    E[Experiment Memory]
    V[Validation & Promotion]
    G[Strategy Registry]
    P[Portfolio & Risk]
    X[Execution]
    M[Markets / Brokers / Funded Capital]
    O[Observability]
    A[Autonomous Engineering]

    D --> S
    S --> R
    E <--> R
    R --> V
    V --> G
    G --> P
    P --> X
    X --> M
    M --> O
    X --> O
    O --> R
    O --> A
    A -->|tested releases| G
```

The desired implementation style is:

**modular monolith + isolated live runtime + background workers**

Do not introduce microservices unless a demonstrated operational or scaling requirement makes them clearly superior.

Core conceptual modules are:

`data → research → experiment memory → strategy registry → portfolio/risk → execution → observability → autonomous engineering`

The diagram should remain clean as the system grows.

If explaining Algua requires a spaghetti diagram, that is an architectural warning.

### Three-harness product ownership

| Harness | Responsibility |
|---|---|
| **Hermes / Nix OS — company and engineering** | Develop and improve the engine, data integrations, portfolio, execution, operator, security and private monitor; maintain CI/CD; monitor aggregate health and respond to incidents. |
| **OpenCode — research operations** | Independently run ideation, isolated strategy authorship, deterministic experiments, interpretation, independent quant review and cumulative learning, including when Hermes is offline. Research authorship stays within approved strategy/metadata paths. |
| **Algua — deterministic quant engine** | Own data access, simulation, score validation, promotion verdicts, portfolio/risk decisions, execution, reconciliation and authoritative ledgers. |

Research reads prior knowledge → deduplicates a hypothesis → authors an isolated strategy → runs
Algua evaluation → records outcomes and lineage → independently reviews survivors → chooses the
next research budget. Engineering reads aggregate telemetry → deduplicates a reproducible problem
→ implements and tests a bounded fix → independently verifies → validates an authorized release
→ checks recovery. Trading verifies data/artifacts → evaluates targets → applies risk → reconciles
→ submits permitted orders → audits. Trading must remain independent of agent availability.
An unsuccessful economic hypothesis is not automatically an engineering incident.

The product ownership map uses Hermes Kanban for delegated engineering, GitHub for code and
evidence, and Todoist for human commitments. Experiments belong in the existing research ledger,
not one task card per trial. This map does not amend the repository's operating-policy files.

### Strategy-first private monitor

The target home is a Strategy Leaderboard with one row per stable strategy ID: name/family, actual
lifecycle tag, latest relevant OOS metrics, data tier, sample size, freshness and evidence health.
Allow exploratory sorting by observed OOS Sharpe/return/drawdown only within comparable cohorts,
with stage/family/data-tier/timeframe filters. Keep missing evidence UNKNOWN, never zero, and
backtest, paper and live results separate. Rows open evidence, lineage, individual runs/search
breadth, costs, portfolio contribution, artifacts, CI/deployment and risks. Safety/ops warnings
remain accessible without a competing bottom four-tab navigation. This approved UI direction
supersedes the old no-leaderboard intent only for display; it grants no promotion authority.

**Implemented / partial:** the strategy-first home, stage/family filters, stable-ID details and
opt-in provenance/OOS disclosure are shipped. Current rows retain server lifecycle order:
comparison is UNKNOWN and metric sorting stays disabled because historical cost and homogeneous
comparison metadata are unavailable. The full comparison, drilldown and operational UX target
is not accepted. Metadata-bound display is not payload verification, PIT proof or a profit claim.

---

# 7. Strategy contract

Strategy logic should be pure and broker-agnostic.

Conceptually:

`point-in-time inputs → target portfolio intent`

Broker-specific behavior belongs in execution adapters.

The same strategy implementation should travel through:

`backtest → shadow → paper → experimental live → scaled live`

Do not create separate strategy implementations for each environment.

A strategy may contain:

- deterministic rules,
- fitted statistical models,
- ML models,
- deep-learning models,
- LLM/agentic components,
- or combinations of them.

Models and LLM providers should be hot-swappable through stable interfaces.

Changing a behavior-affecting model creates a new strategy artifact requiring evaluation.

### Unified scoring target and delivered boundary

The target authored interface is `score(AsOfContext) -> symbol-to-score series`. Context combines
required as-of bars, fundamentals, news, filings, alternative features and pinned models through
one declared interface. Required unavailable inputs fail closed; optional inputs are explicitly
declared. Outputs must be real, finite, duplicate-free and within the eligible as-of universe.
Scores express relative opportunities, not orders, stop prices or cash amounts. Deterministic
construction converts them to target weights, preserving cash and the initial long-only policy.
The earliest eligible fill remains `t → t+1`, with `decision_lag_bars >= 1`.

The strategy must have no broker, account, network, secret or authority access. This is a runtime
acceptance requirement, not something a pure function signature or prompt can enforce.

**Implemented / partial:** `context_v1` now loads authored `score(context)` into the canonical
research backtest, combines supported modalities and pinned models, and retains construction,
overlays, temporal/model verification and legacy identity compatibility. The complete strategy
family migration is unfinished: legacy mutually exclusive signal branches remain. Context signal
parameter overrides are explicitly refused until a reviewed binding exists; supported construction
and overlay grids remain. Model-backed walk-forward/sweep is still refused. Context execution in
frozen/paper/live lanes is unsupported and fails closed. Migrate and remove the compatibility path
only after score, weight, decision and identity parity across every supported strategy and lane.
Genuine bars plus synthetic news/model fixtures demonstrate interface controls, not real-news alpha.

---

# 8. Research philosophy

Algua should generate ideas broadly but operate only a **small portfolio of deeply validated strategies**.

Research follows a lightweight mandatory loop:

`hypothesis → rationale → falsification criteria → experiment → robustness → conclusion → learned knowledge`

Agents may invent entirely new strategy families.

They are not restricted to tuning existing strategies.

Every hypothesis must nevertheless contain:

- an economic or behavioral rationale,
- a falsifiable claim,
- an explicit experiment,
- and criteria under which the idea should be rejected.

Negative results are valuable outputs.

Correctly proving that something does **not** work reduces future search space.

The factory should search a large, diverse top of funnel through cheap screening and progressively
more rigorous evaluation: momentum, reversal, events, fundamentals, quality, ML and novel families.
No fixed set of permanent categories bounds the research space. Preserve all variants, failures and
effective search breadth; cheap screening does not erase trials from selection accounting.

Campaigns have bounded concurrency, CPU/GPU use, storage, wall time and model cost, with a reserve
for novel families. Record budgets and use; reallocate from observed learning and yield rather than
a lucky historical winner. Idempotent cycle/claim identities, checkpoints, timeouts and bounded
retries must leave terminal outcomes and recover abandoned work without duplication. Infrastructure
errors, data exclusions and unfinished attempts must remain distinct from negative economic results.

---

# 9. Experiment memory is a moat

Algua should become smarter because it remembers what it has already learned.

Every meaningful experiment—successful or failed—becomes permanent structured knowledge.

At minimum, record:

- hypothesis,
- economic rationale,
- strategy family,
- parent experiment,
- data snapshot/version,
- point-in-time assumptions,
- code commit,
- strategy artifact,
- configuration,
- model identity,
- parameters,
- transaction-cost assumptions,
- metrics,
- robustness results,
- artifacts,
- conclusion,
- failure reason,
- and lessons learned.

For LLM-dependent experiments also preserve:

- provider,
- model/version,
- prompt,
- timestamp,
- inputs,
- raw response,
- and structured derived output.

Agents must search prior experiments before proposing new research.

Re-running substantially equivalent research requires an explicit explanation of what changed.

Maintain a **strategy genealogy**:

`idea → experiment → modification → descendant → deployment`

The system should automatically maintain synthesized knowledge such as:

- what we know about momentum,
- what has failed in event-driven research,
- which assumptions repeatedly break,
- which markets exhibit which effects,
- which model families added value,
- and which promising directions remain unexplored.

The accumulated experiment graph is part of Algua's long-term intellectual property.

Retain one authoritative experiment/strategy ledger using the existing SQLite registry, MLflow,
Git and linked KB records. Every attempted variant includes data tier and limitations, trial count,
parent/family, costs, identities, decision and error reason. Do not build a parallel research database.

Learning must affect subsequent work: cite prior outcome IDs and explain why a next-cycle choice
changed. Measure attempted and valid trials per wall-hour/cost, family diversity, duplicates,
repeatability, stage yield with honest denominators, error/recovery rate and knowledge reuse.
A scorecard or a successful feedback fixture alone does not prove autonomous cumulative learning.

---

# 10. Reproducibility and research integrity

A backtest must be reproducible from:

`code + artifact + data version + configuration + environment`

If a result cannot be reproduced, it cannot justify promotion.

Historical evaluation must be point-in-time correct.

Particular care is required for:

- universe membership,
- corporate actions,
- delistings,
- fundamentals,
- filings,
- news,
- macroeconomic releases,
- alternative data,
- and LLM inputs.

Mandatory robustness should include, where applicable:

- true out-of-sample evaluation,
- walk-forward testing,
- realistic transaction costs,
- slippage assumptions,
- parameter sensitivity,
- regime analysis,
- liquidity checks,
- capacity checks,
- simple baselines,
- correlation with existing strategies,
- and awareness of repeated/multiple hypothesis testing.

Repeatedly searching the same historical data must never masquerade as independent confirmation.

The implemented PIT masks, `t → t+1` lag, canonical/fast decision parity, burn-on-peek holdout
accounting and measured search/family breadth remain binding. A replay cannot supply elapsed
broker-clocked forward observations. Do not lower enforced gates to make two-year evidence qualify;
no qualifying strategy is a valid research outcome.

Current research promotion retains a binding integrity floor while much of the statistical stack
is recorded as advisory; frozen FDR accounting is not an active veto. The target's stronger
robustness requirements do not imply that all statistical checks currently block promotion. Agent
advancement uses the actual promotion gates, never a board rank or a raw lifecycle flag.

A bare `--actor human` grants nothing: research/paper human-only relaxations require a verified
single-use SSH challenge bound to the command, strategy, recomputed identity and exact run context,
including relaxations. Live activation separately requires the authenticated human signature,
matching code/config/dependency identity and a fresh forward certificate. Protect signer trust
anchors independently of the runtime. None of these walls is relaxed by this PRD.

---

# 11. Data

Algua should own a **canonical local, versioned historical dataset**.

External vendors are upstream sources, not the sole authority for reproducibility.

Initial first-class data:

1. OHLCV,
2. fundamentals,
3. timestamped news,
4. timestamped filings.

Add options, order books, alternative data and specialized sources when a research hypothesis justifies their additional cost and complexity.

The system should be vendor-extensible without making vendor abstraction itself a project.

Prefer established libraries and simple adapters.

### Minimal real-data tier, complete architecture

Start with **approximately two years of real free yfinance daily OHLCV for 150–300 selected
symbols**, pinned in the canonical local store. This is a data-quality tier, not a reduced product
or synthetic-only demonstration. Build actual backtests, supported parameter grids, offline ML
training/evaluation, combined-input contracts, strategy comparison, portfolio simulation, research
learning, recovery and ongoing scheduled paper mechanics around it. Where genuine modalities are
unavailable, record that fact and use labeled fixtures only for contract verification.

The pilot is `pilot_real_proxy`: current surviving-symbol selection cannot establish historical
PIT membership, $0.5–10B market caps, delistings, corporate actions or historical event availability.
Vendor-adjusted prices can be revised. Pinning a download makes its replay reproducible, not its
history PIT-correct. Retrieval time, publication time and knowledge time are distinct. Never
backdate present-day eligibility or fabricate missing announcements.

Target provenance on every result comprises tier, provider, exact snapshot/hash, coverage,
universe-generation method and all known limitations. Keep stable campaign snapshots separate from
fresh operational data. `synthetic_fixture` is test-only; `verified_pit` requires verified evidence,
not a label. At the inspected implementation, bars provenance/identity binding, a bounded real-data
recipe and opt-in board disclosure are shipped; full experiment/factory propagation is partial,
and verified-PIT declarations are refused because no verifier exists.

The merged recipe records snapshot `baaa116a36acee68`: 150 symbols, 75,150 rows, 501 sessions,
2024-10-31 through 2026-10-30. It is a current S&P 400 selection proxy with unavailable/unverified
historical eligibility, not a completed investment dataset. These are recorded acquisition results,
not a fresh acquisition or payload verification in this documentation change.

Later, approved sources add depth, security identity, historical membership/capitalization,
delistings, corporate actions and timestamped filings/news through the same provider/snapshot
seams. The frozen bars contract remains unchanged. No premium procurement is authorized here.

---

# 12. Markets and timeframes

The first complete operating scope is:

- liquid US stocks and ETFs,
- daily strategies,
- hourly strategies.

The architecture should support additional markets without prematurely implementing all of them.

Possible future markets include:

- futures,
- crypto,
- forex,
- prediction markets,
- options,
- and other sufficiently liquid assets.

Each new market requires an **economic reason**.

Do not add an asset class merely because Algua can technically support it.

Likewise, lower timeframes are justified by specific opportunities—not by the mistaken assumption that simply sampling returns more frequently automatically creates more independent statistical evidence.

High-frequency/tick-level trading is outside the current thesis.

The primary research focus is liquid U.S.-listed small/mid-cap common equities: historical
market cap **USD $0.5–10B**, price **>= $5**, trailing median **60-session dollar volume >= $5M**,
and **90-session listing history**, all subject to PIT evidence. The pilot cannot certify these
screens. Existing stock/ETF scope remains; this focus is not a historical-universe claim.

Begin with end-of-day signals and next-eligible-session execution. Evaluate daily but rebalance
only when marginal benefit justifies costs, using declared holding periods, signal decay, ranking
hysteresis and exits. Daily-first delivery does not remove hourly operation from the first complete
architecture or turn extra bars into independent evidence.

---

# 13. Portfolio

Algua should ultimately operate a **portfolio of weakly correlated edges**, not search indefinitely for one perfect strategy.

Portfolio construction should consider:

- expected return,
- uncertainty,
- volatility,
- drawdown,
- correlation,
- liquidity,
- capacity,
- and incremental contribution to the existing portfolio.

A strategy with lower standalone performance may still be valuable if it materially improves the total portfolio.

Capital allocation should adapt within approved limits.

Initial sizing should be conservative:

- explicit risk budgets,
- hard exposure limits,
- no aggressive Kelly sizing.

Fractional Kelly or related approaches may be introduced later if estimation quality supports them.

Systematic portfolio trading is the organizing model. Within-strategy construction maps scores
to weights; across-strategy allocation assigns capped, volatility-aware budgets, controls overlap
and aggregates to one account target. Net shared exposures and constrain liquidity, turnover,
concentration, available cash and gross/net risk before execution. Initial allocation stays simple;
short samples do not justify an unstable return-optimizing framework. No qualified strategies or
infeasible constraints can correctly produce **100% cash**. Allocation estimates must themselves
be available as of the decision.

SL/TP and trailing stops are optional separately evaluated policies, not mandatory strategy outputs
or substitutes for portfolio/risk controls. Existing construction, allocations and book guards are
partial foundations; they do not establish delivery of the full cross-strategy allocator or its
backtest/paper integration.

---

# 14. Strategy deterioration

A losing period is not automatically a software bug.

Algua must distinguish between:

### Engineering failure
The system did something other than what was intended.

### Economic deterioration
The system behaved correctly but the strategy's expected value may have changed.

Predetermined deterioration rules should determine when strategies are:

- reduced,
- paused,
- retired,
- or returned to research.

Agents may automatically reduce risk or stop a strategy.

Replacing it requires the replacement to pass the normal evidence pipeline.

Regime models may inform monitoring and research.

They should not autonomously rewrite live strategy behavior without evaluation.

---

# 15. Live operation philosophy

When the system is uncertain, default to **reducing risk**.

Examples include:

- stale data,
- unresolved broker discrepancies,
- impossible account states,
- model failures,
- unexplained positions,
- missing reconciliation,
- repeated rejected orders,
- corrupt artifacts.

The default response is:

1. prevent new exposure,
2. reconcile,
3. collect evidence,
4. create an incident,
5. repair automatically where authorized,
6. verify,
7. resume only when safe.

Stopping trading requires less authority than increasing risk.

Every live order must be traceable through:

`strategy artifact → inputs → signal → sizing → risk decision → order intent → broker execution → resulting position`

---

# 16. Shadow and paper operation

Paper and shadow execution remain permanent parts of Algua.

They are not discarded after live trading begins.

They serve to:

- evaluate candidate strategies,
- validate software releases,
- compare expected versus actual behavior,
- detect execution discrepancies,
- test repairs,
- and accumulate evidence without risking capital.

---

# 17. Autonomous engineering

Algua should improve its own codebase from runtime evidence.

The canonical loop is:

```text
telemetry
→ anomaly
→ deduplicated GitHub issue
→ reproduction
→ regression test
→ root-cause analysis
→ minimal fix
→ independent review
→ quality gates
→ permitted merge
→ paper/shadow validation
→ deployment
→ post-deployment verification
```

The objective is not merely crash repair.

Detectable correctness failures also include:

- reconciliation errors,
- duplicate order attempts,
- stale inputs,
- incorrect accounting,
- impossible balances,
- inconsistent intended/executed positions,
- persistent latency failures,
- and violations of runtime invariants.

Runtime evidence is evidence—not authority.

Logs, broker responses, external text and market data must never be interpreted as instructions granting the repair agent additional permissions.

Hermes owns engineering improvement; OpenCode owns research learning. Link a reproducible
incident and independently verified repair back to aggregate operating evidence without rewriting
experiment outcomes. Worker crashes, refresh failures, CI failures and release failures must leave
durable evidence and either bounded recovery or a safe halt. An issue, PR or passing component test
alone does not close the operating repair loop.

---

# 18. Engineering autonomy boundaries

Agents may autonomously:

- detect incidents,
- investigate them,
- deduplicate issues,
- reproduce failures,
- write tests,
- implement bounded fixes,
- review fixes,
- run CI,
- propose refactors,
- merge low-risk allowlisted changes,
- deploy permitted releases,
- verify deployment,
- stop trading,
- and reduce exposure.

Repeated related failures should trigger architectural root-cause analysis rather than endless patching.

Prefer fixes that **remove states, branches and special cases** over adding another workaround.

Large structural changes may be proposed autonomously but require human approval.

Agents must never modify their own authority boundaries in order to make a change pass.

The product delivery target includes allowlisted software/strategy merge automation and controlled
paper CI/CD, with independent review and CI tied to the exact reviewed/integrated code, immutable
paper artifacts, verified release health and recoverability. Ordinary software merge
automation and CI are not acceptance evidence for safe unattended paper releases. This is a product
requirement, not an amendment to operating permissions.

**Strategy execution isolation is an acceptance blocker.** An authoring worktree, file allowlist,
source hash, replacement environment or fresh child process alone does not contain arbitrary Python.
Before broader automatic trusted strategy execution, prove an enforced boundary denying network,
credentials, broker and authority-state access and validate typed decision output. Missing isolation
must fail closed. Current frozen-paper reproducibility controls do not establish that full boundary.

---

# 19. Human authority

The human should be a **wall and capital allocator**, not an everyday operator.

Human authorization remains required for:

- first activation of a strategy into real-money live trading,
- increasing approved live capital,
- new paid commitments beyond established budgets,
- and protected/high-impact changes affecting core safety or authority boundaries.

Agents may always reduce risk without permission.

Agents may never independently raise the maximum capital entrusted to them.

The list of routine human responsibilities should shrink rather than grow.

---

# 20. Operational autonomy

Existing compute resources should be used aggressively where useful:

- local RTX 5070 Ti workstation,
- existing VPS,
- local storage,
- and available agent/model infrastructure.

New recurring paid commitments require approval unless a budget is explicitly established.

Algua must be able to operate safely without daily human attendance.

A near-term operational acceptance target is:

**72 hours unattended while either operating correctly or autonomously reaching a predefined safe state.**

Long-term routine operation should require very little human attention.

Human time should be spent primarily on capital decisions, strategic direction and genuinely consequential approvals.

Target one durable systemd research initiator, with bounded specialist jobs. Independent,
deterministic market-session operations and trusted queues retain necessary scheduling and locks.
Hermes monitors aggregate operation rather than initiating every experiment. Existing research,
leap and forage timers are implementation machinery, not proof that the consolidated target has
been cut over or observed unattended. Preserve working behavior until parity is proven; avoid
duplicate initiators and competing authoritative writers.

---

# 21. Capital

Total initial Algua experiment budget:

**₪10,000**

Initial allocation:

- **₪2,000:** experimental personal live capital,
- **₪6,000:** undeployed reserve,
- **up to ₪2,000:** data/infrastructure/operating expenditure.

The expense allocation is a ceiling, not a target.

Initial personal-capital trading should remain conservative:

- long-only stocks,
- unleveraged ETFs,
- no borrowing,
- no derivatives.

A **10% drawdown of the live experimental account** triggers an automatic trading pause and human review.

This threshold is an intervention rule, not a guarantee that losses cannot exceed it.

No automatic replenishment.

No automatic increase in approved capital.

Capital rises because evidence improves, not because the system is confident.

The approved envelope includes no shorting or leverage and no premium-data purchase in this
initial work. The 10% pause remains a policy requirement: runtime defaults still include a 15%
book drawdown breaker and generic gross exposure of 2.0. These do not enforce the ₪2,000,
long-only/unleveraged experimental envelope. The owner-defined cash-flow-adjusted peak, inclusive
10% boundary, cancel/block-orders-without-forced-liquidation response and signed resumption are
recorded in Story 2.6; implementation and deployment verification remain necessary. Do not silently
substitute the existing flattening breaker for this policy. No funding, replenishment, activation
or risk-default change follows from this document.

---

# 22. External and funded capital

Personal savings are not the only potential scaling path.

Compatible funded-account programs and other legitimate external-capital mechanisms are first-class future options.

They are not architectural dependencies.

A funded provider is modeled as another constrained execution environment with:

- instrument restrictions,
- drawdown rules,
- payout rules,
- trading limits,
- automation restrictions,
- costs,
- and operational requirements.

Strategy research optimized specifically for funded-account rules is permitted but must remain distinct from general alpha research.

Passing a funded challenge and possessing a durable economic edge are different objectives.

Provider headline "account size" must not be confused with actual loss capacity.

Implement funded-provider integration only when a compatible strategy has sufficient evidence to justify it.

---

# 23. Initial success criteria

Algua's **one-year success criteria** are:

1. **positive net live P&L**, and
2. **a demonstrated path to materially larger deployable capital**.

Everything else is supporting evidence.

Important supporting measures include:

- drawdown,
- risk-adjusted performance,
- number of independently useful edges,
- operational uptime,
- human interventions,
- incident frequency,
- repair success rate,
- research throughput,
- experiment reuse,
- and strategy correlation.

Do not judge the project by the number of features shipped.

### Machine acceptance and investment acceptance are independent

**Machine acceptance** on limited real data requires all of the following:

- Ten completed **unattended OpenCode research cycles** on the actual scheduler and registry, plus
  **at least 100 individually recorded real-data hypothesis/variant attempts across multiple
  families**. Expose errors, exclusions, duplicates and unfinished work with honest denominators;
  they are not completed validations.
- Reproduced outcomes from pinned data/code/config/environment/model identities; rule, pinned-ML
  and combined-modality controls; visible prior outcomes changing later research choices. Fixtures
  verify unavailable modalities without inventing real events.
- Enforced research and authoritative strategy-execution isolation; no access to broker secrets,
  capital ledgers or protected gates. Independent quant/engineering verification, review and CI
  for advancing code, allowlisted merge automation, and verified paper release, smoke checks and
  schema-compatible recovery.
- Multiple-strategy aggregation, risk-bound order behavior, leaderboard/drilldowns, bounded claims,
  resources/retries, and injected worker, refresh, CI and paper-release failures with recovery or
  a predefined safe state.
- **Actual scheduled paper operation and accelerated historical replay verified separately**.
  Record completed-session ticks; replay never supplies forward qualification. No duplicate
  research initiation or parallel experiment ledger.

**Investment acceptance** additionally requires sufficient PIT universe/delisting and other input
quality, costs, untouched OOS/multiple-testing evidence and genuine elapsed forward observations;
immutable live artifacts and signer anchors; broker/economic-state reconciliation and recovery;
enforced capital/drawdown policy; and the human-signed live ceremony. Machine acceptance cannot
prove alpha, investment eligibility or authority to trade.

**Current evidence:** the full machine target is not accepted. Ten unattended cycles and 100
real-data attempts remain **UNKNOWN**. Merged component slices do not satisfy those counts or the
integrated isolation, learning, portfolio, release and recovery demonstrations. Zero gate-qualified
strategies is compatible with machine acceptance if honest refusals and isolated execution mechanics
are demonstrated; it never waives investment acceptance.

---

# 24. 90-day objective

The initial objective is not to prove lifetime alpha.

It is to prove that the machine is becoming real.

The first operating milestone is:

> **Algua can autonomously research, deploy, operate, observe and repair one real strategy end to end.**

The system should demonstrate:

- trustworthy data,
- reproducible research,
- realistic evaluation,
- working strategy promotion,
- real/paper execution,
- reconciliation,
- observability,
- safe failure,
- immutable deployed artifacts,
- incident creation,
- autonomous tested repair,
- and auditable results.

Daily and hourly trading belong in the first complete operating architecture.

The first validated strategy does not need to exercise every capability before the vertical slice proves the lifecycle.

The limited-real-data machine demonstration in §23 is the near-term proof, not a deadline to
force investment qualification. Complete the factory/portfolio/learning/release/recovery architecture
incrementally even if data limits prevent a candidate passing. Synthetic integration fixtures and
historical replay remain explicitly labeled and cannot replace real scheduled operation.

---

# 25. Development sequence

The architecture is designed as a complete system from the beginning.

Implementation remains incremental and testable.

### Phase 1 — Operating kernel
Make one strategy travel cleanly from research through real-money execution using immutable artifacts and safe operations.

### Phase 2 — Research memory
Make every experiment permanently reusable knowledge and require research agents to build on prior findings.

### Phase 3 — Data depth + hourly operation
Establish deep point-in-time historical data and complete daily/hourly strategy operation.

### Phase 4 — Autonomous engineering
Close the runtime incident → issue → test → fix → validated release loop.

### Phase 5 — Portfolio
Operate multiple genuinely distinct strategies and allocate capital based on portfolio contribution.

### Phase 6 — Alpha breadth
Expand datasets, strategy families, ML/LLM capabilities and research throughput where evidence indicates value.

### Phase 7 — Capital breadth
Integrate compatible funded/external-capital environments.

### Phase 8 — Market breadth
Add additional asset classes when a specific economic opportunity justifies doing so.

These phases define dependency order, not a prohibition on parallel research.

Within these eight phases, the approved redesign follows this implementation dependency order:
canonical product/architecture reconciliation and pinned real-data provenance → unified context
scoring and deterministic portfolio aggregation → enforced strategy execution isolation → one
independent OpenCode factory and cumulative learning → verified paper CI/CD, strategy-first monitor
and Hermes incident feedback → integrated unattended/failure-recovery acceptance. Isolation precedes
broader trusted generated-strategy execution; data quality and live qualification remain separate
constraints. UI work may proceed alongside engine slices without implying engine acceptance.

The merged data recipe/provenance, context/backtest and board/UI slices are partial delivery of
this sequence. [Architecture](architecture.md) records their concrete boundaries. These additions
do not replace the eight phases, defer hourly/PIT depth indefinitely or declare full acceptance.

---

# 26. Code philosophy

Algua should be **small in concepts, not artificially small in lines of code**.

Prefer:

- obvious code,
- focused modules,
- explicit state,
- pure computation where possible,
- typed contracts,
- narrow interfaces,
- established libraries,
- deterministic behavior,
- testable boundaries,
- and deletion over accumulation.

Avoid:

- speculative abstractions,
- universal frameworks,
- custom infrastructure that mature libraries already solve,
- giant modules,
- hidden state,
- duplicated execution paths,
- excessive indirection,
- premature distributed systems,
- and abstractions built only for hypothetical future requirements.

New abstractions require demonstrated repeated need.

Unused capabilities should be deleted once useful history and knowledge are safely retained.

The correct compromise between architecture and shipping is:

> **ship the simplest clean implementation.**

Reuse the existing registry/tracking/KB and deterministic engine. Consolidate duplicate agent
coordination and schedulers only after parity; do not add a second research database, MLflow
instance, execution fork, optimizer framework or speculative microservice. A limited free dataset
justifies honest evidence limits, not a toy architecture.

---

# 27. Explicit non-goals

Algua is not:

- a SaaS product,
- a customer-facing trading platform,
- a multi-tenant system,
- a social trading network,
- a generic agent framework,
- an infrastructure playground,
- a UI product,
- an HFT/tick-level trading system,
- or an excuse to build technology without testing whether it makes money.

Avoid unnecessary:

- dashboards,
- microservices,
- orchestration layers,
- generic plugin systems,
- speculative scaling infrastructure,
- and framework-building.

Build only what improves Algua's ability to learn, trade, control risk, operate autonomously or scale capital.

---

# 28. Roadmap admission test

Every roadmap item must answer at least one of:

**How can this improve:**

1. expected net P&L?
2. risk?
3. capital scalability?
4. autonomy?
5. research learning speed?

If the answer is unclear, the feature probably does not belong in Algua.

---

# 29. When to stop

Individual strategies are retired according to predefined economic/statistical deterioration criteria.

Algua itself should also be falsifiable.

If, after a meaningful period of serious research and real operation, the system produces neither:

- credible net-of-cost edges,
- nor evidence that its research process is becoming materially better at discovering them,

then the core thesis should be reconsidered rather than protected through endless feature development.

The correct response to failure is learning, not adding complexity.

---

# 30. The standard

Algua succeeds when it becomes a machine that:

- discovers things we did not already know,
- remembers everything useful it learns,
- turns validated insights into controlled positions,
- combines independent edges intelligently,
- detects when either its trading or its software is failing,
- improves itself without creating operational chaos,
- requires little routine human involvement,
- and converts that capability into growing real-world capital and net profit.

**Make money. Preserve knowledge. Control risk. Automate everything else.**
