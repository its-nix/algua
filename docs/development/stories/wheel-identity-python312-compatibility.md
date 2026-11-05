---
baseline_commit: db6860000f87a6cc98469e0e4901fa9c10c0d277
status: proposed
---

# Story: Wheel identity Python 3.12 compatibility

Status: proposed

**NOT ready-for-dev.** This is a proposed follow-up, pending independent review, a docs merge,
refreshed readiness and explicit scoped approval from Lior. Neither creating this story nor Lead
docs admission implies approval. Story creation grants no implementation approval, and no merge,
deployment or protected-control approval. An implementation card may be created only after the
prerequisites below are evidenced.

Prepared: 2026-10-31. Baseline: `db6860000f87a6cc98469e0e4901fa9c10c0d277` (PR #711 merge).
Relates to: [Story 1.3b](1-3b-materialize-and-verify-recoverable-planner-artifacts.md), whose delivered
scope stays closed. This story links it and does not duplicate, edit or reopen it.
Queue: Kanban is the technical queue for this initiative, per its admission mandate; this docs task
creates no implementation work in Todoist or Kanban.

Draft provenance: preserved Claude Code story draft from the preparation worktree, adopted in task
`t_9e402dcc` with coordinator alignment to specification commit
`644ac24569fc940e2ba41d4aad32226af5bfb2e4`. Acceptance expectations below are future obligations,
not claims of implementation or verification.

## Story

As Algua's operator,
I want a locked wheel URL with an IPv6 host to have one ownership identity on every interpreter that
runs the gate,
so that duplicate-owner and outage decisions do not depend on how a Python patch release renders
text, and the existing golden holds on both installed 3.12 interpreters.

## Problem

`_authority` spells a validated IPv6 host with `IPv6Address.compressed`
(`algua/registry/planner_environment_lock.py:103` at the baseline). On 3.12.12 that property renders an
IPv4-mapped address with a dotted suffix; on 3.12.3 it renders all-hex. The golden
`https://[::FFFF:192.0.2.10]/x.whl` → `https://[::ffff:c000:20a]/x.whl` therefore fails on 3.12.12.
`.exploded` differs as well, so it is no naive replacement.

Both identities in any comparison are computed in one process; the specification's source
inspection identifies no current cross-interpreter misattribution. The known defect is
interpreter-dependent identity and a red gate, not evidence of a production incident. Operational
reach depends on the interpreter a gate selects. The dependent readiness task will create
`docs/development/implementation-readiness-report-wheel-identity-python312-compatibility.md` and
record fresh results separately from upstream evidence. This story does not claim those results.

## Scope and authority

Proposed scope is the formatting of an already-validated IPv6 address inside `wheel_url_identity`,
and tests proving that nothing else moved.

- The identity is a transient ownership index only. The raw locked URL stays the `locked_wheels` key
  and uv's exact input; uv never receives an identity in place of that URL.
- The accepted URL language, validation grammar, rejection order, messages and error taxonomy do
  not change. `ipaddress.IPv6Address` remains the validator.
- No changes to locks, dependency identity, build inputs, installer argv, descriptor/digest/schema
  versions, publication/verifier policies, approvals/signers or runtime behavior are authorized.
- No interpreter pin, backward pin, skipped test or weakened assertion is acceptable. `.python-version`
  remains `3.12` and `requires-python` remains `>=3.12`. Exercising 3.12.3 and 3.12.12 is not proof
  of every interpreter admitted by that metadata, or of every platform.
- Offline `deployment verify` and frozen runtime verification acquire nothing and never read or
  normalize a lock; this remains unchanged.

## Proposed contract and existing authority

The proposed [SPEC](../specs/spec-wheel-identity-python312-compatibility/SPEC.md) and its
[field-level companion](../specs/spec-wheel-identity-python312-compatibility/wheel-identity-fields.md)
carry the algorithm, literal vectors, rejection matrix, entry-point inventory and compatibility
analysis. They are proposed, not yet normative; their approval condition remains binding.

The delivered [Story 1.3b machine contract](../specs/spec-story-1-3b-artifact-environment-contract/SPEC.md)
and [artifact/environment contract](../specs/spec-story-1-3b-artifact-environment-contract/artifact-environment-contract.md)
retain their existing authority. This follow-up does not redefine their environment materialization,
immutable publication, descriptor or offline-verification scope. Implementers and reviewers must
read both existing contracts and both proposed documents.

## Proposed eventual product/test allowlist — not authorization

| Path | Bounded future change, only after approval |
|---|---|
| `algua/registry/planner_environment_lock.py` | Numeric IPv6 formatter at the existing authority seam; preserve validation and raw-lock handling |
| `tests/test_planner_environment_lock.py` | Literal vectors, compression/idempotence, ownership, raw-key and unchanged grammar assertions |
| `tests/test_planner_environment_outage.py` | Bidirectional mapped aliases and unchanged fail-closed retry boundaries |

These are the **only three** proposed product/test files. Consumers are inspection-only, not
refactoring scope: in particular `planner_environment.py`, `planner_environment_outage.py`,
preparation, intake, merge-back, verifier and frozen-runtime code remain unedited. Existing module
size/import ratchets remain binding. Evidence-only documentation updates do not expand this
product/test allowlist or grant implementation authority.

No edits to `epics.md`, `sprint-status.yaml`, shared README, Task0/CI docs, workflows, `CODEOWNERS`,
diff policy, Story 1.3b or its contracts are admitted here. No locks, package metadata, interpreter
settings, installer flags, registry data or recorded/published artifacts may be changed. No
migration, rebuild, repair, live activation, capital action, provider/broker call or operational
registry write is authorized.

## Prerequisites before any implementation card

1. Independent review of the story, proposed SPEC, field companion and readiness report.
2. Docs merge through reviewed merge controls, with Lior's approval for that exact-head merge.
3. Refreshed readiness on the merged head against then-current `main`, including unresolved items.
4. Explicit scoped approval from Lior for the protected implementation and the three-file scope.

Only after all four are evidenced may implementation be admitted. Routine standing implementation
approval does not substitute for this protected-path decision. Any eventual implementation merge
or deployment needs separate approval; docs admission or merge is not deployment authority.

## Acceptance criteria (future; not executed by this story's creation)

1. **Golden preserved.** `https://[::FFFF:192.0.2.10]/x.whl` yields exactly
   `https://[::ffff:c000:20a]/x.whl` on 3.12.3 and 3.12.12. Preserve every existing
   `WHEEL_URL_IDENTITIES` literal; add coverage rather than changing expected identities.
2. **Interpreter-invariant literal vectors.** Every companion §3 row passes literally on both
   versions, including mixed, hex, padded and expanded mapped equivalents, mapped boundaries and
   non-mapped dotted input. Use the validated numeric 128-bit value, eight minimal lowercase hex
   groups, longest zero run of length at least two, leftmost tie, and correct leading/trailing/all-zero
   `::`. Never emit a dotted suffix. Include singleton and competing-run cases; every output is
   idempotent and preserves the parsed address. Record red first where current 3.12.12 differs.
3. **No stdlib text-rendering dependency.** Deny `IPv6Address.__str__` in a test and still obtain the
   literal identities; do not derive output from `str()`, `.compressed`, `.exploded` or a private
   stdlib text formatter. Keep the stdlib validator, not its rendering policy.
4. **Language and first failure unchanged.** Every companion §4 rejection row raises
   `EnvironmentIncompatible` with `str(exc.value) == expected_message`, including malformed IPv6,
   bare/escaped scopes, IPvFuture, credentials, bad numeric/DNS hosts, ports and percent escapes,
   fragments, path/query syntax and wheel suffix cases. Preserve exact exception class, message and
   first-failure order, including address before port, host before port and authority before path.
   Keep URL regexes unchanged and exercise the accepted 45-character and rejected 46-character
   literal boundaries. Preserve lock-level URL/hash/duplicate validation order.
5. **Equivalent duplicates refused.** Any two of the companion's mapped-equivalent spellings locked
   under two packages raise exactly `a wheel URL is locked for more than one package` on both
   interpreters. Aliases within one package also remain rejected by the global ownership check.
   Accepted `locked_wheels` entries retain exact raw keys; `locked_wheel_owners` uses identities.
6. **RFC-distinct stays distinct.** Every companion §5 pair yields different identities and is
   accepted under two packages with both exact raw keys: reserved escape versus raw character,
   escaped versus real separator, query absent/empty/order/case, path case/empty segment,
   default/non-default port, IPv4 versus mapped, mapped versus compatible/translated, and different
   mapped addresses. Do not conflate those URLs when fixing address spelling.
7. **Outage aliases, not broader retry.** Every companion §7 row holds on both interpreters, using
   the recorded-report fixture with URL substitution in both locked/reported directions. Mixed,
   all-hex, expanded and default-port aliases resolve to the same locked distribution owner.
   Unlocked/different addresses, plain IPv4, malformed/scoped literals, wrong distribution, repeated
   differently spelled later causes, hash mismatch and final timeout remain non-retryable. Preserve
   report shape, the single-report rule and exact cause/temporary-failure allowlists; no recognizer
   or retry semantics change. These are synthetic alias expectations, not captured uv IP-literal
   network evidence. An unrecognized actual report remains fail-closed.
8. **Committed lock unchanged.** Enumerate all committed wheel raw keys and identities against the
   baseline; every key and identity remains unchanged on both versions. No lock rewrite or uv-input
   substitution. Verify the baseline wheel inventory rather than silently assuming its count.
9. **Compatibility impact evidenced.** Confirm the transient-index finding from companion §9 and
   record actual before/after `code_hash` for every bundled strategy. A future product source edit
   normally changes exported source bytes and new `bundle_digest`/`manifest_digest` values; this is
   not a descriptor/digest/schema version change or permission to mutate recorded objects. For a
   given interpreter, build-input/dependency/environment identity inputs remain unchanged. Report
   actual consequences; do not promise all future digest values stay the same.
10. **Test-first and mutation evidence.** After approval, capture failing regression tests before
    the formatter change. Mutation-check new guards: stdlib rendering (`.compressed` on 3.12.12 and
    the rendering guard on 3.12.3; `.exploded`), compressing singleton zeros, refusing a two-zero run,
    rightmost tie, uppercase or padded groups, and moving port validation ahead of address
    validation. Confirm each mutation fails a relevant test, restore byte for byte, and rerun.
11. **Full dual-patch gates.** Use separately locked environments and the two installed interpreters,
    no interpreter downloads. Full pytest, `ruff check .`, `mypy algua scripts` and `lint-imports`
    must exit zero on both 3.12.3 and 3.12.12 for implementation acceptance. Preserve module/import
    ratchets. Existing failures stay explicit; never skip/weaken tests or downgrade to hide them.
12. **Independent exact-head evidence.** Independent Codex QA reviews the implementation diff;
    required CI is read back for the exact head. A single CI interpreter does not replace AC11.
    This proposed story alone satisfies none of these future product acceptance criteria.

## Stop conditions

Stop and flag to Lior, rather than inventing migration or widening scope, if a persisted or
digest-bound wheel-identity use contradicts the transient-index finding; any committed raw lock key
or identity would change; accepted-language behavior differs between the two interpreters; a file
outside the allowlist needs editing; or preserving the golden would require a skipped/weakened test
or backward pin. A changed bundled-strategy `code_hash` also requires stopping and review. No
production-registry compatibility claim is made from repository-only inspection.

## Tasks / subtasks (future; all blocked on the prerequisites)

- [ ] Evidence all admission prerequisites and refresh the baseline (all ACs).
- [ ] Add failing literal, rendering-guard, rejection, ownership and RFC-distinct tests (AC1–AC6).
- [ ] Add bidirectional outage alias and negative tests (AC7).
- [ ] Implement only the numeric formatter and existing call site (AC2–AC3).
- [ ] Prove raw-lock and identity/hash outcomes, stopping on unexpected effects (AC8–AC9).
- [ ] Record mutation kills and restoration (AC10).
- [ ] Record full locked dual-patch gates, independent QA and exact-head CI (AC11–AC12).

These unchecked tasks are an acceptance outline, not independently claimable implementation work.
The current deliverable is documentation only. No product repair, full-gate success, remote CI
acceptance, merge or deployment is asserted by story creation. Readiness/assembly and independent
QA remain separate dependent Kanban phases.

## References

- [Delivered Story 1.3b](1-3b-materialize-and-verify-recoverable-planner-artifacts.md)
- [Story 1.3b SPEC](../specs/spec-story-1-3b-artifact-environment-contract/SPEC.md)
- [Existing artifact/environment contract](../specs/spec-story-1-3b-artifact-environment-contract/artifact-environment-contract.md)
- [Proposed compatibility SPEC](../specs/spec-wheel-identity-python312-compatibility/SPEC.md)
- [Proposed field-level companion](../specs/spec-wheel-identity-python312-compatibility/wheel-identity-fields.md)
- [Canonical PRD](../../PRD.md), §§10, 18–19; [current architecture](../../architecture.md)
- [Story delivery workflow](../../agent/story-delivery.md); [operating playbook](../../agent/operating.md)
