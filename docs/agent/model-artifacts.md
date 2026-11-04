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
