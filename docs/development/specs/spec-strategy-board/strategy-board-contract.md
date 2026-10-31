# Strategy board response contract

`algua runs board` is a pure read. The monitor exposes the same data at
`GET /api/strategy-board` through the existing subprocess JSON seam.

```json
{
  "schema_version": "strategy-board/v1",
  "count": 1,
  "rows": [
    {
      "strategy_id": 22,
      "name": "high52_proximity",
      "family": null,
      "stage": "paper",
      "latest_gate": {
        "run_id": 901,
        "created_at": "2026-10-15T12:00:00+00:00",
        "passed": true,
        "sharpe_oos": 0.81,
        "total_return_oos": 0.12,
        "max_drawdown_oos": -0.08,
        "n_obs_oos": 126,
        "mean_window_sharpe": 0.73,
        "min_window_sharpe": 0.19,
        "pct_positive_windows": 0.75
      }
    }
  ]
}
```

## Field rules

- `schema_version` is exactly `strategy-board/v1`.
- `count` equals `rows.length` and counts registered strategy identities, not runs.
- `rows` follow lifecycle order, then case-insensitive name, then `strategy_id`.
- `strategy_id`, `name`, `family`, and `stage` come from the registry row.
- `latest_gate` is nullable. It is selected only from `runs.kind = 'gate'` where
  `runs.strategy_id = strategies.id`, ordered by `created_at DESC, id DESC`. If that selected
  row has no valid offset-aware ISO timestamp, its recency cannot be trusted and `latest_gate`
  is `null` rather than falling back to a more favorable older run.
- Every metric is a nullable finite scalar already present in the fixed run vocabulary. No metric
  is derived, imputed, or normalized by this projection.
- The contract never returns `derived_from`, config, components, hashes, gate decisions, return
  series, or holdout blobs.

Client-side stage filtering and exploratory ordering operate only over this complete payload. They
may reorder rows but may never replace `latest_gate` or feed a promotion path.

## Opt-in evidence extension

The default command and API response above remain unchanged. `algua runs board
--include-evidence` and `GET /api/strategy-board?include_evidence=true` add top-level
`evidence_schema_version = strategy-board-evidence/v1` and an `evidence` member to every row.
The member is `null` when `latest_gate` is `null`; otherwise it is anchored to that exact
`latest_gate.run_id` and contains only:

- `run_id`;
- atomic `{status, reason, value}` wrappers for `evaluation`, `oos_interval`, and
  `snapshot_provenance`;
- `comparison = {status: UNKNOWN, observed_metric_sort_enabled: false, reasons:
  [historical_cost_context_unavailable, homogeneous_comparison_context_unavailable]}`.

`evaluation.value` is the stored full requested `period_start`, `period_end`, `timeframe`, and
positive `metric_schema_version`. `oos_interval.value` is the inclusive `holdout_start`,
`holdout_end`, and positive `n_bars` reached only through the selected run's exact holdout pointer,
after strategy-identity and `n_obs_oos` count agreement. `snapshot_provenance.value` is the typed
`pilot-provenance/v1` allowlist (`schema_version`, `data_tier`, `universe_method`, all
`limitations`, `coverage_start`, `coverage_end`, `provider`) reached only through the selected
run's exact bars-snapshot pointer. Existing parsers and identity/binding checks are rerun; provider,
name, current artifact, newest snapshot, older run, best metric, or burn-ledger records are never
fallbacks. Readable `verified_pit` metadata remains invalid here because no independent verifier
exists.

Wrapper status is `VALID`, `UNAVAILABLE`, or `INVALID`; non-valid values are atomically `null`.
Bounded reasons are: `missing_fields`, `no_holdout_pointer`, `missing_run_oos_count`,
`no_snapshot_pointer`, `snapshot_not_found`, `provenance_absent`, `source_unavailable`,
`malformed_fields`, `dangling_holdout_pointer`, `strategy_mismatch`, `count_mismatch`,
`malformed_provenance`, `unsupported_provenance_schema`, `snapshot_binding_mismatch`,
`pit_verifier_unavailable`, and `conflicting_snapshot_records`. Evaluation span, OOS interval, and
snapshot coverage are distinct concepts. A valid wrapper means well-formed metadata bound under
these checks, not payload/PIT verification or investment qualification.

The extension exposes no paths, raw configuration, hashes, snapshot IDs, lineage, vectors, cost
placeholders, ranks, or promotion authority. Historical cost and homogeneous comparison context
are absent, so every row remains unranked/UNKNOWN; missing evidence is never zero. Enrichment adds
no writes, migrations, DDL, audit rows, burns, network/provider calls, or broker calls. The existing
CLI bootstrap still opens and migrates the registry before its read, so the command is not claimed
to be globally physically read-only; this extension does not change that legacy behavior.
