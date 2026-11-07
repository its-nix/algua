# Pinned Model Through the Frozen Paper Planner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Available equivalents are `nixkit:subagent-driven-development` and `nixkit:executing-plans`.

**Goal:** Run one pinned daily price-linear context strategy through the same scoring path in research and the frozen paper planner, with recoverable model assets and preserved legacy compatibility.

**Architecture:** Extend the existing frozen descriptor and wire with an explicit model-capable version. Package model bytes and provenance inside the verified bundle; the child resolves its model only from that bundle. Reuse the current scorer, construction, supervisor, invocation evidence and paper release machinery.

**Tech Stack:** Python 3.12, uv, existing pandas/Pydantic/PyArrow/pytest dependencies, canonical JSON, current immutable artifact and model registries. No new dependency.

**Spec:** [Approved strategy delivery design](../specs/2026-11-07-strategy-cicd-design.md), especially §4 and its acceptance criteria.

## Global Constraints

- This plan implements the first delivery only; it does not implement the complete investment/live pipeline.
- One daily `context_v1` strategy, bars and one explicitly pinned price-linear model; no training at inference, model grids, pickle loading or second scorer.
- Keep the frozen `DataProvider.get_bars` contract and `decision_lag_bars >= 1` unchanged.
- Preserve candidate qualification, allocations, current forward promotion, human-only live activation and the existing ILS 2,000 experimental envelope.
- The five-session paper profile and proposed 20% drawdown policy are subsequent protected deliveries. Do not change 63 observations, 95% confidence, any breaker or any signature policy here.
- Preserve v1 descriptor/wire output for existing bars-only artifacts. A v2 request must never run against a v1 bundle, or vice versa.
- Missing authority-denying execution isolation refuses authoritative generated-strategy execution. Process-group containment and fixture tests do not establish that isolation.
- Real paper operation requires an eligible candidate, configured paper account and approved execution isolation. No synthetic gate row, historical-proxy label or fixture is investment qualification.
- Changes in protected files require the existing human review; no automatic merge, deployment, timer activation or trading follows from this plan.
- Keep pinned modules within their size ratchets; place cohesive new behavior in the new files named below. Do not increase line budgets to fit the feature.

## Review Focus

1. A valid model file paired with another version's provenance must refuse, even when both files parse; Task 1 tests this.
2. A context config decoded with the legacy hash must refuse; a legacy artifact's identity and request bytes must remain unchanged; Tasks 2 and 4 test this.
3. A correct model with a future training cutoff must not score a decision; a warmup bar must not become the first evaluated decision; Task 3 tests this.
4. Changing bars snapshot, model reference or protocol between phases must invalidate the binding before effects; Task 4 tests this.
5. Missing isolation or model-store fallback must not turn an offline engineering demonstration into authorized paper execution; Task 5 tests/refuses this.

## Scope and delivery order

Execute Tasks 1–5 in order. Each produces a focused, reviewable commit. Begin implementation in an isolated feature worktree using the worktree skill; preserve this documentation branch.

The first four tasks produce recoverable artifacts and a broker-free production-planner parity proof. Task 5 connects that capability to paper only when its existing authority prerequisites are met. If isolation or an eligible account/cohort is unavailable, preserve the explicit refusal and report real paper acceptance as unperformed. Do not invent an always-true admission guard to finish the plan.

News integration, the new economic/operational certificate policy, frozen live dispatch/signing and the capital/pause amendment each need a separate implementation plan. Their order and policy conflict are recorded in design §§5–6.

---

### Task 1: Portable, verified model assets

**Files:**
- Create `algua/contracts/frozen_model.py` for the pure closed asset descriptor.
- Create `algua/registry/frozen_model_assets.py` for the portable codec, bundle file creation and bounded bundle reads.
- Create `tests/test_frozen_model_assets.py`.
- Modify `CODEOWNERS` and the integrity-critical assertions in `tests/test_repo_hygiene.py` to protect these new authority-sensitive modules.

