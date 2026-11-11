# Qualification profile compatibility audit

Reviewed 2026-11-08 at `d55c325` on `feat/pinned-model-frozen-paper`. This is a source/fixture
audit, with no registry migration, deployed-account inspection or live activation.
Implementation references below are relative to `algua/`.

The November 8 [capped profile](capped-live.md) is separate from the strict forward-certificate
route. Its historical-plus-five-session evidence does not implement the October 4
[Story 2.1](../development/stories/2-1-refuse-live-qualification-on-relaxed-gates.md)
contract in full. Keep that story open; its dated schema version and rollout cannot be copied
onto the current tree.

## Boundaries verified

| Route | Current evidence and authority |
| --- | --- |
| Strict | `registry/live_certificate.py:83` selects the newest strategy/deployment/artifact-matched forward row, then checks pass, freshness, clean ticks, halt state and account hygiene. `registry/transitions.py:140` requires human authority before certificate and approval checks. Raw strict go-live still refuses frozen deployments (`registry/transitions.py:219`). |
| Experimental qualification | `registry/experimental_qualification.py:24` requires a passing PIT gate without PIT override, matching artifact identity, at least 63 sealed OOS observations, committed nonreused holdout lineage, consistent chronology and positive finite OOS Sharpe. The report binds five contiguous scheduled paper sessions and explicitly records `live_authority: false` (`:94`). Recording leaves the paper stage unchanged and creates no forward certificate. |
| Capped frozen live | `registry/capped_context.py:82` binds the distinct `capped-frozen-live/v1` profile, exact deployment/content/qualification, accounts, provider, signed instruments/risk policy and capital. `registry/capped_auth.py:82` issues a separate challenge; only verified human signing reaches atomic activation. The legal paper/forward/live stage edges use explicit experimental reasons (`registry/capped_state.py:133`) and create no strict certificate. Trade-time verification rebuilds this context and rechecks canonical qualification sources. |

## Remaining protected work

All findings below are **Important, flag-only**: they concern authorization policy, protected
schema/writers or live-wall enforcement. No protected implementation changed in this audit.

1. **The complete relaxation set is not persisted.** `registry/db/gate.py:25` and
   `registry/db/forward_gate.py:20` have no `relaxations_json`; neither research INSERT
   (`registry/store/gate.py:85`, `:386`) nor the shared forward INSERT
   (`registry/store/forward_gate.py:107`) writes one. Existing actor/PIT/breadth fields,
   threshold fragments and signed human-actor run contexts are not the immutable, closed,
   per-evaluation classification required by Story 2.1. Implement the protected vocabulary,
   full option classification, write-time canonical sets and immutable insert/update/replace
   rules across every pass/fail writer. Unknown historical rows must remain unrecorded.
2. **Strict go-live does not enforce the Story 2.1 predicate.** Challenge issuance calls the
   certificate verifier directly (`cli/registry_cmd.py:151`); completion ignores the verifier's
   returned certificate ID before checking approval (`registry/transitions.py:146`). Neither
   rejects a relaxed/unrecorded research or forward row. The legacy-cohort certificate branch
   also remains (`registry/live_certificate.py:91`). Implement one protected wrapper at both
   ceremony sites, after even an injected certificate verifier, judging the exact active
   deployment and newest selected forward row. Refuse before challenge issuance or signature
   consumption with the reviewed stable error; no human-signature waiver.
3. **The capped profile does not prove every research input was unrelaxed.**
   `registry/experimental_qualification.py:24` checks explicit PIT/lineage/holdout conditions;
   `:65` checks the recorded pass and Sharpe. It does not reject all declared-breadth,
   terminal-last-close, family, actor-wall or advisory-threshold relaxations from the old
   vocabulary. Current research thresholds remain advisory by profile
   (`registry/experimental_sessions.py:14`). Human review must reconcile the old blanket
   no-relaxation policy with this explicit newer profile, specify the permitted research
   classification for each route, and bind the approved rule to immutable profile identity.
   Do not label capped qualification as strict or infer missing flags as false.
4. **Story 2.1's schema/entry-point plan needs rebasing.** `registry/db/constants.py:36` already
   uses v49 for the paper equity peak; current schema is v52. The October production-row counts
   and v48/v49 rollout are historical. Choose the next reviewed migration version, classify a
   fresh backup conservatively, rehearse idempotence and update writer/rollback inventories.
   Its raw-edge AC also remains separate: current `registry/transitions.py:78` exempts humans
   on the candidate edge and `:88` exempts them from the working-tree forward token check.
   Implementing those refusals requires protected review; preparatory regression files alone
   do not establish that production paths refuse them.

## Focused verification

Ran the existing offline Linux helper with network disabled:

```sh
.superpowers/sdd/2026-11-07-pinned-model-frozen-paper/linux-exec-admin pytest -q \
  tests/test_experimental_qualification.py tests/test_forward_certificate.py \
  tests/test_capped_live.py -k 'not frozen_live_uses_real_child_after_checkout_removal and not normal_live_cli_routes_frozen_tenant_without_checkout and not allocation_decrease_during_tick_aborts_stale_sizing'
```

**66 passed, 4 deselected (6.88s).** Coverage includes qualification creating no strict-stage or
certificate credit, capped activation creating no forward certificate, signed-context changes,
source/provider drift, replay/revocation and strict certificate presence/ordering/freshness.
The fixtures use synthetic rows, temporary registries and fake brokers; they are not economic
qualification or real-account acceptance. Source-writing frozen fixtures completed teardown.
Full-root validation and the four unrelated child/tick cases were intentionally omitted for
this bounded audit. No claim is made that the missing Story 2.1 predicate is tested or delivered.
