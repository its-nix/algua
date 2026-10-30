# Observed-versus-target report and ADR — three-harness redesign

**Date:** 2026-10-30. **Owner:** Lior Nisimov. **Scope:** plan Task 0.
**Companions:** [design](../superpowers/specs/2026-10-30-algua-three-harness-design.md),
[plan](../superpowers/plans/2026-10-30-algua-three-harness-implementation.md),
[readiness report](implementation-readiness-report-2026-10-30-three-harness.md).

This records one read-only snapshot. It is not evidence of health, and it changes no control.

## 1. ADR: control-plane split

**Context.** The owner chose to separate who develops Algua, who operates its research and what
computes its results. Delegated work was instructed through Todoist, and scheduling and merge routes
grew before that split existed.

**Decision.** Lior approved the direction by mandate on 2026-10-30: Hermes develops the machine,
OpenCode operates research, and Algua's deterministic code owns data, simulation, promotion,
portfolio, risk, execution and ledgers. Hermes Kanban owns delegated engineering work, GitHub owns
code and evidence, and Todoist holds only Lior's human commitments.

**Consequences.** This is direction, not new control or new permission. Lior's approval remains
required for all merges, deployments, credentials, destructive or external-sharing actions and
protected authority changes. Auto-merge and paper CI/CD are TARGET BLOCKED. The role change in
`its-nix/os` needs a separate PR there; this repository's docs cannot make it.

**Rejected.** A second task system or research database, and enabling automation from documentation
alone.

## 2. Source provenance

The source bundle was proposed documentation. Publishing it does not assert that it was merged
before now. The owner retains the original native-input ZIP, whose checksum is not recorded here.

| Source file | SHA-256 |
|---|---|
| `README.md` | `174a385464701da5e6bf93d1631bd1a02a8ddcde2c369b88ab4e05c1ec155f78` |
| `01_PRD_CONSOLIDATION.md` | `981919f5f753db298c256217f87cfba3f5e91e19ada070cc2ac01d2882ed7ed9` |
| `02_ARCHITECTURE_DESIGN.md` | `fa179ebcdcf124ff4fd805cca68b15491ddbc179c69bc20421ddcf83c005c182` |
| `03_IMPLEMENTATION_PLAN.md` | `66f2c2f2076086146a8cbd9053bbd662a1881485da4f9dfc514aab6403d2df52` |
| `04_LNX_HANDOFF.md` | `d6da43dbf313e130dde3f4df08ceef5795128efd341823a9ba07221af602748b` |

`01` is reconciled into the [PRD](../PRD.md). `02` and `03` are published in full with a provenance
and precedence overlay. Read-only `its-nix/os` source: main
`583f065c04baadce81f30a925fd4b8feb34c4e67`.

## 3. Observation method

The coordinator ran these read-only on 2026-10-30. Repository findings marked "tree" were read from
this worktree at the same base.

- `git fetch origin`
- `gh api repos/its-nix/algua/branches/main/protection`
- `gh pr list --state open`
- `gh api` reads of `profiles/algua/ROLE.md` and `docs/ARCHITECTURE.md` in `its-nix/os`
- `systemctl --user show` for the units below

These observation commands changed no unit, timer, protection setting or remote branch. Subsequent
publication of this documentation branch and PR is separate from this read-only snapshot; neither
publication nor passing CI authorizes merge or deployment.

## 4. Observed baselines

| Item | Observed |
|---|---|
| `HEAD` and `origin/main` | `db6860000f87a6cc98469e0e4901fa9c10c0d277` |
| Main checkout, untouched | `a3c71fa6302eb7491510c0c14beee998156a5e1a` |
| `its-nix/os` main | `583f065c04baadce81f30a925fd4b8feb34c4e67` |
| os `profiles/algua/ROLE.md` | Requires Lior's approval for all merges, deployments, credentials, destructive actions and external sharing. Queue routing is already correct; explicit three-harness ownership is missing. |
| os `docs/ARCHITECTURE.md` | A profile is same-UID, not an OS sandbox. |

**Branch protection on `main`:**

