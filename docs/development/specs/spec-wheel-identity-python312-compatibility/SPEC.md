---
id: SPEC-wheel-identity-python312-compatibility
status: proposed
companions:
  - wheel-identity-fields.md
  - ../../stories/wheel-identity-python312-compatibility.md
sources:
  - ../spec-story-1-3b-artifact-environment-contract/SPEC.md
  - ../spec-story-1-3b-artifact-environment-contract/artifact-environment-contract.md
---

> **Proposed follow-up contract. Not approved, not ready-for-dev, not yet normative.** This SPEC
> and its companion become normative
> only after independent review, a docs merge and explicit scoped approval from Lior. Creating them,
> or admitting them to the docs lane, grants no implementation, merge, deployment or protected
> control approval. Story 1.3b and its contract stay closed and unedited; this document links them.

# Wheel identity Python 3.12 compatibility

## Why

`wheel_url_identity` decides duplicate wheel ownership and outage attribution for the committed
lock. For an IPv4-mapped IPv6 host it delegates spelling to `IPv6Address.compressed`, whose output
differs between the two installed 3.12 interpreters:

| Interpreter | `IPv6Address("::FFFF:192.0.2.10").compressed` | `.exploded` |
|---|---|---|
| 3.12.3 | `::ffff:c000:20a` | `0000:0000:0000:0000:0000:ffff:c000:020a` |
| 3.12.12 | `::ffff:192.0.2.10` | `0000:0000:0000:0000:0000:ffff:192.0.2.10` |

The existing golden `https://[::ffff:c000:20a]/x.whl` for `https://[::FFFF:192.0.2.10]/x.whl`
therefore holds on 3.12.3 and not on 3.12.12. `.exploded` differs too, so it is no naive
replacement. The identity must stop depending on stdlib text rendering.

## Capabilities

- id: CAP-1
  intent: A locked wheel URL with an IPv6 host has one ownership identity on every interpreter that
    runs the gate.
  success: Every vector in the companion yields the same literal output on 3.12.3 and 3.12.12,
    including the unchanged golden `https://[::ffff:c000:20a]/x.whl`.
- id: CAP-2
  intent: The set of accepted URLs and the way each rejected URL is rejected stay exactly as they
    are.
  success: The companion's rejection matrix passes unchanged, with the same exception class,
    message and first-failure order, and all committed lock raw keys and identities are unchanged.
- id: CAP-3
  intent: Duplicate ownership and outage attribution treat equivalent IPv6 spellings as one owner
    without widening retry.
  success: Equivalent mapped spellings cannot claim two owners; a reported alias is attributed to
    the same locked owner in both directions; malformed, unlocked and integrity failures stay
    non-retryable.

## Constraints

- The field-level algorithm, vectors, rejection matrix and inventory in `wheel-identity-fields.md`
  are the proposed contract.
- The identity is an ownership index only. The exact raw locked URL remains the `locked_wheels` key
  and uv's input. `uv.lock` is never rewritten and uv never sees an identity.
- The IPv6 identity is lowercase, compressed and all-hex for every address, mapped addresses
  included. A dotted IPv4 suffix is never emitted, and stdlib text properties are never used for
  it. This deliberately differs from the RFC 5952 mixed-notation recommendation for mapped
  addresses, because the existing golden is all-hex.
- `ipaddress.IPv6Address` remains the validator. Only formatting of the already-validated address
  changes, so the URL grammar and regular expressions are untouched.
- The change adds no dependency, interpreter pin, build input, installer argument, lock change,
  descriptor, digest or schema version, publication or verifier policy, signer or runtime behavior.
- `is_locked_wheel_outage` keeps its exact report shape, cause allowlist, single-report rule and
  retry semantics. Canonical owner attribution does not broaden any of them.
- `deployment verify` and the frozen runtime path acquire nothing and never read or normalize a
  lock; that stays true.

## Relationship, scope and eventual implementation allowlist

This is a separate compatibility follow-up to delivered
[Story 1.3b](../../stories/1-3b-materialize-and-verify-recoverable-planner-artifacts.md), its
[canonical SPEC](../spec-story-1-3b-artifact-environment-contract/SPEC.md) and its
[artifact/environment contract](../spec-story-1-3b-artifact-environment-contract/artifact-environment-contract.md).
Those documents retain their authority and delivered status; this proposal does not reopen them.
The companion inventories both direct calls and prepare/intake/verify reachability.

If explicitly approved later, the proposed product/test allowlist is only:

- `algua/registry/planner_environment_lock.py`: numeric IPv6 formatting at the existing authority
  seam, with validation and raw-lock handling preserved;
- `tests/test_planner_environment_lock.py`: literal vectors, compression/idempotence, duplicate
  ownership and unchanged raw-key/grammar assertions;
- `tests/test_planner_environment_outage.py`: bidirectional mapped alias attribution and unchanged
  fail-closed retry boundaries.

No product or test edit is authorized by this drafting task. Consumer files are inspection-only,
not an invitation to refactor. A required change outside this allowlist stops for scope review.
Future acceptance requires red/green and mutation evidence, the full locked pytest, ruff, mypy
(`algua scripts`) and lint-imports gates on both installed 3.12.3 and 3.12.12, independent Codex
review, and exact-head CI readback. Existing failures must remain visible, not skipped or weakened.

`.python-version` is `3.12`; project `requires-python` is `>=3.12`. This proposal changes neither.
The spelling algorithm is interpreter-invariant by its numeric definition; that is not evidence
that every interpreter admitted by package metadata or every platform has been exercised.
The provisioning minor-pin check remains unchanged.

No persisted wheel-identity field was found in the inspected repository call graph. No migration
or version bump is proposed. This does **not** promise that future source commits have unchanged
bundle/manifest digest values: exact exported source bytes and source references continue to bind
new artifacts normally. Existing descriptor bytes, digest domains/versions and recorded objects
remain untouched; see companion §9 for the distinction and stop conditions.

## Non-goals

- Changing any accepted or rejected URL, or tightening or loosening the IPv6 grammar.
- Pinning, downgrading or upgrading an interpreter, or changing `.python-version`,
  `requires-python`, `uv.lock` or package metadata.
- Claiming support for any interpreter other than the two verified patch releases.
- Adding CI matrix entries or editing workflows, `CODEOWNERS` or the diff policy.
- Migrating, rebuilding or repairing any recorded artifact, or inventorying a production registry.
- Editing Story 1.3b, its contract or any broader consumer.

## Stop conditions

Stop and flag to Lior instead of inventing a migration or widening scope if any of these appears:

- a persisted or digest-bound use of the identity, contradicting the transient-index finding;
- a committed `uv.lock` key or identity that would change;
- an interpreter-specific acceptance difference between 3.12.3 and 3.12.12, which the source trace
  does not predict;
- a need to touch a file outside the proposed allowlist;
- the golden becoming unsatisfiable without weakening, skipping or pinning a test backwards.

## Success signal

On a reviewed, explicitly approved implementation head, every companion vector passes on both 3.12.3
and 3.12.12; the rejection matrix and all existing tests pass unchanged; the mutation checks are
killed; and the full locked gates, independent Codex QA and exact-head required CI are read back.
This proposal itself delivers none of that evidence.
