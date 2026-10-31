---
status: in-progress
baseline_commit: db6860000f87a6cc98469e0e4901fa9c10c0d277
---

# Real-data pilot provenance: first working slice

## Outcome

An operator can label a new `data ingest-bars` snapshot with a strict, versioned research
provenance declaration. The declaration is bound into the existing snapshot identity through the
existing `source_metadata` input. This slice does not change snapshot-ID or content-hash
algorithms, the frozen bar contract, registry state, promotion gates, or refresh/operator behavior.

## Acceptance contract

1. The reserved `source_metadata["research_provenance"]` value is a canonical JSON string with
   schema version `pilot-provenance/v1`. It contains exactly: `data_tier`, `universe_method`,
   `limitations`, observed UTC `coverage_start` and `coverage_end`, and `provider`.
2. `data_tier` has exactly three readable values: `pilot_real_proxy`, `verified_pit`, and
   `synthetic_fixture`. An absent reserved key decodes as `None`/JSON `null`; it is not a fourth
   tier and is never inferred from provider metadata.
3. Writes cannot mint `verified_pit` because this slice has no evidence verifier. Valid existing
   envelopes retain and return their actual tier when decoded.
4. A `pilot_real_proxy` declaration always receives the complete v1 proxy-limitation set. Tokens
   are closed-vocabulary, unique, and sorted, so omission cannot hide known bias.
5. Declared bars derive coverage and symbols from normalized bars. Coverage is never supplied by
   a CLI flag, and the observed symbol set must equal the requested symbol set.
6. General `source_metadata` cannot inject the reserved key. The shared metadata builder and the
   direct prebuilt-parquet path reject it. Direct manifest append validates any present envelope
   before creating or modifying the manifest.
7. Re-ingesting identical bars and provenance deduplicates to the existing record. Changing only
   provenance produces a different snapshot ID while leaving the original immutable. Reloading a
   record preserves its exact ID and envelope. Flat and streamed hash algorithms remain distinct;
   no cross-algorithm equality is asserted.
8. `data ingest-bars` accepts `--data-tier`, `--universe-method`, and repeatable `--limitation`.
   Declaration validation runs before provider resolution/fetch. Omitting all options preserves
   legacy unlabeled behavior.
9. Fresh refresh/operator writes remain unlabeled. If refresh finds a reusable declared snapshot,
   it returns that exact record, tier, and ID without fetching or relabeling it.

## Explicitly later

Provenance propagation and policy gates are not part of this slice. A later admitted slice must
carry the field through `data inspect`, backtest, walk-forward, sweep, trial records, promotion via
read projections, reruns, registry projections, board, and API. Board/API selection must be
latest-not-best. That later work may add read projections but must not add registry writes merely
to expose provenance.

The real 150–300 symbol pilot dataset, PIT verification, promotion policy, and full Task 1
completion remain later work. The bounded yfinance smoke below is not that dataset. No broker
smoke is authorized. `data verify` retains its current readability/row-count baseline; this slice
does not claim that it recomputes every content hash. Direct manifest validation checks envelope
syntax, tier, metadata coverage/provider, and metadata-derived ID; it does not prove a direct
caller's payload coverage or hash. The typed store path derives coverage from normalized bars.
A hostile same-UID manifest writer remains outside this metadata-label slice's threat model.

## Focused evidence

- RED: `tests/test_research_provenance.py` initially failed collection because the provenance
  module did not exist.
- GREEN: envelope validation, canonical round-trip, legacy `None`, actual-tier readback,
  `verified_pit` refusal, reserved-key/direct-manifest guards, observed coverage/symbol binding,
  identity/dedup/immutability, refresh reuse, and pre-fetch CLI validation are covered by focused
  tests.

## Entrypoints and scope

| Surface | This slice | Later propagation gate |
|---|---|---|
| `data ingest-bars` | Explicit typed declaration, validation before fetch; normalized observed coverage | Run/result projections |
| `data ingest` / `import-bars` | Existing unlabeled CLI; reserved key injection refused | No implicit provider classification |
| `data refresh-bars`, paper/live operator `--refresh` | No lane change; fresh rows unknown, reused rows retain actual ID/tier | No promotion authority from tier |
| Direct normal/streamed store | Typed declarations; symbols and observed coverage checked | Same immutable store/manifest |
| Other store writers and prebuilt `_ingest_parquet` | Shared reserved-key refusal | No provenance feature for non-bars |
| Direct `SnapshotManifest.append_if_absent` | Canonical envelope, tier, provider/metadata coverage and ID checks before manifest commit | Payload verification is not added here |
| Inspect | Existing raw canonical string survives CLI readback | Decoded, snapshot-keyed nullable read projection |
| Backtest / walk-forward / sweep / trial / promote / reruns | Unchanged; no registry writes or protected gate changes | Every bound snapshot must project actual tier; trials resolve parent; invalid distinct from legacy |
| Registry run projection / board / API | Unchanged; `strategy-board/v1` not extended | Separately admitted read/UI contract, latest-not-best and identity-bound; unknown null, not zero |

