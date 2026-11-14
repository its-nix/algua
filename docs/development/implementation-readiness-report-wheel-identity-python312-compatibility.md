# Implementation-readiness evidence: wheel identity / Python 3.12

**Outcome: readiness evidence assembled; implementation is NOT authorized.** This is an evidence report for a proposed compatibility follow-up, not a product repair, acceptance of the proposed SPEC as normative, or approval to implement.

## Tested identity and evidence boundary

The fresh baseline matrix was executed at exact repository head `db6860000f87a6cc98469e0e4901fa9c10c0d277` (PR #711 merge), not at this report's later assembled documentation head. The two proposed SPEC files were committed separately at `644ac24569fc940e2ba41d4aad32226af5bfb2e4`; the proposed story at `5fee55b31f8b73c7b64ada49b240d3586dc80422`. Those commits and their upstream-reported checks are not substituted for the baseline execution below. The baseline worker retained 25 command logs with verified exits and hashes in `wheel-identity-baseline-evidence.zip` (40 files; 42,344 bytes; SHA-256 `15d2564e9f9e27d2dbf815eebf4b4ecdd2588b8a3f8eaa08b36976a47f6dfa9b`); its report is `.task-evidence/BASELINE-REPORT.md` in task `t_d5dd48c7`'s worktree/attachment.

**Important limitation:** these results are fresh at the canonical product baseline, but they are not final assembled-docs-head verification. This report and the story/SPEC are being assembled after that baseline run. The parent assembly lane must run and record both complete matrices at its immutable final docs head, and rerun after any amendments. Remote CI was not run or accepted by this evidence task.

### Final assembled-head evidence protocol

The assembly lane (`t_4532ae9d`) commits the four proposed documents before running its final matrix. To avoid a self-referential commit hash or changing repository dirty inputs during determinism tests, the exact tested commit, command logs, exits, package inventories and hashes are recorded in the separate downloadable `wheel-identity-assembled-head-evidence.zip` task artifact and exact-head PR handoff. At this report's authoring time those runs are NOT RUN; the later artifact must be inspected for their actual PASS/FAIL results. No baseline result in this document is promoted to final-head evidence. Any later documentation amendment invalidates that final-head claim until the matrix is refreshed. Independent QA and remote CI remain separate evidence.

Readiness provenance: adopted from completed report task `t_12228e6e`; assembly corrected cache-tag/SOABI labeling and added this evidence protocol and interpreter-selection assessment. Story/SPEC preserve their disclosed Claude Code draft provenance. No renewed authoring or quota bypass is claimed by mechanical assembly.

## Declared interpreter scope

At the tested baseline, `.python-version` contains `3.12`; `pyproject.toml` declares `requires-python = ">=3.12"`. Fresh execution covered only the two installed CPython patch builds below, on this host/Linux x86_64. It does not establish every interpreter admitted by `requires-python`, every Python 3.12 patch, platform, or architecture. No interpreter setting or metadata was changed.

Operational gate selection is not pinned to either tested patch: `algua/operator/gate_runner.py:49-53` invokes `uv run --frozen` without an explicit interpreter patch. A passing 3.12.3 run therefore does not prove that a gate selecting 3.12.12 succeeds. The metadata's broader `>=3.12` declaration is not an exercised compatibility matrix; environment construction separately requires the running minor to equal the committed `3.12` pin (`planner_environment.py:112-115`). Those are distinct existing constraints, not a reason to narrow metadata or pin backward here. Other admitted versions/platforms remain unverified; CI ownership stays with `t_ab3d8099`.

## Fresh baseline matrix (unchanged product and tests)

| Gate | CPython 3.12.3 | CPython 3.12.12 |
|---|---:|---:|
| Literal mapped-IPv6 regression `tests/test_planner_environment_lock.py::test_wheel_url_ownership_identity_is_rfc_canonical[ipv6-mapped-ipv4]` | PASS, 1 passed (exit 0) | FAIL, 1 failed (exit 1) |
| Unchanged `tests/test_planner_environment_lock.py` | PASS, 162 passed (exit 0) | FAIL, 1 failed / 161 passed (exit 1) |
| Full `pytest -q` | PASS, 6291 passed / 5 skipped / 171 warnings; 2407.99 s (exit 0) | FAIL, 1 failed / 6290 passed / 5 skipped / 171 warnings; 2000.08 s (exit 1) |
| `ruff check .` | PASS (exit 0) | PASS (exit 0) |
| `mypy algua scripts` | PASS, 360 source files (exit 0) | PASS, 360 source files (exit 0) |
| `lint-imports` | PASS, 29 kept / 0 broken (exit 0) | PASS, 29 kept / 0 broken (exit 0) |

The sole pytest failure on 3.12.12 is the unchanged test `tests/test_planner_environment_lock.py::test_wheel_url_ownership_identity_is_rfc_canonical[ipv6-mapped-ipv4]` (assertion at line 199). For input `https://[::FFFF:192.0.2.10]/x.whl`, expected identity is `https://[::ffff:c000:20a]/x.whl`; the current implementation at `algua/registry/planner_environment_lock.py:103` instead yields `https://[::ffff:192.0.2.10]/x.whl`. The stdlib `.compressed` rendering differs across these installed patch releases; `.exploded` also differs and is not a safe substitute. No test was edited, skipped, xfailed, weakened, or hidden. The runner's aggregate process exit is not a green verdict: each command's actual exit and log hash were verified separately.

### Commands and tools used

The baseline runner used separate locked environments `.venv-3123` and `.venv-31212`, with interpreter downloads disabled. For each exact interpreter `P` and environment `E`, the command sequence was:

```sh
UV_PROJECT_ENVIRONMENT="$E" UV_PYTHON_DOWNLOADS=never uv sync --locked --python "$P" --no-python-downloads --no-progress
UV_PROJECT_ENVIRONMENT="$E" UV_PYTHON_DOWNLOADS=never uv run --locked --no-sync --no-env-file --python "$P" pytest -q 'tests/test_planner_environment_lock.py::test_wheel_url_ownership_identity_is_rfc_canonical[ipv6-mapped-ipv4]'
UV_PROJECT_ENVIRONMENT="$E" UV_PYTHON_DOWNLOADS=never uv run --locked --no-sync --no-env-file --python "$P" pytest -q tests/test_planner_environment_lock.py
UV_PROJECT_ENVIRONMENT="$E" UV_PYTHON_DOWNLOADS=never uv run --locked --no-sync --no-env-file --python "$P" pytest -q
UV_PROJECT_ENVIRONMENT="$E" UV_PYTHON_DOWNLOADS=never uv run --locked --no-sync --no-env-file --python "$P" ruff check .
UV_PROJECT_ENVIRONMENT="$E" UV_PYTHON_DOWNLOADS=never uv run --locked --no-sync --no-env-file --python "$P" mypy algua scripts
UV_PROJECT_ENVIRONMENT="$E" UV_PYTHON_DOWNLOADS=never uv run --locked --no-sync --no-env-file --python "$P" lint-imports
```

`uv sync` was run before these commands in each environment. Actual executables: CPython 3.12.3 `/usr/bin/python3.12`; CPython 3.12.12 `/home/liornisimov/.local/share/uv/python/cpython-3.12.12-linux-x86_64-gnu/bin/python3.12`; uv 0.9.26 at `/home/liornisimov/.local/bin/uv`; pytest 9.0.3, Ruff 0.15.15, mypy 2.1.0 and import-linter 2.11 from the locked environments. Both builds reported `linux-x86_64`, cache tag `cpython-312` and SOABI `cpython-312-x86_64-linux-gnu`. The baseline evidence report records per-command log hashes, environment inventories, input hashes, and the isolated execution environment.

### Distinguishing prior upstream claims

The above table is the fresh baseline task's actual output. Earlier Task0/upstream material cited a full 3.12.12 result of 6324 passed / 5 skipped and other focused counts. That full count was not reproduced in this baseline run and is not reported as its result. Separate upstream documentation/story gates (including a 3.12.3 root run) are likewise not evidence for this baseline matrix or for the final assembled docs head. The baseline's own full counts are 6291 passed on 3.12.3 and 1 failed / 6290 passed on 3.12.12.

## Boundedness and persisted compatibility assessment

The proposed contract is bounded in principle: format only an already validated IPv6 address at the existing `wheel_url_identity` authority seam, with numeric eight-hextet lowercase formatting and compressed zero-runs; preserve the accepted URL language, validator, rejection order, errors, raw lock URL keys, and exact uv inputs. The identity is proposed as a transient ownership index, not a replacement lock key. Duplicate ownership and outage attribution are addressed without expanding retry policy. Consumer paths are inspection-only, and frozen/offline verification must continue not to acquire or normalize locks.

The upstream source/consumer and persistence review reports no persisted wheel-identity field in the inspected repository call graph; the fresh baseline lock probe found 1900 raw entries/keys/identities in each environment and no raw entry whose current identity differs from itself. This is bounded repository evidence, not a production-registry audit or proof about arbitrary historical data. No migration, descriptor/digest/schema version change, or recorded-object rewrite is proposed. A future source change can normally alter exported source bytes and new bundle/manifest digests while leaving digest domains/versions unchanged. If implementation evidence finds any persisted or digest-bound identity, changed committed raw key/identity, changed bundled-strategy `code_hash`, or other unexpected compatibility consequence, stop and obtain Lior's review; do not invent a migration or claim no impact.

## Proposed scope, non-goals, blockers, and authority

The SPEC and story remain **proposed, not approved/not normative and not ready-for-dev**. Their eventual product/test allowlist is exactly:

- `algua/registry/planner_environment_lock.py`
- `tests/test_planner_environment_lock.py`
- `tests/test_planner_environment_outage.py`

Consumers are inspection-only. No broader refactor, lock or dependency change, installer/argv or build-input change, interpreter pin/change, package metadata change, CI/workflow/CODEOWNERS/diff-policy change, descriptor/digest/schema-version change, publication/verifier policy change, approval/signer/runtime change, artifact migration/rebuild/repair, operational registry inventory/write, live activation, capital action, or provider/broker call is in scope or authorized. Story 1.3b and its delivered contracts remain closed and authoritative.

Unresolved blockers: the existing 3.12.12 mapped-IPv6 regression remains red; the final assembled-docs-head dual-patch gates and independent exact-head QA are outstanding; remote CI evidence is outstanding. These do not authorize suppressing the existing failure. Before any protected implementation card, require independent review of the story, proposed SPEC/field companion and readiness report; a reviewed docs merge with Lior approval for that exact head; refreshed readiness on the merged head against then-current main; and **explicit scoped Lior approval for the protected three-file implementation**. That approval does not authorize an implementation merge or deployment; those require separate approval. No implementation is authorized by this report or its creation.

No operational registry writes, operational commands, provider/broker calls, trading actions, merge, deployment, or authority/protection changes were performed for this report. The baseline tests used isolated test fixtures and fake provider/broker interfaces only.