**Interfaces:**
- Consumes existing `ModelRef`, `ModelVersion`, `ModelHandle`, `FrozenFile`, `compute_provenance_digest`, and `features.price_linear_context.validate_proxy_model(handle)`.
- Produces `FrozenModelAsset(ref: ModelRef, artifact_sha256: str, provenance_sha256: str)`; its three fields are the complete descriptor. Both outer hashes are full lowercase 64-hex SHA256. Existing model-ref digests retain their current representation.
- Produces `pack_model(handle: ModelHandle) -> tuple[FrozenModelAsset, tuple[FrozenFile, ...]]` in `registry/frozen_model_assets.py`.
- Produces `unpack_model(asset: FrozenModelAsset, artifact: bytes, provenance: bytes) -> ModelHandle` in `registry/frozen_model_assets.py`. The contracts module must not import registry, features or any other Algua layer to perform codec validation.
- Produces `read_bundle_model(bundle_root: Path, asset: FrozenModelAsset) -> ModelHandle` in `registry/frozen_model_assets.py`.

Use exactly `_algua/model/artifact.json` and `_algua/model/provenance.json`; never take a path from a model name or metadata. Artifact size is at most 64 KiB, matching the existing linear codec; provenance size is at most 1 MiB, matching the existing producer report bound. Read no more than limit + 1. Reject non-regular files, symlinks and oversize content using existing bounded-file patterns.

Portable provenance is canonical JSON with exactly `name`, `version`, `digest`, `created_at`, `training_snapshot_id`, `training_as_of`, `code_hash`, `hyperparameters`, `seed`, `eval_report`, `provenance_digest`. Omit machine-local `artifact_path`; reconstruct it as `None`. Reject duplicate keys, extra/missing keys and coercive types. Verify both full outer hashes, exact pin equality, existing artifact/provenance digests and the existing producer-profile validator. Neither codec fits a model or imports strategy code.

- [ ] **Step 1: Add asset regression tests.** Reuse the `trained` fixture from `tests/test_trained_model_context.py`; its final two tuple entries are the verified version and bytes. Cover round-trip, swapped provenance, changed bytes, incorrect pin, unsafe files and both size limits. The core assertion is:

```python
def test_pack_roundtrip_keeps_pin_and_bytes(trained):
    version, raw = trained[-2:]
    asset, files = pack_model(ModelHandle(version, raw))
    contents = {item.path: item.data for item in files}
    restored = unpack_model(asset, contents['_algua/model/artifact.json'],
                            contents['_algua/model/provenance.json'])
    assert restored.version.as_ref() == version.as_ref()
    assert restored.artifact_bytes == raw
    assert restored.version.artifact_path is None
```

- [ ] **Step 2: Run** `uv run pytest tests/test_frozen_model_assets.py -q`; expect missing new interfaces initially, and meaningful content/identity failures while implementing.
- [ ] **Step 3: Implement the interfaces and closed formats above.** Reuse the numerical codec and existing provenance digest definition, rather than defining a competing identity.
- [ ] **Step 4: Run** `uv run pytest tests/test_frozen_model_assets.py tests/test_trained_model_context.py tests/test_model_config_and_loader.py tests/test_repo_hygiene.py::test_integrity_critical_modules_are_codeowner_protected -q`; require all passing.
- [ ] **Step 5: Commit** `feat: package verified pinned models as frozen assets`.

### Task 2: Model-capable descriptor and exact config identity

**Files:**
- Modify `algua/registry/frozen_manifest_contract.py`, `artifact_manifest.py`, `artifact_recording.py`, `artifact_verification.py`, and `frozen_view.py`.
- Modify `algua/contracts/strategy_identity.py`; retain its exports through `algua/strategies/base.py`.
- Create `algua/registry/frozen_model_manifest.py` for model-profile parsing if needed to keep existing modules focused.
- Create `tests/test_frozen_model_manifest.py`; extend `tests/test_frozen_view.py` and existing artifact ledger tests.
- Protect the new manifest module through `CODEOWNERS` and the existing integrity test.

**Interfaces:**
- Consumes Task 1's `FrozenModelAsset` and `read_bundle_model`.
- Extend `FrozenManifest` with trailing defaulted fields `strategy_interface=LEGACY_INTERFACE` and `model_asset: FrozenModelAsset | None = None`.
- Extend `strategy_config_hash(config, *, strategy_interface: StrategyInterface = LEGACY_INTERFACE) -> str`. Have `loaded_config_hash(strategy)` use that helper. Both existing legacy and context hashes must remain identical to their pre-change values.
- Preserve `parse_frozen_manifest(raw: str) -> FrozenManifest` and the existing deployment/verification public signatures.

