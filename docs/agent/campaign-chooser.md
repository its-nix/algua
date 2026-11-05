# Opt-in constrained campaign choice

`research idea cycle-start --run RUN --limit N --choose --choice-dir NEW_PRIVATE_DIR`
captures the existing deterministic menu, asks the output-only chooser once, validates the reply,
and passes that selection to the existing controller and attempt CAS. The caller must hold the
existing research-loop lock. This command claims selected ideas; it does not launch strategy work.
The research driver accepts an explicit `--choose-campaign` opt-in:

```sh
.opencode/scripts/run-research-loop.sh --choose-campaign --hypotheses 3
```

It passes `--choose --choice-dir <data_dir>/research-cycles/<cycle_id>.choice` to the existing
`cycle-start` command while holding its existing research-loop lock. The directory is private and
must be new; reusing a cycle never spends another chooser call or claims replacement work. The
controller's returned campaign determines fenced digest/queue publication. Provider failures,
invalid choices or changed feedback stop the cycle without falling back to legacy selection.
For a fresh mutating chooser start, the complete request and unused cycle/private directory are
checked before reconciling older interrupted controller cycles through their existing fenced
outcomes. Memory capture and menu construction follow that recovery, so it cannot invalidate the
new choice's feedback. Failed recovery stops before archive/model work or new claims. Read-only
menus and supplied manual campaigns keep their existing behavior and stale-feedback checks.
`--choose-campaign` and `--campaign FILE` are mutually exclusive. Supplied campaign files,
`--menu-only` and legacy callers retain their existing channels. There is no automatic chooser
default, schedule change or additional initiator. Capture, choice, claims and terminal outcomes
remain separate evidence.

The chooser is configured in `.opencode/opencode.json` and launched only by
`.opencode/scripts/run_agent.sh`. Its effective primary-agent configuration must expose zero tools,
with wildcard denial and one step. Missing or incompatible configuration fails before the model
call. The seam requests JSON events and an explicit title, then exports the same session with the
installed runtime's `--sanitize` option. This configuration is a functional output-only boundary,
not a strategy sandbox or Task4 security assessment. Existing sandbox selection is preserved;
a containment failure is terminal and must not be worked around by changing permissions.

The producer accepts at most 96 KiB of prompt, 256 KiB per event/log file and 32 KiB of selection
text. Model wall time is at most 120 seconds (or the smaller captured wall limit), with at most
15 seconds each for configuration inspection and session export, plus 5 seconds for cleanup.
CPU and address-space limits tighten the captured resources; the process-wide file limit uses the
captured `file_mb` budget so native state may exceed 8 MiB. Independent prompt, output and reply
bounds above remain unchanged. These are process limits, not strategy isolation. No model
call or claim is allowed with a configured monetary cap while cost is UNKNOWN, even a zero cap.
Reported runtime costs do not establish an authoritative monetary accounting source.

The reply must be exactly `{menu_id, choices}`. Every choice must have exactly `category`,
`hypothesis_id`, `reason`, `prior_evidence_ids`, and `budget`. The existing `selection_ids`
validator checks all five fields against the captured menu; reasons must be nonblank and at most
2,000 characters. Empty choices, duplicate JSON fields, extra fields, nonfinite values, tools,
error events, partial/truncated steps, mismatched sessions and feedback/context drift refuse.
There is no substitute top pick or fabricated explanation. Fresh feedback is checked after the
call and the existing claim transaction rechecks it under its write lock. A used cycle ID refuses
a second chooser call; reconcile through the existing controller rather than spending again.

The private directory must be new. It keeps `menu.json`, `prompt.txt`, raw `runtime.jsonl` and
`runtime.jsonl.stderr`, `effective-agent.json`, sanitized `session.json`, actual session/model
identity in `runtime-evidence.json`, exit status, and an accepted `campaign.json`. Files may
exist for failed calls, but there are no claims or controller records for rejected output.
Failed cycle starts also emit a small driver diagnostic with a fixed phase, recognized code,
typed retry flag and fixed error text (including a chooser exit status when available). Captured
claims, free-form exception messages and native login/session contents are never echoed there.
Keep the directory private: prompts contain registry metadata and paths. Runtime state/cache and
native refresh state stay under it. The seam reads the existing native login store into inherited
process memory when needed, without changing the original store or printing credentials. Treat
native runtime data as private login/session state; never publish it or cache directories.

The coordinator's private `two_synthetic_choices.py` helper creates a disposable fixture registry,
performs exactly two chooser invocations, finishes only their selected claims using explicitly
trusted synthetic outcome reports, and independently reads back the persisted ledger and context.
Author verification substitutes a fake runtime executable. Real synthetic choices remain pending
until the coordinator runs the helper. Neither chooser calls nor controlled terminal fixtures are
research cycles/trials, Task4/Task10 acceptance, market evidence, PIT, alpha or qualification.
