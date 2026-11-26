<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/brand/exports/readme-banner-dark.png">
  <img src="docs/brand/exports/readme-banner.png" alt="Algua" width="800">
</picture>

# Algua

Algua researches and tests systematic trading strategies. Its first intraday futures milestone is a
paper desk that trades one Micro E-mini S&P 500 (MES) position at a time through Interactive Brokers
(IBKR). The goal is to measure net dollars after costs before the owner decides whether to sign a
real-money pilot. The futures implementation is under development on the roadmap branch. The default branch currently ships the daily-stock platform.

## Run the daily-stock platform

From the repository root, with Python 3.12 and uv installed, run

```bash
uv sync
uv run algua doctor
```

## Preview the offline futures desk

In a checkout of `roadmap/futures-20261126`, run `uv run algua futures synthetic-smoke`.
The smoke command uses generated minute bars, two fixed-priority proposals and a temporary journal.
Its JSON shows which proposal got the slot, when it filled, how the protective orders resolved and
the result after fees. It runs locally without broker credentials or orders.

| To exercise | Add to the smoke command |
| --- | --- |
| An opening gap through the stop | `--scenario gap_stop` |
| An early close | `--session 2025-01-09` |
| A $400 daily-limit breach | `--scenario daily_limit` (expected exit code 1 with a JSON incident) |

## Futures qualification

- **Market data.** The importer can pin dated-contract minute bars and verify them on readback. Qualifying the historical dataset still requires exchange calendar coverage, vendor contract mappings and a verified export.
- **Research.** The simulator models fills, gaps, fees and skipped trades. The proposed scaling rule exceeded its false-positive target in rare-loss simulations, so statistical acceptance remains open.
- **Paper execution.** An attended IBKR adapter exists. Broker-side protection, account recovery and forward performance still need observations on the intended paper installation.

## Existing daily-stock platform

The daily-stock lane is frozen during migration. Its data and research commands are documented
below. The [architecture map](docs/architecture.md) describes the installation, and the
[operating guide](docs/agent/operating.md) defines its authorization gates.

### Stock data snapshots

For EODHD daily US bars, see the [free demo ingestion and backtest recipe](docs/eodhd.md).
For Sharadar daily US bars and selected ARQ facts, see the [Sharadar integration](docs/sharadar.md).

```
# Register a local file snapshot.
uv run algua data ingest daily-bars \
  --provider local \
  --symbols AAPL,MSFT \
  --start 2026-01-02 \
  --end 2026-01-31 \
  --as-of 2026-02-01T00:00:00+00:00 \
  --source local-csv \
  --from-file data/raw/daily-bars.csv

# Fetch provider bars into a parquet point-in-time snapshot.
uv run algua data ingest-bars \
  --provider yfinance \
  --symbols AAPL,MSFT \
  --start 2026-01-02 \
  --end 2026-01-31 \
  --timeframe 1d \
  --adjustment none

# Record universe membership as of a date.
uv run algua data ingest-universe core \
  --symbols AAPL,MSFT \
  --effective-date 2026-01-02

uv run algua data inspect
uv run algua data inspect --summary
```

### Fundamentals and news

Fundamentals and news ingestion (`data fetch-*`, `ingest-*`, `query-*`) was removed pending a
redesign of context inputs. Existing manifest records still list under `data inspect`, and the
as-of read path is unchanged.

## Containerized research-loop runs (local-first)

For event-driven host research, enable `deploy/systemd/algua-research.path` alongside the existing
six-hour timer. Trusted leap imports touch `ALGUA_DATA_DIR/research-ready`; `research ready` skips
idle or exhausted invocations without starting a model. Configure the path unit for the installed
data directory. `ALGUA_RESEARCH_DAILY_CYCLE_LIMIT=4` admits at most four chooser launches per UTC
day, including failures and existing recorded launches. The worker's per-run CPU, wall-time and
memory caps still apply. This resource budget grants no paper/live authority.

Reproducible, disposable runs that don't pollute the host. One image runs both the loop and the
gate. Prerequisite: `cp .env.example .env` (compose loads it; paper creds only — never live).

