![Algua — agent-first algorithmic research](docs/brand/readme-banner.svg)

# Algua

Building a mostly autonomous quantitative trading company, with net trading profit as the product.
Start with the [vision of record](docs/PRD.md), the [current architecture](docs/architecture.md),
and the [implementation gaps and roadmap reconciliation](docs/vision-reconciliation.md).
See `docs/agent/` for operating docs. Dated material in `docs/superpowers/` preserves design history.
Brand assets and usage guidance live in [`docs/brand/`](docs/brand/README.md).

## Quickstart
```
uv sync
uv run algua doctor
```

## Data snapshots
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

## Containerized research-loop runs (local-first)

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
ALGUA_DB_PATH=/path/to/existing/registry.db uv run algua research campaign-menu \
  --budget 4 --novelty-min 1 --novelty-max 2
# Supply a NEW disposable directory; the example refuses reuse and ignores ALGUA_DB_PATH.
uv run python scripts/examples/campaign_feedback.py --output-dir "$TASK6_SCRATCH/new-demo"
```

The command reads lifetime idea attempts and negative-result context, then returns deterministic
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