Legacy manifests retain exactly the old root keys and values, `assets=[]`, descriptor/boundary/planner/wire versions 1 and the old digest. Model manifests use those four versions as 2, add the explicit `strategy_interface='context_v1'`, and put exactly the Task 1 descriptor in a one-element `assets` array. The asset files remain part of the normal verified bundle inventory. `asset_digests_json` is the canonical asset array, never `[]` for a model manifest. Keep old exported v1 constants stable; choose the profile from the parsed manifest instead of globally bumping every writer.

The model profile requires daily execution, `needs_model=True`, exactly one pin equal to the asset ref, `needs_news=False`, and `needs_fundamentals=False`. Decode exact JSON types before constructing `ModelRef` and `ExecutionContract`. Hash the config with its explicit interface. All unsupported combinations refuse through the existing bounded artifact/tenant errors.

- [ ] **Step 1: Add tests** `test_v1_bytes_and_digest_unchanged`, `test_v2_model_manifest_roundtrip`, `test_context_interface_is_required_for_config_hash`, `test_ledger_asset_projection_cannot_disagree`, and `test_unknown_mixed_or_downgraded_profile_refuses`. Capture a real pre-change v1 manifest/request golden from the existing fixtures before changing writers. Assertions include:

```python
assert parse_frozen_manifest(v1_json).json == v1_json
assert parse_frozen_manifest(v1_json).digest == v1_digest
assert frozen_deployment_manifest(model_manifest).asset_digests_json == canonical_json(
    model_manifest.to_dict()['assets'])
assert decode_frozen_config(model_manifest).model_ref == model_manifest.model_asset.ref
```

Here `v1_json`/`v1_digest` are the captured fixture golden; `model_manifest` is that fixture rebuilt with a Task 1 asset and context config, not a production row.

- [ ] **Step 2: Run** `uv run pytest tests/test_frozen_model_manifest.py -q`; establish the intended failures.
- [ ] **Step 3: Implement** the two explicit profile encodings, strict readers, interface-aware decoding and full asset verification. Keep malformed content, unavailable content and unsupported profile errors distinct using existing error classes.
- [ ] **Step 4: Run** `uv run pytest tests/test_frozen_model_manifest.py tests/test_frozen_artifact_contract.py tests/test_frozen_artifact_ledger.py tests/test_frozen_artifact_verification.py tests/test_frozen_view.py tests/test_score_context_backtest.py -q`; require all passing.
- [ ] **Step 5: Commit** `feat: version frozen model descriptors without changing legacy identities`.

### Task 3: Shared context scoring and bundle-only model loading

**Files:**
- Create `algua/strategies/context_inputs.py`; move the existing pure `build_context` implementation from `algua/backtest/context.py` and re-export it there for compatibility.
- Modify `algua/strategies/loader.py`, `algua/registry/artifact_preparation.py` and `algua/live/frozen_child.py`.
- Create `algua/strategies/frozen_model.py` for the narrow frozen-model admission/loader, and protect it and the shared context module.
- Create `tests/test_frozen_model_loading.py`; reuse existing trained-model/authoring fixtures.

**Interfaces:**
- Preserve `build_context(strategy, *, decision_ts, first_decision_ts, universe, bars, bars_snapshot_id, fundamentals, fundamentals_snapshot_id, news, news_snapshot_id) -> AsOfContext` exactly, including its argument names. Use the existing annotations from `backtest/context.py`; introduce no backtest import into live or strategies.
- Extend `load_strategy(name: str, *, reload: bool = False, model_resolver: Callable[[str, StrategyConfig], ModelHandle] | None = None) -> LoadedStrategy`. `None` retains the current registry resolver. A supplied resolver must still pass the existing `LoadedStrategy` byte/pin/provenance validation.
- Produce `load_frozen_model_strategy(name: str, *, model: ModelHandle) -> LoadedStrategy` in `strategies/frozen_model.py`; admit only the Task 2 profile and existing price-linear producer codec.
- Preserve `load_tradable_strategy(name: str)` as the current legacy-only entry point. Do not allow mutable live/working-tree paths to acquire model eligibility as a side effect.

