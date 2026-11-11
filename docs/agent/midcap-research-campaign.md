# Bounded liquid-midcap research campaign

Prepared 2026-11-08; definition only. No authority claims, strategy authoring, LLM call,
unattended cycle, source switch, timer change or market experiment was executed here.

## Fixed inputs and scope

- Bars: verified-payload snapshot `c63d16f44419cb96`, requested `[2024-11-01,2026-11-08)`;
  latest observed session November 6. “Verified” means payload integrity, **not verified PIT**.
- Universe: exactly the 300 symbols in `momentum/midcap_weekly_momentum_smoke.py::CONFIG`.
  Retain its private screen/source digest; do not re-screen, substitute, refresh or backdate membership.
  The $10/$20M/60-session/252-observation screen and 11 sectors describe current selection only.
- Use static-universe bars, `1d`, closed-bar decisions and lag 1. Price signals use `adj_close`;
  raw volume is permitted only for explicitly declared volume features, not fabricated order flow.
  Preserve raw OHLCV and the [frozen contract](../contracts/bar-schema.md).
- Common execution: long-only, no borrowing, top 20 equal weights, maximum symbol weight 0.075,
  fees 0.0005 plus slippage 0.0005 per side, as in the existing machinery control. Rebalance
  intervals below describe basket updates, not a guaranteed maximum holding age. No optimization
  of portfolio size, costs, universe or dates. Rules are deterministic; retain actual emitted seed.
- Keep four chronological research windows, holdout fraction 0.2 and default embargo. Prior pilot
  windows/full backtests have been examined: never call this interval an untouched holdout.
  All seven proxy limitations persist: revisable adjusted close, unverified corporate actions,
  missing delisted names, unavailable event timing/market cap/PIT membership, survivorship bias.
  See [data assessment](pit-data-assessment.md); no candidate, paper intake or `merge_back` is eligible.

Pin the final reviewed release before execution: record `git rev-parse HEAD`, `git status --short`,
`shasum -a 256 uv.lock pyproject.toml .opencode/opencode.json .opencode/scripts/run_agent.sh`
and the fixed-universe module hash. Inspection began at `d55c325e874362640feafbac4bcd10c0a25df6b0`;
that is **not** the final release pin. The existing controller binds the complete source baseline,
dependency/runtime/driver hashes and data-manifest digest; exact bars identity/content verification
must accompany it. Keep private receipts outside Git. Drift requires a new campaign context.

## Predeclared first tranche

These are falsifiable proposed mechanisms, not accepted edges or already-created ledger ideas.
Before admission, compare actual attempts/retained evidence and family notes; the checkout KB index
is sparse and cannot establish absence of prior work. Reuse the existing family where mechanisms
overlap; category labels and parameter variants are not independent families.

| Mechanism / existing category | Closed-bar score and bounded grid | Maximum variants |
|---|---|---:|
| Persistence / `momentum` | Trailing adjusted return; lookback `{20,60}` × basket cadence `{5,10}` sessions | 4 |
| Short rebound / `mean_reversion` | Negative trailing adjusted return; lookback `{2,5}` × cadence `{2,5}` | 4 |
| Defensive dispersion / `vol_structure` | Negative realized adjusted-return volatility; lookback `{20,60}` × cadence `{5,10}` | 4 |
| Trend quality / `momentum` | 20-session return rank plus log-price path-efficiency rank; efficiency lookback `{20,60}` × weight `{0.25,0.75}`; cadence 5 | 4 |
| Stable participation / `liquidity_microstructure` | 20-session return rank minus raw-volume variability rank; volume lookback `{20,60}` × penalty `{0.25,0.75}`; cadence 5 | 4 |
| Calendar-conditioned rebound / `seasonality` | Negative adjusted return at weekday `{0,4}` anchors × lookback `{2,5}`, retain basket between anchors; shares rebound-family history | 4 |

For each, missing/incomplete lookback means no score, never filled synthetic prices. Author the
canonical expanding-prefix scorer first; use a vectorized scorer only with existing parity checks.
Falsification: refute the proxy mechanism if its median costed research-window Sharpe is <=0, or no
completed variant has positive net research-window return. Unfinished/error variants remain untested;
isolated winners with median failure are unstable, not a license to expand the grid. Review turnover,
drawdown, concentration and behavior versus the fixed control as diagnostics, without changing rules.

Initial ceiling: **24 new numerical variants across six ideas**, plus one singleton replication of
the existing 20-session Friday momentum control when needed (a repeat is not a novel hypothesis).
No adaptive neighboring values. Later tranches require a new written grid justified by recorded
learning; do not inflate the count through renames, repeated reports or control reruns.

| Control | Admission now |
|---|---|
| Rule-only | Existing `midcap_weekly_momentum_smoke`: available for proxy mechanics, exact singleton `lookback=20`. |
| Pinned ML | Blocked until actual portable price-linear bytes and verified pin/training provenance exist before the full evaluation start. Bundled AAPL/MSFT/NVDA examples are fixtures, not a 300-name trained model. |
| Rule + pinned ML | Blocked with the model; if admitted later, fix both components/combination before evaluation and compare on identical inputs. Both using price data is not a news/fundamental multimodal demonstration. |
| News/fundamental combined | Blocked for this historical window; current-collected snapshots cannot be backdated. Synthetic sidecar controls test mechanics only and never count as real-data hypotheses or alpha. |

