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
five-bar warmup and `t→t+1` execution remain in force. Context paper/live and model-backed
walk-forward/sweeps remain refused. This demonstrates executable DL inference on fixtures,
not a trained DL producer, real multimodal evidence, predictive quality or trading qualification.
