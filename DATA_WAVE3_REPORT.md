# Data wave 3 — stable-identity / alias PREPARATION (not the complete pipeline)

Base d28be08, branch wave3/data-20261116. Spec: 2026-11-12-pit-data-pipeline-design.md §4.15, components B/C.
Synthetic data only; no private/vendor data read; no pushes, deploys, Todoist edits, VPS or broker effects.

## What this is
Preparation only: a pure, unwired alias module. It is NOT the Sharadar bar importer, NOT the universe
materializer, NOT PIT verification, and adds no `verified_pit`. No qualified output, schema, provider/
importer publication semantics, or protected path changed.

## Changed files
- `algua/data/security_identity.py` (new, unprotected, pure): `stable_symbol(permaticker)` -> `SHR_<n>`;
  `AliasInterval` (half-open `[start,end)`); `Rename`; `AliasTable` (`stable_for(ticker, date)`,
  `ticker_for(stable, date)`, `history`) which refuses overlap per ticker and per security;
  `alias_table_from_tickers(read_tickers frame, renames)`.
- `tests/test_security_identity.py` (new): synthetic rename, ticker reuse (ZZRU fixtures), date
  boundaries (last price date inclusive, next day unowned), overlap/bad-input refusals, missing first date.
- `DATA_WAVE3_REPORT.md`.
Commit: see `git log -1` on the branch (scoped commit, message "data: preparatory stable security alias table").

## Checks actually run (macOS, no Docker, no CLI import needed)
- `uv run pytest -q tests/test_security_identity.py -n0`: 6 passed.
- `uv run ruff check` on both files: clean. `uv run mypy algua/data/security_identity.py`: clean.
- `uv run lint-imports`: 31 kept, 0 broken. `tests/test_module_size_ratchet.py`: 4 passed.
- NOT run: Linux/Docker CLI tests (none touch the CLI; pending via parent), full suite.

## Design notes / limits
- TICKERS gives one current ticker per permaticker plus first/last price dates, so earlier names need
  explicit `Rename` records. Where those come from (ACTIONS ticker changes? vendor related-ticker field?)
  is unresolved; I did not read vendor data to decide.
- Alias spans are price-trading spans, not membership. Nothing infers historical membership.
- `SHR_` prefix is my choice (owner may override); keys are alnum+underscore so safe as bar `symbol`.

## Blockers / for human review (not done here)
1. Wiring: the Sharadar bar importer (component B; `algua/data/importers/`, provider `sharadar.py`) must
   emit `stable_symbol` as `symbol`, and the execution edge (broker ticker <-> stable key, incl.
   broker-held positions) must call `ticker_for`/`stable_for`. Execution/registry paths are CODEOWNERS-
   protected or authority-bearing -> human review. Deferred until prerequisite acceptance (revision
   comparison and the one unresolved acquisition from the initial13-security sample).
2. Alias persistence: no store or schema exists; storing the table (new snapshot dataset) is a schema/
   manifest change, deferred.
3. Universe materializer (C) must emit stable keys into `data import-universe`; the frozen
   deploy/research/us-liquid-common-v1.json definition is untouched.
4. `algua/data/store/delistings.py` / `backtest/delisting.py` (component D) and PIT verifier (I) remain
   protected future work.