Preparation may capture the explicitly pinned model from the current registry once. Validate the profile, package its files and recheck the pin/bytes/provenance during existing final pre-record revalidation. Compute identities before and after through the existing algorithm; do not narrow the approved source closure. The child reads only the manifest-bound bundle assets, injects the recovered handle, checks config/interface identity and calls the shared context scorer. It must not consult the host model registry, environment-configured model root, network or `latest`.

- [ ] **Step 1: Add tests** `test_bundle_model_loads_without_host_registry`, `test_loaded_model_still_obeys_bound_pin`, `test_future_training_cutoff_refuses_context`, and `test_unsupported_sidecars_remain_refused`. Patch the host resolver and training function to fail if called. Delete the disposable source model directory before cold child execution. Assert:

```python
assert restored_strategy.model_handle.artifact_bytes == original_model_bytes
assert restored_strategy.config.model_ref == original_pin
with pytest.raises(ValueError, match='first decision'):
    build_context(strategy, **future_cutoff_inputs)
```

Use the existing trained context fixture for `strategy` and its captured bars; `future_cutoff_inputs` sets the first decision before that fixed model's training cutoff. Do not alter provenance to manufacture a supposedly earlier model.

- [ ] **Step 2: Run** `uv run pytest tests/test_frozen_model_loading.py -q`; verify the existing refusal or missing loader fails these cases.
- [ ] **Step 3: Implement** shared composition, injected model resolution and profile-specific preparation/child loading. Keep generic trading refusal intact. Bind the source interface before decoding its config identity; no fallback from `score(context)` to `signal`.
- [ ] **Step 4: Run** `uv run pytest tests/test_frozen_model_loading.py tests/test_trained_model_context.py tests/test_score_context_backtest.py tests/test_frozen_source.py tests/test_frozen_artifact_offline.py -q`; require all passing.
- [ ] **Step 5: Commit** `feat: load frozen context models independently of the source registry`.

### Task 4: Versioned context input and production-planner parity

**Files:**
- Modify `algua/live/planner_contract.py`, `planner_binding.py`, `planner_decision.py`, `planner_late.py`, `planner_validation.py` and `live_loop.py`.
- Create `algua/live/model_context.py` for pure model-context composition at the late decision. Carve `PlannerContext` and `planner_context_for_deployment` into `algua/live/planner_context.py`, re-exporting them from `live_loop.py` for existing callers, so the pinned loop can shrink rather than grow.
- Create `algua/live/frozen_model_wire.py` for the model-specific extension; modify `frozen_wire.py`, `frozen_wire_result.py`, `frozen_invocation.py`, `frozen_dispatch.py`, and `frozen_child.py` only at their profile-dispatch seams.
- Extend `tests/_frozen_harness.py` for a model bundle, not a second simulation harness.
- Create `tests/test_frozen_model_wire.py` and `tests/test_frozen_model_parity.py`; protect the new wire module.

**Interfaces:**
- Add optional trailing `bars_snapshot_id: str | None = None` to `EarlyPlannerInput`; v2 requires it. Add optional trailing `context: AsOfContext | None = None` to `PlannerInput`.
- Task 2's manifest selects the versioned profile in `FrozenTarget`/`PlannerContext`; existing constructors keep v1 defaults. Extend `planner_context_for_deployment(deployment, calendar_code: str, *, bars_snapshot_id: str | None = None) -> PlannerContext | None`; the paper caller supplies the same exact snapshot used by `FrozenPlanner`. Add trailing `protocol_version: int = 1` and `bars_snapshot_id: str | None = None` to `PlannerContext`. Copy those values into the early request; never synthesize a snapshot ID from dates.
- Produce `build_model_decision_context(strategy: LoadedStrategy, early: EarlyPlannerInput, view: pd.DataFrame, decision_ts: datetime) -> AsOfContext | None` in `live/model_context.py`. Legacy input returns `None`; the supported model profile composes the shared context, with no I/O, before passing it to `plan`.
- Preserve `encode_request(phase, early, late, identity) -> tuple[bytes, bytes]` and `decode_request(request_json, bars_arrow) -> DecodedRequest`. V2 early fields add exactly `bars_snapshot_id` and `model_ref`; model bytes remain in the bundle, not request JSON. Derive `model_ref` from the recorded config and require exact equality when decoding.
- `PlannerInput.protocol_version` and `PlannerResult.protocol_version` reflect the selected profile. Existing v1 positional constructors and v1 output remain unchanged. V2 results carry wire version 2 with the existing closed result shapes; do not let a version-1 envelope represent a version-2 decision.