| Setting | Observed |
|---|---|
| `required_status_checks` | null |
| `require_code_owner_reviews` | true |
| `required_approving_review_count` | 0 |
| `enforce_admins` | false |
| `dismiss_stale_reviews` | false |
| `require_last_push_approval` | false |

These settings cannot enforce automatic exact-head or independent review. No protection edit or
auto-merge was made.

**Open PRs, all MERGEABLE at observation:**

| PR | Head | Relevance |
|---|---|---|
| [#707](https://github.com/its-nix/algua/pull/707) | `1569fb96e023ac8dbc4100d3c461c705d9374af8` | Acceptance dashboard, input to Task 10 |
| [#712](https://github.com/its-nix/algua/pull/712) | `8818d32e28515d0e279d4ab3af26dbac8217656c` | Planner safety fix, dependency for Tasks 2 to 4 |
| [#713](https://github.com/its-nix/algua/pull/713) | `7f4baa53826697542afddcb49620a1922798cae2` | BMAD sync; owns `epics.md` and sprint docs |
| [#694](https://github.com/its-nix/algua/pull/694) | `0c3b34a710b0a4e0074d048fd2642fc834e88c27` | Open dependency; content not inspected here |
| [#670](https://github.com/its-nix/algua/pull/670) | `40855794f479bd67b45f7daa9707657c77423590` | Open dependency; content not inspected here |

**Schedulers.** All five services read inactive/dead at observation, which is not health acceptance
and does not verify any completed cycle. Unit fragments are at
`/home/liornisimov/.config/systemd/user/algua-*.service`, with working directory
`/home/liornisimov/Projects/algua`.

| Unit | Entry | Timer observed |
|---|---|---|
| `algua-research` | `.opencode/scripts/run-research-loop.sh` | every 6h |
| `algua-leap` | `.opencode/scripts/leap.sh` | every 2h |
| `algua-forage` | `.opencode/scripts/forage.sh` | daily |
| `algua-paper` | `.venv/bin/algua operator run --job paper -- algua paper run-all --refresh` | every 20min |
| `algua-mergeback-drain` | `.opencode/scripts/drain-mergeback-queue.sh` | every 30min |

## 5. Criteria

PASS means the evidence named here supports the criterion. FAIL means this tree or snapshot shows it
unmet. UNKNOWN means it was not exercised or inspected. PENDING means the coordinator has yet to
supply the result.

**Machine acceptance**

| Criterion | Status | Evidence |
|---|---|---|
| 10 unattended OpenCode-led research cycles | UNKNOWN | Not exercised |
| ≥100 honest recorded real-data attempts across families | UNKNOWN | Not exercised |
| Rule, pinned-ML and combined-modality interfaces | FAIL | `algua/strategies/base.py:150-157` keeps modalities mutually exclusive; no `AsOfContext` in the tree |
| Data tier on every run and UI result | FAIL | No `data_tier` or `pilot_real_proxy` in `algua/` or `web/` |
| Reproducible from pinned identities | UNKNOWN | Provenance columns exist; no rerun exercised on the pilot |
| Research workers hold no capital or protected authority | UNKNOWN | Runtime seam exists; not tested as acceptance |
| Strategy code contained in privileged runs | FAIL | `AGENTS.md` records the strategy sandbox as deferred; the frozen child is process separation, not an authority sandbox |
| Independent review and exact-head CI enforced | FAIL | Protection settings above |
| Verified paper release, smoke and rollback | FAIL | No `deploy/scripts/`; no release entry in the tree |
| Multi-strategy target aggregation | FAIL | No allocator in the tree |
| Leaderboard and drilldowns | FAIL | Lifecycle default and four tabs in `web/frontend/src/App.tsx` |
| Injected recoverable worker failure | UNKNOWN | Not exercised |
| Replay and scheduled paper independently labeled | UNKNOWN | Not exercised |
| One research initiator, no duplicate writers | FAIL | Research, leap and forage have separate timers; the merge-back route below is a second writer to main |

**Investment acceptance and walls**

| Criterion | Status | Evidence |
|---|---|---|
| Human-signed LIVE ceremony unchanged | PASS | This change touches no code; guides retain the rule |
| Frozen deployments refused at go-live and in the live lane | PASS | `frozen_live_unsupported` in `algua/registry/transitions.py` and `algua/registry/frozen_tenant_errors.py`, read not run |
| Raw edges into `candidate` and `forward_tested` refused | PASS | `raw_edge_refused` in `algua/registry/raw_edge.py`, read not run |
| Go-live refuses relaxed qualification | FAIL | See the discrepancy below |
| 10% pause enforced | FAIL | Unimplemented, Story 2.6; `book_max_drawdown` default is 0.15 |
| Capital envelope enforced | FAIL | Unimplemented, Story 2.5; `book_max_gross` default is 2.0 |
| Full PIT universe and delistings | FAIL | The planned pilot is a proxy; no purchase authorized |
| Elapsed forward evidence | UNKNOWN | Not inspected here |
| Immutable signer anchor | UNKNOWN | Deployed filesystem ownership not inspected |

**This change**

| Criterion | Status | Evidence |
|---|---|---|
| Doc-contract tests | PASS | 34 passed; 19 copy-mutation cases; original red run 17 failed / 26 passed |
| Full root gate, Python 3.12.3 | PASS | 6,325 passed, 5 existing skipped; Ruff/mypy/import boundaries clean; details below |
| Full root gate, default Python 3.12.12 | FAIL | 1 unchanged-baseline IPv6 canonicalization failure; details below |
| Installed Codex independent review | PENDING | Downstream QA card; not run by the implementer |
| Remote CI at exact head | PENDING | Coordinator to populate |
| Web gates | N/A | No web code touched |

**Story 2.1 implementation gap.** The existing normative contract requires unrelaxed live
qualification; this tree shows only part of that outcome. `raw_edge_refused` is present, but
`relaxations_json` and
`live_qualification_relaxed` have no matches under `algua/`, and
[sprint status](sprint-status.yaml) lists the story as `ready-for-dev`. The relaxation decision was
made on 2026-10-04 and is not an open question; the enforcement is what is missing here. The open
dependency PRs #694 and #670 are dependency-version updates, not evidence that this control shipped.

## 6. Settled owner decisions

Both were decided on 2026-10-04 in [#624](https://github.com/Lior-Nis/algua/issues/624) and are not
reopened here.

- **Drawdown:** [Story 2.6](stories/2-6-pause-live-trading-at-ten-percent-drawdown.md) owns the 10%
  pause, and [Story 2.5](stories/2-5-enforce-the-experimental-capital-envelope.md) owns the envelope.
  Both are unimplemented. Activating 2.5 still needs Lior's USD ceiling and instrument list.
- **Signed relaxations:** they remain available for exploration and can never authorize go-live.
  [Story 2.1](stories/2-1-refuse-live-qualification-on-relaxed-gates.md) owns enforcement.

Stories 1.3b, 1.3c and 1.3d have shipped per [architecture](../architecture.md), so frozen paper
execution exists. Live hand-off does not, and go-live still refuses frozen deployments.

## 7. Blockers

1. **The direct-main merge-back route is unresolved.** `paper merge-back` pushes to
   `refs/heads/main` through `algua/operator/gitops.py`, and the drain timer exists. Documentation
   does not disable it. It stays inside its diff allowlist, but it conflicts with Lior's approval for
   all merges. This is a migration and containment blocker, not a silent approval. Lior needs to
   decide its status before Task 7.
2. **Strategy containment** blocks any widening of strategy automation (Task 4). A file allowlist
   does not make Python safe, and a same-UID profile is not a sandbox.
3. **Branch protection** cannot enforce exact-head or independent review.
4. **The `its-nix/os` role** needs a separate PR for explicit three-harness ownership. No os file was
   written here.
5. **Open PR overlap:** rebase after #712, #713 and #707 where their areas meet.

## 8. Cross-links and hotspots

| Plan task | Existing owner | Note |
|---|---|---|
| Task 4 | [Story 1.3](stories/1-3-materialize-and-execute-frozen-planner-artifacts.md) frozen scope | Process separation is not an authority sandbox |
| Task 7 | [Story 2.8](stories/2-8-validate-releases-in-paper-before-live.md) | No duplicate release story |
| Task 8 | [spec-strategy-board](stories/spec-strategy-board.md) | [Supersession record](../vision-reconciliation.md#strategy-leaderboard-supersession-2026-10-30) |
| Task 10 | [Story 2.10](stories/2-10-run-the-72-hour-unattended-acceptance.md), #707 | No duplicate acceptance status |
| Tasks 2 to 4 | #712 | Planner safety dependency |

**Hotspot:** `docs/development/epics.md` and `docs/development/sprint-status.yaml` belong to #713 and
were not edited. Their statuses, including Story 2.1 and the Epic 2 sequence, need reconciling there.

**CI follow-up ownership:** `t_ab3d8099` owns CI strengthening in a separate worktree. Existing
`.github/workflows/ci.yml` already has root `gate` and `web` jobs; workflow tests are distinct from
GitHub required-check enforcement. Task 0 changes neither. The owner's follow-up blanket approval
is intent to continue scoped delivery, not permission to remove CODEOWNERS, expand the diff
allowlist or bypass current protected-path, live, capital, merge or deployment controls.

## 9. Executed local evidence

Both runs used the unchanged committed lock and the identical tests. Five pre-existing skips and
171 warnings were reported in each full run; no test, skip, threshold or policy was weakened.

| Command | Interpreter | Exit / actual result |
|---|---|---|
| `uv run --locked pytest tests/test_three_harness_docs.py tests/test_repo_hygiene.py tests/test_codeowners_parity.py tests/test_research_methodology_doc.py -q` | 3.12.12 | 0; 48 passed in 1.66s |
| `uv run --locked pytest -q` | 3.12.12 | 1; 1 failed, 6,324 passed, 5 skipped in 666.92s |
| `uv run --locked ruff check .` | 3.12.12 | 0; clean |
| `uv run --locked mypy algua scripts` | 3.12.12 | 0; 360 source files |
| `uv run --locked lint-imports` | 3.12.12 | 0; 29 kept, 0 broken |
| Same focused subset with `--python /usr/bin/python3.12` | 3.12.3 | 0; 48 passed in 1.77s |
| `uv run --python /usr/bin/python3.12 --locked pytest -q` | 3.12.3 | 0; 6,325 passed, 5 skipped in 692.77s |
| Same Ruff, mypy and import-linter commands with `--python /usr/bin/python3.12` | 3.12.3 | All 0; clean, 360 source files, 29 kept / 0 broken |

The 3.12.3 commands used `UV_PROJECT_ENVIRONMENT` pointing to a separate scratch venv, never a
production path. Neither `.python-version` nor `uv.lock` nor the default project interpreter was
changed. This comparison does not erase the default failure or establish remote acceptance.

**Important, existing baseline compatibility failure.**
`tests/test_planner_environment_lock.py:199`, case `ipv6-mapped-ipv4`, expects
`https://[::ffff:c000:20a]/x.whl`; `algua/registry/planner_environment_lock.py:103` delegates its
ownership identity to `IPv6Address.compressed`. Actual stdlib probes return `::ffff:192.0.2.10`
on 3.12.12 and `::ffff:c000:20a` on 3.12.3. Neither affected file differs from base. An exact
`git archive db6860000f87a6cc98469e0e4901fa9c10c0d277` scratch copy reproduced 1 failed / 161 passed
for that test module on 3.12.12; the same module passes all 162 tests on 3.12.3. The single failing
case was also rerun independently against the base. Protected repair/admission is routed to Lead
card `t_51c03411`, not implemented or suppressed here. No runtime downgrade is proposed.

**Structural checks:** all 30 PRD headings remain in original order and unrequested sections are
byte-identical; the PRD diff retains all original text. Both frozen UI-intent blocks are
byte-identical, with supersession notices outside them. All supplied design/plan section and task
headings and unchecked-step counts are retained. All 135 local Markdown destinations in the
changed docs resolve; URL fragments were not validated. Diff scope is docs/guides and one doc test.

Actual command logs and a checksum manifest accompany the Task 0 Kanban handoff. The PR/head and
remote check-run identities are recorded separately at publication. Independent Codex review is
PENDING on `t_febd9af7`; this report is implementer verification, not independent self-review.
