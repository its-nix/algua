# VPS research-only operations

Status (2026-11-05): the three research timers are enabled. The startup timer fired at
10:59 UTC and launched the worker as `algua`; that run's outcome remains separately recorded.
Research scheduling does not establish full-goal, verified-PIT, paper or live acceptance.

## Installed profile

Only `algua-{research,forage,leap}.{service,timer}` are in scope: three root-managed pairs.
Services run as `algua:algua`, HOME `/home/algua`, in `/home/algua/Projects/algua`.
They load `/home/algua/.config/algua/research.env` (owner algua, mode 0600).
PATH starts with `/usr/local/libexec/algua` for the admitted private bwrap, then the user's
`.local/bin` and `.opencode/bin`; the selected OpenCode version is 1.19.5.
Broker credential variables remain scrubbed; no auth-store or credential changes are implied.

Each job: 4 GiB physical-memory cap, zero swap, 16 GiB virtual address-space allowance,
CPU limit 1200 seconds and `TimeoutStartSec=25min`. All three share `algua-research.slice`,
which caps combined memory at 6 GiB with zero swap.
Research gets 20 minutes, one hypothesis and one worker. Forage/leap get 15 minutes and
at most three notes/ideas respectively. These limits do not imply a monetary-cost cap.
The private environment's research settings are memory 16384 MB (virtual AS, not RSS),
CPU 1200 seconds, one hypothesis and one worker. `MLFLOW_DISABLE_TELEMETRY=true`
disables anonymous usage telemetry, not experiment tracking.

Registry: `/home/algua/Projects/algua/data/algua.db`; knowledge: checkout `kb/`;
tracking: checkout `mlruns.db` and `mlruns.artifacts/` (configured prefix `mlruns`);
pinned pilot data: `/home/algua/datasets/pilot-2026-11-03/data`.
Preserve these stores, retained research branches and runtime archives during maintenance.

## Cadence

| Timer | UTC schedule |
|---|---|
| Research | 00:00, 06:00, 12:00, 18:00; also `OnActiveSec=1min` after timer activation |
| Forage | Daily 03:00 |
| Leap | Every two hours at :30; pool-depth gated |

`Persistent=true` is retained. Missed firings may catch up together; each driver's own
nonblocking lock prevents same-driver overlap, not overlap between stages. The shared slice
bounds their combined memory. Enabling research can start a job after one minute.

## Operate from the existing admin SSH session

Use explicit unit names; never enable paper, live or merge-back drainer units as part of this profile.

```bash
systemctl list-timers --all algua-research.timer algua-forage.timer algua-leap.timer
systemctl status algua-research.service algua-forage.service algua-leap.service algua-research.slice --no-pager
journalctl -u algua-research.service -u algua-forage.service -u algua-leap.service -n 80 --no-pager
# Enable only these research timers:
systemctl enable --now algua-research.timer algua-forage.timer algua-leap.timer
# One manual research firing (the unit still runs as algua):
systemctl start algua-research.service
# Stop future firings; this does not stop an already active job:
systemctl disable --now algua-research.timer algua-forage.timer algua-leap.timer
# Separately interrupt only active research-stage jobs:
systemctl stop algua-research.service algua-forage.service algua-leap.service
```

Keep journals and application logs private; do not dump environment or auth-file contents.
After a checkpointed worker timeout/interruption, the supervisor kills/reaps its worker tree,
then allows at most 120 seconds of trusted evidence capture and claim closure. It never resumes
inference, accepts late success or rewrites terminal outcomes. Failed capture retains scratch.
After an interruption, inspect the durable cycle result and claim state; use the existing
fenced CLI for any needed reconciliation, never SQL resets or reopening refuted ideas.

## Interpret results and data limits

A completed runtime can still yield a nonzero research/service exit for qualification refusal.
Check `$ALGUA_DATA_DIR/research-cycles/<cycle>.result.json` and the
retained public memory, not the service exit alone. Actual numerical rows and a durable outcome
are required to count an empirical cycle. A missing evaluation is not a negative economic result.
Timeout, setup failure, provider error and native-worker crash remain infrastructure failures.

The pilot is `pilot_real_proxy`, not verified PIT. Preserve all seven limitations:
vendor-revisable adjusted prices, unverified corporate actions, missing delisted symbols,
unavailable event knowledge times, unavailable historical market cap, unavailable PIT membership
and survivorship bias. Pin actual snapshot, dates, configuration and seed; never fall back to demo.
Labelled proxy backtests/WF/sweeps are permitted; they do not establish an investable edge.
Strict promotion/live floors remain unchanged: no fabricated PIT data, relaxation flags or
proxy `merge_back`. Missing genuine input modalities remain missing; preserve failed evidence.