In v2, bind the bars snapshot, model pin, interface and version in addition to the existing bars/config/state binding. Validate that the two phases and descriptor agree. For a paper tick there is one evaluated decision, so set context `first_decision_ts=decision_ts`; each fixed model must already be knowable by that decision. For multi-decision research replay retain its fixed first evaluation cutoff. Warmup history is input history, not an evaluated decision or a reason to backdate model availability.

`plan` dispatches context strategies through `target_weights_context(context)` and legacy strategies through the existing `target_weights(view)`. Preserve canonical weight validation, construction/overlays, held-symbol exits, risk checks and later-bar execution. The supervisor validates typed outputs and owns every effect; it does not import the authored scorer.

- [ ] **Step 1: Add tests** `test_v1_request_and_binding_golden_unchanged`, `test_model_v2_request_roundtrip`, `test_cross_version_child_refuses`, `test_changed_snapshot_or_model_invalidates_phase_b`, and `test_model_scores_weights_and_intents_match_research`. Use existing real-child launch fixtures; compare the actual child to the canonical scorer on identical bars and pin. Assert:

```python
pd.testing.assert_series_equal(actual_scores, expected_scores, rtol=1e-12, atol=1e-12)
pd.testing.assert_series_equal(actual_weights, expected_weights, rtol=1e-12, atol=1e-12)
assert actual_decision_ts == expected_decision_ts
assert actual_intents == expected_intents
assert legacy_request_bytes == v1_request_golden
```

The canonical expected values come from the existing scorer/construction and `build_intents`; do not duplicate the forecasting formula in the test. Keep decision lag one in the canonical fill-timing comparison. Add malformed/absent snapshot and future-cutoff refusal cases, including warmup-only inputs.

- [ ] **Step 2: Run** `uv run pytest tests/test_frozen_model_wire.py tests/test_frozen_model_parity.py -q`; establish failures before changing the protocol.
- [ ] **Step 3: Implement** profile-dispatched codecs and planner composition. Protect the new context/wire modules using the existing integrity policy. Preserve all v1 byte limits; v2 adds no model-byte transport and retains the existing request/output/time limits. Only newly model-capable artifacts use version 2. Update unsupported-version fixture cases from version 2 to an actually unsupported version such as 99; retain explicit wrong-profile v1/v2 tests.
- [ ] **Step 4: Run** `uv run pytest tests/test_frozen_model_wire.py tests/test_frozen_model_parity.py tests/test_two_phase_planner.py tests/test_planner_parity.py tests/test_frozen_wire.py tests/test_frozen_wire_result.py tests/test_frozen_child.py tests/test_frozen_dispatch.py tests/test_frozen_replay.py -q`; require all passing.
- [ ] **Step 5: Commit** `feat: execute pinned model contexts through the frozen planner`.

### Task 5: Paper integration, refusal boundaries and release compatibility

**Files:**
- Modify `algua/registry/frozen_runtime.py`, `algua/registry/intake.py`, and `algua/cli/paper_cmd.py` at the existing frozen tenant/target construction seams.
- Modify `tests/_frozen_paper_world.py` to support an optional `model_handle: ModelHandle | None = None` argument on `build_world`; its default behavior and `World` API stay unchanged.
- Create `tests/test_frozen_model_paper.py`; extend existing frozen paper/forward evidence tests.
- Modify `docs/agent/model-artifacts.md` and `docs/architecture.md` to document the delivered scope and explicit acceptance limits.

**Interfaces:**
- Preserve existing paper CLI options, `prepare_and_verify_frozen`, `resolve_paper_tenant`, and invocation/evidence APIs. Route from the verified manifest profile, not an agent-supplied enable flag.
- Use the existing `World.trade_tick()`, `World.orders(name)`, `World.ticks(name)`, `World.sent` and `World.bundle_root` to exercise the real child/CLI path with a recording broker and disposable registry.
- Preserve all existing live and working-tree model refusals. No new raw stage transition, certificate kind or schema migration belongs to this task.

