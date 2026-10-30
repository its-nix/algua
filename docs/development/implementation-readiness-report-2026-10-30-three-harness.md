# Implementation readiness — three-harness redesign

**Date:** 2026-10-30. **Base:** `db6860000f87a6cc98469e0e4901fa9c10c0d277`.
**Inputs:** [design](../superpowers/specs/2026-10-30-algua-three-harness-design.md)
(`2026-10-30-algua-three-harness-design.md`),
[plan](../superpowers/plans/2026-10-30-algua-three-harness-implementation.md)
(`2026-10-30-algua-three-harness-implementation.md`),
[observed-target report](observed-target-report-2026-10-30-three-harness.md)
(`observed-target-report-2026-10-30-three-harness.md`).

## Verdict

**Documentation preparation: READY for independent review**, with the interpreter-specific gate
limitation recorded below. **Implementation: BLOCKED for every slice.** This report admits no story. Each slice
needs its own contract, readiness rerun and approval under
[story delivery](../agent/story-delivery.md). All later protected readiness is UNKNOWN or BLOCKED.

Lior's approval remains required for every merge and deployment. Auto-merge and paper CI/CD are
TARGET BLOCKED. Independent review by installed Codex belongs to the dedicated downstream QA card, and
the implementer did not run it.

| Slice | Readiness | Blocked by |
|---|---|---|
| Task 0 docs | READY for local preparatory review | Independent review and remote CI pending; default Python 3.12.12 baseline failure below |
| Task 1 data tier | BLOCKED | No contract; `data_tier` storage decision |
| Task 2 multimodal contract | BLOCKED | No contract; #712; protected `algua/strategies/base.py` |
| Task 3 allocator | BLOCKED | No contract; #712; Story 2.5 envelope interaction |
| Task 4 containment | BLOCKED | No threat-model contract; protected-path approval; UNKNOWN whether a hard boundary fits the frozen child |
| Task 5 research factory | BLOCKED | Task 1; Task 4; approved schedule cutover |
| Task 6 cumulative learning | BLOCKED | Task 5 |
| Task 7 release and merge | BLOCKED | Task 4; merge-back decision; branch protection; Story 2.8 boundary |
| Task 8 leaderboard | BLOCKED | Admitted UI contract; Task 1 for tier display; `strategy-board/v1` stands |
| Task 9 incident handoff | BLOCKED | Separate `its-nix/os` PR |
| Task 10 machine acceptance | BLOCKED | All of the above; #707; Story 2.10 |

Machine acceptance targets stay open: 10 unattended cycles are UNKNOWN, and ≥100 honest real-data
attempts are UNKNOWN.

## Normative sources

These own their schemas. This report inventories and does not restate them.

- [Bar schema](../contracts/bar-schema.md), FROZEN.
- [Strategy-board contract](specs/spec-strategy-board/strategy-board-contract.md).
- [Frozen execution contract](specs/spec-story-1-3c-frozen-paper-execution/frozen-execution-contract.md)
  and [Story 1.3d SPEC](specs/spec-story-1-3d-frozen-evidence-and-qualification/SPEC.md).
- [Unrelaxed live qualification SPEC](specs/spec-story-2-1-unrelaxed-live-qualification/SPEC.md) and
  [its contract](specs/spec-story-2-1-unrelaxed-live-qualification/live-qualification-contract.md).
- Stories [2.3](stories/2-3-bind-live-authorization-to-the-frozen-deployment.md),
  [2.4](stories/2-4-hand-off-and-execute-frozen-deployments-live.md),
  [2.5](stories/2-5-enforce-the-experimental-capital-envelope.md),
  [2.6](stories/2-6-pause-live-trading-at-ten-percent-drawdown.md),
  [2.8](stories/2-8-validate-releases-in-paper-before-live.md) and
  [2.10](stories/2-10-run-the-72-hour-unattended-acceptance.md).

## Field-level inventory

"Target" fields are proposed in the plan and do not exist in this tree.

### Data tier and manifest

