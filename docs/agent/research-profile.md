# Pinned midcap research profile

`ALGUA_RESEARCH_PROFILE` is an opt-in path to a complete JSON descriptor. The reviewed example is
[`deploy/research/midcap-profile.json`](../../deploy/research/midcap-profile.json). Install it as
`/etc/algua/midcap-research-profile.json`, owned by the deployment owner and readable by research.
Set the variable in the actual service environment; no setting means unchanged legacy behavior.
A configured driver requires existing `--choose-campaign` or `--campaign` mode.

The descriptor fixes snapshot `c63d16f44419cb96`, `[2024-11-01,2026-11-08)`, its logical payload hash
and the exact 300-name reviewed CONFIG membership hash. The larger snapshot has 400 names; it does
not expand the profile. The literal CONFIG is parsed without importing strategy Python.

Canonical descriptor SHA256: `141b63119de47343db027750521ae31872769ddf39cb0aa2a6e92ae48a2f5427`.
Sorted-symbol canonical-JSON SHA256: `1abefef02ee2d02204fbed780161a6e058b392f6b9bc6959d4bd7d852695987a`.
Payload hash: `5b3d7c7b0d2dd987cb0eb563e5d4eff98b6ae0621854a30ac837ac9248250ac0`.
These hashes are identity/readback evidence, not PIT certification or predictive evidence.

Before chooser/claims, the driver validates all fields, manifest identity, actual full logical bar
content, dates, membership and all seven proxy limitations. The existing controller binds the
receipt into source/data context; a mismatched admission refuses setup. The same complete receipt
is attached to each projected claim and the primary goal, with instructions to pass it unchanged
to author/interpret tasks. Copied worker payload and CONFIG are rechecked before launch. Prompt
propagation is not proof of actual model task receipt/use or a strategy execution sandbox.

The profile fixes daily static-universe exploration, costs/construction and chronological evaluation
settings. Conflicting hypothesis inputs produce `run_error`; data substitution is not permitted.
Proxy reports record known data exclusions as `data_blocked`, actual integrity failures as
`integrity_fail`, or operational `run_error`, with empirical findings kept
separately. A candidate/merge-back or gate verdict in such a report is refused before controller
completion; bound proxy campaigns also cannot publish merge-back work. No PIT label, promotion,
forward session, live authority or source switch follows from a receipt.

Read-only verification on the intended Linux release, before enabling research:

```sh
export ALGUA_RESEARCH_PROFILE=/etc/algua/midcap-research-profile.json
export ALGUA_DATA_DIR=/home/algua/datasets/midcap-machinery-2026-11-08/data
uv run python -c 'import json,os; from pathlib import Path; from algua.operator.research_profile import load_research_profile; print(json.dumps(load_research_profile(Path(os.environ["ALGUA_DATA_DIR"])),sort_keys=True))'
.opencode/scripts/run-research-loop.sh --choose-campaign --hypotheses 3 --workers 1 --cpu-seconds 1200 --timeout 20m --memory-mb 16384 --file-mb 512 --dry-run
```

The dry run verifies configured source inputs but claims no ideas and invokes no model. Deployment,
retained-memory compatibility, credentials and service activation remain the trusted operator's
separate checks. Use the existing six-hour cadence and preserve prior checkpoints/receipts unchanged.

## Diagnostic controls

The primary strategy retains the pinned construction. A sweep can declare
`"evaluation_role":"benchmark","benchmark_for":"<primary strategy name>"`; the control's
CONFIG.params must contain the same markers so its role/target survive existing archival input
serialization and identity hashing. Include the primary sweep in the same batch. A diagnostic
control may use `equal_weight_positive` with empty construction_params, or the usual top-20 policy.
All other profile inputs/costs/timing remain fixed. Declare a common conservative feature_lookback
to align effective embargo/windows. Mismatches reject the entire declared batch before simulation.
Normal measured trial/search-breadth recording still applies. Role labels grant no authority;
benchmark metadata is sweep-only and cannot request registration or promotion. The pilot remains
qualification-ineligible, and its report/merge-back refusal boundaries are unchanged.

### Empirical assessment and qualification

`research campaign-menu` retains the authoritative attempt `outcome` and separately projects
`reported_falsification_assessment` (`refuted`, `survived`, `untested`, or `unknown`). The completed
worker report in the existing operational `research-runs.jsonl` supplies this advisory field only
when cycle, idea, terminal ledger outcomes and controller counts match. It is **UNVERIFIED_WORKER**,
authority **none**; the digest is not tamper-evident or a verified numerical conclusion. Family and
category `reported_empirical` counts stay separate from existing economic/gate counters. Selection
receives both axes; eligibility and automatic priority rules are unchanged.

A qualification-ineligible proxy can report a refuted hypothesis. An untested comparison is not a
refutation, and survived is not established profitability. Missing/legacy/ambiguous assessments
stay unknown. Reads do not rewrite attempts, archives or stages. Missing, malformed, concurrently
changed, linked, or oversized digest files (2 MiB ceiling) yield unavailable coverage and unknowns;
repair the source separately rather than guessing conclusions. Research results in the dashboard
show these worker-reported assessments alongside qualification outcomes.