```bash
# Build the image.
docker compose build

# A disposable run gets its own DB + mlruns under ./runs/<RUN_ID>/; snapshots + kb are shared :ro.
scripts/run.sh alpha doctor
scripts/run.sh alpha backtest ...        # explore: backtest / walk-forward / sweep

# Re-use an existing run dir on purpose:
ALGUA_REUSE=1 scripts/run.sh alpha ...

# Run the same quality gate the host runs, inside the freshly built image:
docker compose build && docker compose run --rm gate
```

**Exploration vs promotion (important):** disposable per-run DBs are for *exploration* only
(backtest / walk-forward / sweep). `research promote` burns the single-use holdout, which must be
tracked in the **one shared authoritative DB** — running it against a throwaway per-run DB would
silently reuse the holdout across runs. The container refuses `research promote` on a per-run DB
unless you explicitly point `ALGUA_DB_PATH` at the authoritative DB (or set `ALGUA_ALLOW_PROMOTE=1`).

**Assumptions / limits:** linux/amd64; a local filesystem (SQLite WAL is not safe on NFS); data
*ingest* (which writes snapshots) is a separate step, not part of the read-only disposable-run path.

## Advisory campaign feedback (Task6)

```bash
# Supply a NEW disposable directory; the example refuses reuse and ignores ALGUA_DB_PATH.
uv run python scripts/examples/campaign_feedback.py --output-dir "$TASK6_SCRATCH/new-demo"
```

The example reads lifetime idea attempts and negative-result context, then returns deterministic
`CampaignChoice(category, hypothesis_id, reason, prior_evidence_ids, budget)` options. One budget
unit is an attempt slot. Set `TASK6_SCRATCH` to an authorized scratch directory for the example.
Novelty uses unseen pool families (category fallback); an unavailable
novelty reserve stays unspent. Missing DB/schema and a source changing during capture refuse as
JSON. Source DB/WAL files are copied to a private temporary directory before SQLite opens them;
there is no source connection, migration, claim, KB write, or scheduling change.

Attempted, completed, unfinished, invalid, run-error, abandoned, economically rejected, preview
and promoted counts remain separate. Preview is provisional; negative-log labels never become
economic evidence or additional trials. These counts do not estimate alpha or independent trials.
Duplicates reuse the existing signature/family comparison. A changed hypothesis needs a new pool
entry with `duplicate_of_idea_id` identifying a colliding older Idea. Its `override_reason` must
begin `changed_fields=source_ref,falsification;` (choose the actual changed fields), followed by
exact `ideas:ID`, `idea_attempts:ID`, and `negative_results:ID` anchors and a distinct explanation.
Separate anchors with whitespace, commas or semicolons. Supported fields are `source_ref`,
`source_date`, `falsification`, `required_data`, `market` and `horizon`. Every declared field must
have a nonempty persisted value different from the parent; at least one must differ from every
colliding entry. Mere prose, cosmetic falsification edits and reordered data requirements do not
establish a change. All collision attempts and matching negative logs must be cited; every cited
ID must resolve to this causal history. An unattached log alone cannot establish changed inputs.
The new entry must postdate all blocking ideas, attempt claims/outcomes and negative logs; missing,
ambiguous or stale timestamps fail closed. Freshness uses persisted timestamps, never today's date.
Reused normalized explanations and unfinished/preview duplicate work are excluded. These checks
validate recorded differences and references, not semantic truth or independent economic evidence.
`exclusions` maps idea IDs to `{reason, prior_evidence_ids}` objects, including the exact blocking
ideas, attempts and matching negative logs even when the idea itself is claimed or already attempted.

Acceptance mapping: `tests/test_campaign_policy.py` covers history causality, duplicate exceptions,
rejected yield, non-alpha failures, bounds, reserves and determinism;
`tests/test_campaign_registry.py` covers truthful persisted denominators, WAL reads and refusals;
`tests/test_campaign_experience.py` covers consolidated family notes in the existing experience
domain. The executable example saves before/after menus, explicit **SYNTHETIC_FIXTURE** outcomes,
evidence IDs, reasons, counts and KB notes in its disposable directory. It demonstrates feedback,
not autonomous research cycles, market qualification or deployment authority. Full-root testing,
independent review and publication remain coordinator acceptance steps.