Production enablement depends on a reviewed authority-denying strategy execution boundary; current `run_contained` alone is insufficient. This plan does not invent or certify that separate security implementation. Until that boundary is available and assessed for the actual launch seam, retain `frozen_content_unsupported` for authoritative model-paper execution. Test trusted fixture execution through existing injected test seams only; expose no production bypass switch or environment variable. This is an explicit deployment prerequisite, not a passed acceptance item.

- [ ] **Step 1: Add tests** `test_model_paper_tick_uses_bundle_and_exact_snapshot`, `test_model_corruption_produces_no_tenant_orders`, `test_missing_isolation_keeps_authoritative_admission_closed`, `test_restarted_model_tick_preserves_existing_order_idempotency`, and `test_model_paper_does_not_enable_live`. Broker assertions use the existing world, for example:

```python
assert world.orders(TENANT) == []  # after a model verification refusal
assert not any(row['lane'] == 'live' for row in world.ticks(TENANT))
assert world.deployment().manifest_digest == original_manifest_digest
```

Use normal successful fixture ticks separately from refusal tests. Verify repeated identical-session dispatch does not create a second order and that model invocation/tick rows retain the exact deployment and bars snapshot. Synthetic fixture gate seeds must never be copied into the authoritative registry.

- [ ] **Step 2: Run** `uv run pytest tests/test_frozen_model_paper.py -q`; establish intended failures.
- [ ] **Step 3: Implement** profile routing, model-aware target metadata, refusal behavior and documentation. Use existing application release prepare/verify/recovery seams; run their applicable fixture tests without installing or activating a service. Carve CLI glue into an appropriate helper rather than growing pinned `paper_cmd.py`.
- [ ] **Step 4: Run the relevant integration regressions:**

```sh
uv run pytest tests/test_frozen_model_paper.py tests/test_frozen_paper_cli.py tests/test_frozen_paper_isolation.py tests/test_frozen_promotion.py tests/test_forward_evidence_frozen.py tests/test_lane_parity.py tests/test_module_size_ratchet.py tests/test_repo_hygiene.py -q
uv run pytest tests/test_release_paper.py tests/test_build_paper_release.py -q
uv run ruff check algua tests
uv run mypy algua
uv run lint-imports
```

Require all selected tests/type/lint checks passing and import-linter reporting zero broken contracts. The release fixture commands above verify the existing wrapper/build path without performing deployment. Do not claim an omitted test passed. Since this changes protocol, identity and multiple execution seams, run `uv run pytest -q` once on the integrated first-delivery branch before declaring it ready for protected review; do not repeat it after every task.

- [ ] **Step 5: Commit** `feat: integrate verified model artifacts with frozen paper mechanics`.

## Completion and next delivery

Publish a concise implementation result: exact commits, which identity/version/parity/failure tests actually passed, compatibility results, and whether real scheduled paper execution occurred. Local fixtures and successful release verification do not satisfy five elapsed sessions or economic qualification.

Only perform actual paper verification after an eligible artifact, paper account and reviewed isolation are available under the existing CLI permissions. Do not fetch credentials, activate timers, relax gates or change the authoritative registry merely to complete this plan. A genuine economic rejection remains a valid outcome.

Next, plan the qualification-policy change against design §6 and the existing Story 2.1 conflict, then the frozen-live authorization/handoff and enforced risk policy. Those plans must make the exact economic criteria and account intervention behavior explicit before changing protected runtime code.

## Plan self-review

- Spec §4 items 1/4: shared scorer, context identity and model-only profile in Tasks 2–4.
- Spec §4 items 2/3: portable verified assets, explicit profiles and two-phase binding in Tasks 1–4.
- Spec §4 items 5/6: supervisor authority and conservative isolation/admission boundaries in Task 5.
- All first-delivery acceptance items map to the named tests; actual scheduled/account acceptance remains explicitly conditional, not inferred from fixture success.
- The broader qualification, news, live and risk deliveries are intentionally outside this plan. No existing gate or operational permission is silently superseded.
