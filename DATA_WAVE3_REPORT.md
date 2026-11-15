# Data wave 3 — stable-identity / alias PREPARATION (not the complete pipeline)

Base d28be08, branch wave3/data-20261116. Spec: `docs/superpowers/specs/2026-11-12-pit-data-pipeline-design.md`
§4.15, components B/C. Synthetic data only; no private/vendor data read; no pushes, deploys, Todoist edits,
VPS or broker effects, no Docker, no agents. The acceptance card stays in Review; the initial13-security
revision comparison and the one unresolved acquisition remain open blockers. The frozen universe
`deploy/research/us-liquid-common-v1.json` is untouched.

## Correction to the earlier run
An earlier commit (449f2bb) added `algua/data/security_identity.py` + `tests/test_security_identity.py`.
That module built historical aliases from the CURRENT ticker plus first/last price dates, which invents
alias coverage, and it had no production caller. **Both files are deleted in this change.** Nothing from
them is a recommendation.

## What this change contains
- `tests/test_sharadar_identity_evidence.py` (2 tests, synthetic rows, existing `read_tickers` only): pins
  that a reused ticker is two distinct permatickers with disjoint price spans, and that TICKERS has one
  current ticker per permaticker and no prior-name column.
- This report. No production code, schema, store, importer/provider publication semantics, qualified output,
  `verified_pit`, or protected path changed.

## Findings (code-located)
1. `read_tickers` (`algua/data/importers/sharadar_tables.py:95`) yields one row per SEP permaticker with only
   the current `ticker` and first/last price dates. Renames are not representable, so dated aliases cannot
   be derived from it. Alias spans from price dates are price spans, not an alias history, and never
   membership.
2. `SharadarBarProvider.get_bars` (`algua/data/providers/sharadar.py:24`) is keyed on exact vendor ticker per
   request and already records `security_identity: exact_vendor_ticker;historical_identity_not_verified`.
   That label should change only after prerequisite acceptance.
3. Universe path (`algua/data/constituents.py` `_norm_symbol`/`constituents_to_snapshots`, store
   `algua/data/store/universe.py`) takes opaque symbol strings. A stable key would pass through unchanged,
   so component C needs no store change to carry stable keys.
4. The only current permaticker consumers are the validation checks (`sharadar_check*.py`), which read
   TICKERS but do not build identity.
5. Execution edge: `algua/execution/alpaca_broker.py` (~L317-352) matches `intent.symbol` against broker
   symbols directly. A stable-key to broker-ticker mapping there is protected/authority-bearing.

## Prospective seams (all deferred)
- B (importer/provider): emit `SHR_<permaticker>`-style stable key as bar `symbol`; needs a trusted dated
  alias source. Open question: whether the vendor exposes ticker-change history (ACTIONS ticker-change rows
  or a related-ticker field). Decide from the acceptance sample, not from this synthetic work.
- Alias persistence: a new snapshot dataset plus manifest entry (schema/manifest change).
- Execution edge: `ticker_for`/`stable_for` at broker submit and broker-held reconciliation
  (CODEOWNERS/authority review).
- Refusal rules any future alias builder needs: explicit dated inputs only, no gaps, no overlap per ticker
  or per security, unknown ticker/date refuses.

## Checks actually run (macOS, uv, `-n0`)
- `pytest -q -n0 tests/test_sharadar_identity_evidence.py`: 2 passed.
- `ruff check` on that file: clean.
- NOT run: Linux/Docker CLI tests (none touch the CLI), mypy, lint-imports, size ratchet, full suite.

## Blockers
Prerequisite acceptance (revision comparison, one acquisition) unresolved; trusted dated alias source
unidentified; execution-edge and delisting/PIT-verifier work are protected human-reviewed scope. This is
preparation only. No completion or real-money readiness claim.
