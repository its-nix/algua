# Research lifecycle — the canonical command sequence

This describes research commands through **candidate**, then the separate operational path toward
paper and forward qualification. Isolated research workers stop at `candidate`; trusted drivers
and operational commands own subsequent steps. Every data command emits JSON on stdout.
`tests/test_e2e_lifecycle.py` exercises lifecycle controls using synthetic fixtures and signed test
ceremonies; those fixtures are not an autonomous economic-qualification recipe.

Stages: `idea -> backtested -> candidate -> paper -> forward_tested -> live -> retired`
(allowed edges live in `algua/contracts/lifecycle.py`). An agent may operate the lifecycle
**up to and including `forward_tested`**. The `forward_tested -> live` transition is a hard wall —
it requires a human actor, a verified approval, AND a fresh forward-test certificate, enforced in
`algua/registry/store/` and `algua/registry/transitions.py`.

Before using these templates, set `SNAPSHOT_ID`, `UNIVERSE`, `START` and `END` to the assigned
real bars snapshot, PIT universe and evaluation interval. Keep them identical across commands.
Missing PIT eligibility or insufficient evidence is a valid refusal; do not fabricate it.
`--demo` is for explicitly requested synthetic smoke tests, not economic qualification.

## 1. Backtest and register (`idea -> backtested`)

A single backtest that also registers the strategy and advances it to `backtested`:

```bash
uv run algua backtest run cross_sectional_momentum \
  --snapshot "$SNAPSHOT_ID" --universe "$UNIVERSE" \
  --start "$START" --end "$END" --register
```

`--register` is what advances the stage; without it the run is exploratory and the registry is
untouched. Add `--track` to log the run to MLflow.

Confirm the stage:

```bash
uv run algua registry show cross_sectional_momentum   # -> "stage": "backtested"
```

## 2. Out-of-sample evidence (still `backtested`)

These do **not** change the stage — they generate the evidence the gate will judge.

Walk-forward (holdout + K equal out-of-sample windows + stability):

```bash
uv run algua backtest walk-forward cross_sectional_momentum \
  --snapshot "$SNAPSHOT_ID" --universe "$UNIVERSE" \
  --start "$START" --end "$END" --windows 4 --holdout-frac 0.2
```

Run a bounded parameter sweep to record the measured breadth required by agent promotion.
Use a predeclared grid within the assigned budget; a singleton trial can record breadth but does
not demonstrate parameter robustness. Breadth-deflated statistics remain advisory:

```bash
uv run algua backtest sweep cross_sectional_momentum \
  --snapshot "$SNAPSHOT_ID" --universe "$UNIVERSE" \
  --start "$START" --end "$END" \
  --param lookback=20,40,60 --param construction.top_k=3,5 --rank-by mean_sharpe
```

## 3. Promotion gate (`backtested -> candidate`)

`research promote` runs the walk-forward, evaluates the gate, and transitions the strategy to
`candidate` **only on pass**. On failure it reports why and leaves the stage untouched.

```bash
uv run algua research promote cross_sectional_momentum \
  --snapshot "$SNAPSHOT_ID" --universe "$UNIVERSE" \
  --start "$START" --end "$END"
```

- Agents use measured sweep breadth; `--n-combos` is an authenticated human-only declaration.
- PIT coverage, minimum holdout observations and positive raw holdout Sharpe are binding alongside
  preflight integrity checks. The statistical stack is advisory; FDR has no veto or throttle.
- Raw `registry transition --to candidate` is refused for every actor. Use `research promote`.

Output carries `passed`, `promoted`, the per-check breakdown, the config hash, and the snapshot
id. After a pass, `registry show` reports `"stage": "candidate"`.

## 4. Toward paper (`candidate -> paper`)

The isolated research worker stops here and writes its report for the trusted driver. Eligible
merge-backs are queued for the trusted drainer, which runs authoritative promotion and intake.
Outside that worker role, an authorized operational caller can run paper intake:

```bash
uv run algua paper intake
```

Intake considers eligible candidates in FIFO order, verifies/prepares frozen planner content,
and binds paper admission to a deployment and allocation under book limits. It can leave a
candidate queued or refuse unsupported content. A raw stage transition does not perform this
operational preparation and is not a substitute. Paper credentials and a reachable venue are required.

## 5. Forward-test gate (`paper -> forward_tested`)

An operational agent advances from `paper` to `forward_tested` only via `paper promote`;
this command is outside the isolated research worker's role:

```bash
uv run algua paper promote cross_sectional_momentum
# -> {"ok": true, "passed": true, "promoted": true, ...} on pass
# -> {"ok": false, "passed": false, ...} on fail — stage stays at paper
```

The gate requires ≥63 broker-clocked daily return observations, ≥90% session coverage, realized
Sharpe ≥ max(0.5 × holdout_sharpe, 0.3), vol/drawdown bounds, clean integrity, and account
hygiene. Evidence must be ≤5 trading sessions stale. Relaxation flags are human-only.

The adopted short-paper experimental-delivery target in PRD §16 awaits protected implementation;
it does not replace these executable requirements yet. Frozen live activation remains unsupported.

Re-running `paper promote` on a strategy already at `forward_tested` refreshes the live-wall
certificate without a stage change (exit 0 on pass).

## 6. The live wall (`forward_tested -> live`) — human only

An agent **cannot** put a strategy live. This fails as JSON with a non-zero exit, and the stage
stays at `forward_tested`:

```bash
uv run algua registry transition cross_sectional_momentum --to live --actor agent
# -> {"ok": false, "error": ...}, exit 1
```

Going live is a two-step signed ceremony requiring a human actor AND a valid forward-test
certificate:

**Step 1** — get the go-live challenge (includes certificate summary):

```bash
uv run algua registry transition cross_sectional_momentum --to live --actor human
# -> {"ok": true, "action": "go_live_challenge", "challenge": "...", "certificate": {...}, ...}
```

**Step 2** — sign the challenge and re-run:

```bash
echo '<challenge value>' > challenge.txt
ssh-keygen -Y sign -n algua-go-live -f ~/.ssh/id_ed25519 challenge.txt
uv run algua registry transition cross_sectional_momentum --to live \
  --actor human --signature challenge.txt.sig
# -> {"ok": true, "stage": "live"}
```

The challenge is single-use and expires in 10 minutes. The forward certificate must be a PASS,
≤10 sessions old, with a clean record and matching identity. This is the boundary the system
enforces and an agent must never try to route around.
