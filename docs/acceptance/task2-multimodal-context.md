# Task 2 acceptance — research-only multimodal context

> Historical acceptance record for the first Task 2 slice. The protected canonical-backtest
> integration is now tracked in `docs/acceptance/task2-score-backtest.md`; paper/live/frozen
> execution remains unsupported.

## Delivered boundary

This change adds a non-production compatibility vertical only:

- `AsOfView` and `AsOfContext` are pure contracts with defensive frame and nested model-metadata
  copies. `as_of` is a decision cutoff, not a fabricated source-observation timestamp. Daily bar
  indexes retain the frozen contract's UTC-midnight session-label meaning.
- The research composer supports simultaneous bars, PIT-masked news/fundamentals and pinned models.
  It delegates bitemporal masking to `backtest.pit_view`, resolves model metadata and bytes together
  through the existing verified model registry, and refuses a model trained after the first
  decision.
- `score_context` requires declared modalities/models and accepts only finite, unique, in-universe
  per-symbol scores.
- `LegacyStrategyAdapter` calls the existing `LoadedStrategy.signal()` and then the unchanged
  `LoadedStrategy.construct()` path, including overlays, capacity and gross-utilization tightening.
  It is not a hidden combined-input closure and is not a second weight-production path.

The boundary is research-only: it is not wired into backtest, sweep, paper, live, frozen planner,
promotion, artifact identity or deployment. It writes no authority, trading or capital state.

## Repeatable read-only exercise

Pass a private pilot manifest explicitly; there is no absolute product default:

```bash
uv run python scripts/multimodal_context_exercise.py \
  --manifest /path/to/campaign-pinned/campaign_manifest.json \
  --output /path/to/scratch/task2-multimodal-exercise.json
```

The script requires canonical `pilot_real_proxy` provenance, performs a full logical-bars hash
readback against the manifest identity, and then reads the manifest-adjacent immutable bars store
through `StoreBackedProvider`. It refuses an output path inside that read-only input store. News
and model inputs are clearly marked synthetic contract fixtures and the temporary model registry
is created under the caller's output directory. Evidence carries the canonical data tier,
universe method, coverage and complete limitation set, and explicitly denies alpha, qualification,
historical PIT-universe and elapsed-forward claims. It performs no acquisition or data sharing.

## Remaining protected integration at delivery time

Full Task 2 completion requires a separately owner-reviewed protected change:

1. `algua/strategies/base.py`: replace mutually exclusive legacy modality flags with the reviewed
   context-aware authored scoring path while preserving serialized/config-hash compatibility.
2. `algua/strategies/loader.py`: bind context strategies and their complete model/input identity;
   retain verified model resolution and first-party artifact closure semantics.
3. `algua/backtest/decision_path.py` and likely `algua/backtest/engine.py`: assemble one context at
   each decision, stamp all input identities, retain `t -> t+1`, and prove canonical/fast parity.
4. `algua/registry/frozen_view.py`, `algua/registry/artifact_preparation.py` and frozen planner/live
   modules only if config decoding, deployment eligibility or non-research support expands.

Do not remove the compatibility adapter until every supported legacy strategy has score, weight and
decision parity on identical pinned inputs and the single protected context path is accepted. Paper
and live remain unsupported until their data availability, frozen wire, identity and lane-parity
requirements are reviewed and implemented.