| Field | Type, nulls | Owner | State |
|---|---|---|---|
| `SnapshotMetadata.dataset`, `kind` | `Dataset`, `Kind` enums, non-null | `algua/data/models.py` | Current |
| `provider`, `start`, `end`, `as_of`, `source` | `str`, non-null | same | Current |
| `symbols` | `tuple[str, ...]`, non-null | same | Current |
| `timeframe`, `adjustment`, `universe` | `str`, nullable | same | Current |
| `source_metadata` | `dict[str, str]`, nullable | same | Current; candidate home for tier metadata, undecided |
| `SnapshotRecord.snapshot_id`, `content_hash`, `created_at` | `str`, non-null | same | Current |
| `row_count` | `int`, nullable | same | Current |
| `runs.snapshot_id`, `data_source`, `universe_name` | `TEXT`, nullable | `algua/registry/db/runs.py` | Current |
| `data_tier` | Target enum `pilot_real_proxy`, `verified_pit`, `synthetic_fixture` | `algua/contracts/data_tier.py` if needed | Target |
| `PilotDataManifest` | Target `snapshot_id`, `start`, `end`, `provider`, `universe_method`, `limitations` | Existing metadata, no second store | Target |

### Context modalities, model identity and score

| Field | Type, nulls | Owner | State |
|---|---|---|---|
| `StrategyConfig.needs_fundamentals`, `needs_news`, `needs_model` | `bool`, default false, at most one true | `algua/strategies/base.py`, protected | Current |
| `model_ref` | `ModelRef`, required iff `needs_model` | same | Current |
| `ModelRef.name`, `version`, `digest`, `training_as_of`, `provenance_digest` | `str`, `int`, `str`, `str`, `str`, non-null | `algua/contracts/model_types.py` | Current |
| `ModelHandle.version`, `artifact_bytes` | `ModelVersion`, `bytes` | same | Current |
| `runs.components` | JSON list, non-null, `'[]'` when empty | `algua/registry/db/runs.py` | Current; already expresses several models |
| `AsOfContext`, `AsOfView` | Target `decision_ts`, `universe`, `features`, `models` and `kind`, `knowable_at`, `snapshot_id`, `frame` | `algua/contracts/strategy_context.py` | Target |
| `score(context)` output | Target finite, duplicate-free `symbol -> score` | Target contract | Target |

### Allocator, budgets, constraints and empty cash

| Field | Type, nulls | Owner | State |
|---|---|---|---|
| `allocate_locked` and `allocate_in_lane` inputs | `strategy_id`, `capital: float`, `actor` | `algua/registry/allocations.py` | Current; a capital slice, not a risk budget |
| `ExecutionContract.max_gross_exposure`, `max_weight_per_symbol`, `allow_short` | `float`, `float`, `bool`, defaults 1.0, 1.0, false | `algua/contracts/types.py` | Current |
| `book_max_gross`, `book_max_net` | `float`, defaults 2.0, 1.0 | `algua/config/settings.py` | Current; not the PRD §21 envelope |
| `OrderIntent` | `symbol`, `side`, `target_weight`, `decision_ts`, non-null | `algua/contracts/types.py` | Current |
| Empty target | `build_intents` emits zero targets for dropped holdings | `algua/live/planner_decision.py` | Current per strategy; no account-level all-cash outcome |
| `budgets`, `PortfolioConstraints` | Target `Mapping[str, float]` and `max_gross`, `max_weight_per_symbol`, nullable `max_turnover` | `algua/portfolio/allocator.py` | Target |

### Claim, run and failure lineage

| Field | Type, nulls | Owner | State |
|---|---|---|---|
| `ideas.claimed_by`, `claim_token` | `TEXT`, nullable | `algua/registry/ideas.py` | Current |
| `idea_attempts.idea_id`, `run_stamp`, `claim_token`, `claimed_at` | non-null | `algua/registry/db/ideas.py` | Current, append-only |
| `idea_attempts.outcome`, `reason`, `evidence_ref`, `strategy_name`, `outcome_at` | `TEXT`, nullable | same | Current; written once by a trusted driver |
| `AttemptOutcome` | Includes `run_error`, `abandoned`, `integrity_fail` | `algua/contracts/idea.py` | Current; no `data_unavailable` or `infrastructure_error` split |
| `runs.kind` | `backtest`, `walk_forward`, `sweep`, `sweep_trial`, `gate` | `algua/registry/db/runs.py` | Current |
| `runs.strategy_id` | `INTEGER`, nullable on purpose for pre-registration evidence | same | Current |
| `runs.derived_from` | JSON list, non-null | same | Current |
| `research_cycle_id`, `attempts[]`, cost and time bounds | Target | Existing ledger, no second database | Target |