Implementation file allowlist inspected against root `CODEOWNERS`: `algua/data/research_provenance.py`,
`algua/data/provenance_binding.py`, `algua/data/models.py`, `algua/data/manifest.py`,
`algua/data/store/{identity,bars,bars_streamed}.py`, `algua/cli/data_cmd.py`,
`tests/test_research_provenance.py`, `tests/test_provenance_edges.py`, and this story. None matches
a protected rule at the baseline. `compute_snapshot_id` and content-hash functions are unchanged;
`identity.py` only gains reserved-key refusal. The existing protected canonical JSON helper is
imported without modification. No ratchet or integrity test is weakened.

## Executed readiness — 2026-10-31

The latest owner amendment authorizes Codex implementation and this concise acceptance contract
in one PR, superseding the earlier five-doc/draft-only and docs-first merge ceremony. No new
planning cards or mandatory documentation subtree are introduced. Task 0 PR #715 at
`97af8dd778f14f4e678d044087fd5966ef8bc1a3` was read as proposed, unmerged material, not authority;
its root/web checks passed and both Security checks failed at observation. The source bundle's
Task 1 intent is incremental; this ingest-only slice is not its end-to-end acceptance.

- Installed Codex 0.164.0 authored the implementation in workspace-write mode, fresh session
  `01a19167-1b21-7e32-8d25-0daeec3c0daf`; no bypass flag. Coordinator added adversarial tests,
  reused canonical JSON instead of a duplicate encoder, and recorded evidence. Independent review
  is pending on existing child `t_6024ead5`, which must use a separate fresh Codex session.
- Locked offline `uv sync` succeeded with uv 0.9.26 and installed CPython 3.12.12 in a scratch
  environment; no toolchain pin, dependency, or lockfile changed.
- Focused plus adjacent data/CLI/refresh/lane/manifest/ratchet tests: **125 passed**. The first
  ratchet run found the new parser at 300 lines; reusing the existing canonical encoder fixed the
  root cause without raising the ratchet. New-feature tests alone: **41 passed**.
- Four disposable-copy mutations were killed: manifest validation bypass, unverifiable PIT append,
  ID-binding bypass, and reserved-key bypass. Clean baseline and restored copy each passed all 41.
- Preliminary Ruff, mypy (`algua scripts`, 362 files), and import-linter (29 kept, 0 broken) passed.
- Sanitized scratch-CWD CLI root/ingest/inspect/verify help and default `doctor` each exited 0.
  Doctor is not trading readiness: broker credentials absent; live authorization probe skipped.
- **Real yfinance smoke PASS:** AAPL and MSFT, daily `[2024-10-21, 2024-10-26)`, `adjustment=none`,
  `as_of=2026-10-31T10:07:29.978179+00:00`, method `small-smoke-proxy/v1`. Snapshot
  `012216cbc9f5657f`, content hash
  `e199640269743577a1dd88831d56949d1930d4b999141d742d398faea5405120`.
  Ingest, exact-ID inspect/readback, and existing verify all exited 0. Actual tier and all required
  limitations persisted. Raw bars stay in private scratch storage, never public Git.
- Full final root gates must run sequentially on the committed, stable assembled head. Their
  SHA-bound logs/results are attached separately to avoid a self-referential report amendment.
  Known base/default Python 3.12.12 wheel-identity failure remains unresolved in protected
  `planner_environment_lock.py`; no green full-suite result is assumed or compatibility test skipped.
- The larger 150–300 symbol/two-year selection recipe, bounded retry/partial-failure accounting,
  downstream projections, historical PIT verification, and machine/investment acceptance are
  **not delivered** here. Small network success proves neither scale nor vendor stability.

Evidence directory (private):
`/home/liornisimov/.hermes/profiles/alguaeng/cache/scratch/t_40b6c320-evidence`.
No operational registry, broker, orders, live/capital, approval/signer, service/schedule, merge,
deployment, shared canonical guide, or board-contract changes were performed.
