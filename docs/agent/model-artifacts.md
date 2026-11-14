# Local model artifact commands

Prepared local artifact bytes can be registered through the existing model registry:

```sh
uv run algua model register NAME --artifact prepared.bin --metadata training.json
uv run algua model show NAME --version 1
uv run algua model list NAME
```

The commands use the configured `<data_dir>/models` store. They do not train, deserialize or run
the artifact, resolve a strategy, mirror to MLflow, contact a remote service or advance a lifecycle.
Existing author-agent restrictions on registry writes remain in force.

The separate [offline proxy producer](model-training.md) adds `model train-linear`; the prepared
artifact commands above retain their declared-metadata behavior.

`training.json` is UTF-8 JSON with exactly these six required keys:

```json
{
  "training_snapshot_id": "declared-training-snapshot",
  "training_as_of": "2026-01-02",
  "code_hash": null,
  "hyperparameters": {},
  "seed": 0,
  "eval_report": {}
}
```

Snapshot and code declarations accept a string or null. Hyperparameters and evaluation report
accept an object or null; the existing API stores null maps as empty objects. Seed is an integer
or null, with booleans excluded. Unknown/missing keys, duplicate keys at any nesting depth,
incorrect types and nonfinite numbers (including exponent overflow) refuse before registration.
The metadata input fits 1 MiB and the artifact input fits 64 MiB. The CLI opens nonblocking,
requires regular files through their descriptors and reads at most the limit plus one byte to
detect excess input. These are input materialization bounds; existing registry operations and
manifest/artifact verification are not a bounded whole-operation I/O or deadline contract.

Training metadata is **declared**. The cutoff must parse as a finite timestamp through the existing
normalizer; the original text is stored and pinned unchanged. Bare dates and naive timestamps are
accepted under that normalizer's UTC convention, as are valid future declarations. Registration
does not establish honest training, point-in-time eligibility, predictive quality or qualification.
Existing loader, context and evaluation checks still determine whether a pin can be used.

Register and show return JSON `ok` plus the exact `ModelRef` fields `name`, `version`, `digest`,
`training_as_of`, `provenance_digest`, and the four fields `created_at`, `training_snapshot_id`,
`code_hash`, `seed`. Artifact/provenance digests retain the existing 16-hex format. Full
hyperparameters, evaluation reports, artifact paths and bytes are omitted. List returns
`{"ok": true, "versions": [...]}` using the same projection in ascending version order. It
verifies every manifested version and fails the whole read on corruption; a missing name returns
an empty list without creating a store. Model-registry failures retain the existing generic
`internal` JSON error code and nonzero exit. Usage/input failures also emit JSON with nonzero exits.

Every registration creates a new immutable version, even for identical bytes and metadata.
Unmanifested version directories remain reserved gaps and are excluded from list/show. There is
no force, latest, delete, root override, all-name catalogue or automatic retry. A failed
acknowledgement can follow durable publication; inspect explicit versions before deciding what
to do next.

Research memory preserves model references, not model bytes. The current research driver copies
snapshots and their manifest into scratch; this command does not add model transport, cross-cycle
artifact retention or a training pipeline. It also does not expand the separate public-memory
name/reference vocabulary.

## Frozen dense inference reference

`features.dense_network.FrozenDenseNetwork` supplies inference only, using existing NumPy/pandas.
Its `frozen-dense/v1` JSON has exactly `schema`, ordered unique `features`, and three `layers`.
Each layer has exactly `weights` (output-by-input rows) and `bias`. Both hidden layers apply ReLU;
the final layer has one linear output. Inputs/parameters and every layer result must be finite
real float64 values; booleans, invalid dimensions, duplicate/unknown keys and wrong feature order
refuse. Limits: 64 KiB encoded model, 32 inputs/hidden units, three layers and 4096 scoring rows.
`from_json(bytes)`, `to_json()` and `predict(DataFrame) -> Series` perform no file or registry I/O,
training, random sampling or order execution. Output is a score, not a weight or order.

The supplied `model_dense_scores` context strategy uses one/five-observed-bar returns and a
2→2→2→1 network. Its weights are **hand-authored and untrained**; the illustrative declared cutoff
does not establish historical knowledge or PIT correctness. Null training snapshot/seed and the
`hand_authored_inference_fixture` evaluation marker are part of the exact provenance pin.
Prepare the fixture files offline, then use the existing commands in a fresh local model store:

```python
import json
from pathlib import Path
from algua.strategies.ml import model_dense_scores as fixture

Path("dense.json").write_bytes(fixture.ARTIFACT_BYTES)
Path("dense-metadata.json").write_text(json.dumps({
    "training_snapshot_id": fixture.TRAINING_SNAPSHOT_ID,
    "training_as_of": fixture.TRAINING_AS_OF, "code_hash": None,
    "hyperparameters": fixture.HYPERPARAMETERS, "seed": None,
    "eval_report": fixture.EVAL_REPORT,
}))
```

```sh
uv run algua model register model_dense_scores --artifact dense.json --metadata dense-metadata.json
uv run algua backtest run model_dense_scores --snapshot EXISTING_BARS_SNAPSHOT \
  --start 2023-01-03 --end 2023-03-01
```

Use an immutable stored bars snapshot covering the three configured symbols and requested period;
context scoring refuses unpinned `--demo` input. The tests ingest explicitly synthetic bars.
The existing loader verifies the exact version/bytes/provenance; canonical context validation,
five-bar warmup and `t→t+1` execution remain in force. This dense fixture remains unsupported for context paper/live and
model-backed walk-forward/sweeps. This demonstrates executable DL inference on fixtures,
not a trained DL producer, real multimodal evidence, predictive quality or trading qualification.

## Frozen pinned-model planner profile

Artifact preparation can package the offline `price-linear/v1` producer into a new version-2
frozen descriptor: daily bars, `context_v1`, one explicit `ModelRef`, no news or fundamentals.
The bundle contains `_algua/model/artifact.json` (64 KiB maximum) and canonical portable
`_algua/model/provenance.json` (1 MiB maximum), with full SHA-256 digests in addition to the
existing registry pins. The provenance omits the machine-local artifact path. Model reads require
regular bounded files and refuse symlinks through the asset path. Serving reads the verified
bundle, without accessing the model registry or training.

Descriptor, boundary, planner and wire versions are all 2 for this profile; existing version-1
artifacts, hashes and request/result bytes retain their meanings. Requests bind the exact bars
snapshot, model pin, interface and protocol across both phases; model bytes stay in the bundle.
The child uses the same context composition, scorer, construction, overlays and intent builder
as research. For a single paper decision its first evaluated cutoff is that decision, rather
than the beginning of warmup history. A future-trained pin is refused before a warming result.
The decision lag remains at least one bar.

**Owner-approved reviewed-code paper execution (2026-11-08).** The owner explicitly waived the
extra model-only isolation prerequisite. Verified model-paper intake and ticks use the same
reviewed-code trust model as existing strategies; no production bypass flag or fixture policy
patch is needed. This is unsandboxed execution: authored imports during artifact preparation run
in the operator process, and process containment does not deny filesystem/network/credential
access or guarantee removal of escaped descendants. Only human-reviewed first-party strategy
code belongs on this path. Model/bundle/PIT/config checks, current research and forward gates,
supervisor risk checks and signed live activation remain binding.

This waiver is not an `authoritative_strategy_execution` isolation assessment and cannot satisfy
verified-PR admission's separate Task4 attestation. Working-tree model trading and frozen live
execution retain their existing refusals. Real elapsed paper sessions and economic eligibility
must still be established; fixture success is not qualification or deployment acceptance.


## Fixed pre-period price-linear research

Walk-forward and sweeps admit only the supported bars-only `context_v1` price-linear profile with
one verified explicit model pin whose training cutoff is no later than the entire evaluation
start. Every fold and parameter combination reuses that pin; no rolling fitting or model search
is added. Invalid/future profiles refuse before data access or holdout reservation. Results and
the run ledger preserve the exact five-field model reference; holdout measurements remain private
until the existing promotion burn.

## Five-session experimental qualification

`uv run algua paper qualify-experimental NAME` previews current historical eligibility plus five
contiguous completed exchange sessions for the active frozen deployment. Actual non-overridden
scheduled paper runs record per-tenant observations; `operator run --now`, historical replay and
synthetic fixtures cannot provide elapsed operational sessions through this hook. Each observation
requires a fresh successful frozen invocation, reconciled broker-clocked tick and exact artifact,
account and snapshot identity. Sibling failures do not erase successful tenants' observations.
Paper Sharpe is not retested by this profile.

`--actor` is a reported author label only: it supplies no authority and no signature is involved
(the signed `--actor human` path was removed, spec 2026-11-13). The record is append-only and separate from strict forward certificates: it does
not advance the strategy stage or authorize live execution. Capped frozen-live execution and the
new layered drawdown controller remain separate implementation work.