## Existing execution and evidence seams

Use [the research playbook](../../.opencode/skills/run-the-research-loop/SKILL.md) and
[chooser](campaign-chooser.md), with at most **three claimed ideas**, **one worker**, **1200 CPU
seconds**, **20 minutes active wall time**, 16,384 MiB address-space and 512 MiB file limits per firing.
Reserve the final two minutes for interpretation/reporting; stop new numerical work before that.
Keep the existing six-hour cadence and one research-loop lock; no new scheduler or catch-up burst.
The supervisor's bounded failure finalization is separate from active research time.

The trusted driver alone captures menu/context, performs chooser/CAS claims, seeds worker memory,
launches through `run_agent.sh`, captures/readbacks retained results and finishes every claim once.
Use `--choose-campaign` only after its release/profile check; never bypass it with handpicked IDs.
Model cost is UNKNOWN: do not invent a monetary cap/accounting result; configured caps refuse claims.
Author/interpret tasks run sequentially within that bound, not one reasoning call per grid point.
Use `backtest run --register`, `backtest walk-forward --windows 4 --holdout-frac .2`
and one predeclared `backtest sweep --param KEY=... --top 4`, always with the pinned snapshot/dates.
Retain full JSON privately for the window/grid falsification; summarize it for reasoning context,
without rerunning calculations. `--summary` is available when those detailed results are not needed.
`research run-all --tasks FILE` amortizes compatible backtest/sweep commands; its JSON accepts
`backtest|sweep|promote`, **not** walk-forward or `summary/track`. Keep standalone walk-forward.
Record actual `sweep_trial` rows/overflow and failures; a sweep parent or claim slot is not a variant.
Known proxy qualification ends `integrity_fail`, `preview_gate: null`, no `merge_back`; report empirical
falsification separately. Do not pass `--n-combos`, human relaxation flags or a fabricated universe.

## Isolated preparation commands

These existing CLI commands create only a disposable preparation registry/menu; no claims, model
call, worker or simulated outcome. They are not market evidence and need no copied market payload:

```sh
PREP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/algua-midcap-prep.XXXXXX")
export ALGUA_DB_PATH="$PREP_ROOT/prep.db" ALGUA_DATA_DIR="$PREP_ROOT/data"
export ALGUA_KNOWLEDGE_DIR="$PREP_ROOT/kb" ALGUA_TRACKING_BACKEND=noop
uv run algua research idea add --title 'PREPARATION_ONLY midcap persistence' --source-type manual --category momentum --market us_equities --horizon daily --required-data ohlcv --family momentum --hypothesis 'PREPARATION_ONLY; fixed c63d16f44419cb96; no execution' --falsification 'Untested preparation; no economic result'
uv run algua research idea cycle-start --run midcap-prep --limit 3 --timeout 20m --workers 1 --cpu-seconds 1200 --memory-mb 16384 --file-mb 512 --menu-only
uv run algua research campaign-menu --budget 3
```

On the prepared **Linux** release only, the same isolated environment can inspect the driver with
`.opencode/scripts/run-research-loop.sh --hypotheses 3 --timeout 20m --workers 1 --cpu-seconds 1200 --memory-mb 16384 --file-mb 512 --choose-campaign --dry-run`.
It does not claim, query archives or launch a model; it also does not validate real data/memory.
Do not remove `--dry-run` from this preparation recipe or reuse its `noop` profile for real cycles.

**Execution blockers:** final reviewed source/dependency release and Linux supervision/containment
are not verified by this document; authoritative idea admission and observed author/interpret use
remain pending. The November 9 [pinned profile](research-profile.md) implementation supplies the
exact validated data receipt through existing context and task prompts; deployment must enable it.
The actual local MLflow retention/chooser/primary-memory profile and prior-evidence receipt
checks need verification on the intended deployment; data path/content/300-symbol receipts remain
deployment inputs; genuine model/combined controls are unavailable. PIT and fresh qualifying
historical evidence remain separate investment blockers. No source flip or execution is authorized here.

The parent verified the preparation with the updated-lock Linux image: the existing CLI created
one `PREPARATION_ONLY` idea in a disposable registry, both menu commands succeeded, and the driver
`--dry-run` completed. The menu offered one choice; `idea_attempts` remained empty. The test image
does not install the `algua` console entry, so verification invoked its same `main()` entry using
`python -c 'from algua.cli.main import main; main()'`. A first console-entry attempt failed before
any idea was created; the corrected isolated run exited zero. No market payload or model was used.

**Counts attributable to this preparation:** 0 actual cycles, 0 market attempts/variants, 0 candidates,
0 elapsed paper sessions. Three unattended cycles **and** >=100 individually recorded real-data
hypothesis/variant attempts across families remain acceptance targets, with errors/exclusions/
unfinished work exposed. They are not promised within three cycles; fixtures/menu captures/replays
do not count. Done here means a bounded campaign definition ready for deployment-profile review.