### Strategy board, current contract

Schema `strategy-board/v1` from `algua/registry/strategy_board.py`, unchanged by this work.

| Field | Type, nulls |
|---|---|
| `schema_version` | `"strategy-board/v1"`, non-null |
| `count` | `int`, equals `rows.length` |
| `rows` | array, lifecycle order, then case-insensitive name, then `strategy_id` |
| `strategy_id` | `int`, non-null |
| `name`, `stage` | `str`, non-null |
| `family` | `str`, nullable |
| `latest_gate` | object, nullable, selected by `created_at DESC, id DESC` for the identity |
| `latest_gate.run_id` | `int`, non-null within the object |
| `latest_gate.created_at` | offset-aware ISO `str`; otherwise the whole `latest_gate` is null |
| `latest_gate.passed` | `bool`, nullable |
| `sharpe_oos`, `total_return_oos`, `max_drawdown_oos` | `float`, nullable |
| `n_obs_oos` | `int`, nullable; a negative value becomes null |
| `mean_window_sharpe`, `min_window_sharpe`, `pct_positive_windows` | `float`, nullable |

Target additions, only under an admitted UI contract: `data_tier`, `freshness`. Default order changes
in the UI only. The
[supersession record](../vision-reconciliation.md#strategy-leaderboard-supersession-2026-10-30) holds
the limits.

### Release head, review, check, digest and rollback

| Field | Type, nulls | Owner | State |
|---|---|---|---|
| `MergeBackRecord.branch_tip` | `str`, non-null | `algua/operator/journal.py` | Current |
| `base_sha`, `merge_sha`, `attempt_token`, `revert_sha` | `str`, nullable | same | Current |
| `mergeback_evidence.strategy_id`, `branch_tip`, `recipe_hash`, `search_trials_watermark`, `status` | non-null, unique on strategy and tip | `algua/registry/db/mergeback.py` | Current |
| `deployment_artifacts.manifest_digest`, `environment_digest`, `source_kind`, `source_ref` | `TEXT`, non-null, immutable | `algua/registry/db/deployment.py` | Current; strategy artifact, not supervisor release |
| `independent_review_at_head`, `all_required_ci_green_at_head`, `strategy_isolation_passed` | Target booleans | Task 7 | Target |
| Release digest, provenance, rollback state | Target | Task 7, Story 2.8 boundary | Target |

### Human-signed LIVE and frozen refusal

| Field | Type, nulls | Owner | State |
|---|---|---|---|
| `live_challenges.nonce`, `strategy_id`, `code_hash`, `config_hash`, `issued_at`, `expires_at` | non-null | `algua/registry/db/authz.py` | Current |
| `live_challenges.dependency_hash`, `consumed_at` | `TEXT`, nullable | same | Current |
| `approvals.dependency_hash` | `TEXT`, nullable; NULL never satisfies the gate | `algua/registry/db/core.py` | Current |
| `approvals.revoked_at` | `TEXT`, nullable | same | Current |
| `LiveAuthorization` | `strategy_id`, `code_hash`, `config_hash`, nullable `dependency_hash`, `principal`, `authorized_at` | `algua/contracts/types.py` | Current |
| `frozen_live_unsupported` | Stable refusal code | `algua/registry/frozen_tenant_errors.py` | Current |
| `raw_edge_refused` | Stable refusal code | `algua/registry/raw_edge.py` | Current |
| `relaxations_json`, `live_qualification_relaxed` | Story 2.1 contract | Absent from this tree | See the [observed-target report](observed-target-report-2026-10-30-three-harness.md) |

## Entry-point inventory

Every later contract must extend this list before it adds a guard.

| Surface | CLI and API paths | Direct and runtime paths | Reruns | Alternate writers and bypass guards |
|---|---|---|---|---|
| Snapshot and tier | `data ingest`, `ingest-bars`, `refresh-bars`, `import-bars`, `import-universe`, `import-delistings` | `SnapshotManifest.append_if_absent` is the only manifest writer | `append_if_absent` returns the committed winner | `paper run-all --refresh` mints bars, so a tier must also cover operator refresh |
| Strategy evaluation | `backtest run`, `walk-forward`, `sweep`, `research promote` | `LoadedStrategy`, `algua/evaluation/`, `algua/live/planner_decision.py`, `algua/live/frozen_child.py` | Promote reruns, sweeps | Fast and canonical paths need parity; frozen tenants never import the checkout |
| Allocation | `live allocate`, paper intake | `allocate_locked`, `allocate_in_lane`, `deallocate`, `revoke_active_locked`, `transition_strategy` exit guards | Intake retries | Paper and live lanes must keep parity; `live allocate` authentication is Story 2.5 |
| Claims and attempts | `research idea claim`, `record-outcome`, `link` | `algua/registry/idea_attempts.py`, research and leap drivers, merge-back drainer | Fencing token | Agents never run these against authority |
| Run ledger | `runs list`, `runs board`, `/api/runs`, `/api/strategy-board` | `algua/registry/store/runs.py` | Append per evaluation | Display surfaces must never feed promotion |
| Merge and release | `paper merge-back`, drain timer, `gh` under Lior's approval | `algua/operator/mergeback.py`, `gitops.py` `push_cas`, `push_revert`, `diff_policy.py` | Journal keyed on branch tip | **`paper merge-back` writes `refs/heads/main` directly: unresolved blocker** |
| LIVE | `registry transition --to live --actor human`, `registry approve`, `registry enroll-approver` | `algua/registry/transitions.py`, `live_gate.py`, `approvals.py`, `require_tick_deployment` | Single-use challenge | Raw `registry transition` refuses gated edges; bare `--actor human` unlocks nothing; frozen deployments refused |

## Execution evidence

Per story delivery, readiness runs external tools rather than assuming them.

| Tool | Result |
|---|---|
| Claude Code 2.1.314 | Authenticated; scoped invocation worked with empty setting sources, strict MCP, no Chrome and `dontAsk`, with no bypass flags. An initial default invocation timed out without output. Claude authored the docs and tests; its final invocation then hit the account's five-hour quota. Coordinator finished mechanical test-pattern/lint and evidence corrections; no permission or quota bypass. |
| Codex CLI | Installed; help and login status succeed. Independent review not run by the implementer. |
| uv 0.9.26, CPython 3.12.12, pytest 9.0.3 | Project interpreter works in an isolated venv. |
| Doc-contract tests | PASS: 34 passed; 19 copy-mutation cases collected and exercised; original red run 17 failed / 26 passed before docs reconciliation |
| Focused docs/hygiene subset | PASS: 48 passed on both Python 3.12.12 and 3.12.3 |
| Full root gate, Python 3.12.3 | PASS: 6,325 passed, 5 existing skipped; Ruff clean; mypy clean (360 source files); 29 import contracts kept, 0 broken |
| Full root gate, default Python 3.12.12 | FAIL: 1 unchanged-baseline IPv6 canonicalization test, 6,324 passed, 5 existing skipped; static gates pass |
| Independent review | PENDING |
| Remote CI | PENDING |
| Web gates | N/A, no web code touched |

The same locked dependencies and unmodified tests were exercised on both interpreters. The
Python 3.12.3 comparison used a separate scratch environment and explicit
`uv run --python /usr/bin/python3.12 --locked ...`; `.python-version`, `uv.lock`, the project's
default environment and the running system were not changed. It is diagnostic evidence, not a
production downgrade recommendation or a claim that default/remote CI is green. The
[observed-target report](observed-target-report-2026-10-30-three-harness.md#9-executed-local-evidence)
contains the failure, reproduction and follow-up.

## Findings

1. **Major:** the direct-main merge-back route conflicts with Lior's approval for all merges. Task 7
   cannot be scoped until Lior decides its status.
2. **Major:** Story 2.1's required relaxation-set enforcement is absent from this tree; the existing
   normative contract is not proof of implementation. Keep that work with Story 2.1.
3. **Minor:** `sprint-status.yaml` and `epics.md` are stale for Epic 2. #713 owns them, so they are
   unchanged here.
4. **Minor:** the docstring in `algua/registry/strategy_board.py` stays old by design until a UI
   contract lands.
