# Unattended research-cycle acceptance — 2026-11-05

The owner's amended threshold is **three completed empirical unattended research
cycles**, reduced from ten on 2026-11-05. It is met. Other Algua 2.0 acceptance
requirements are unchanged; this record does not declare the overall goal complete.

## Executed cycles

Each counted cycle delegated authoring and independent interpretation to OpenCode,
ran real numerical CLI evaluations against the pinned yfinance pilot, wrote a report,
closed its controller ledger, and retained a verified public experiment archive.
The first three were explicitly seeded bootstrap replications, not novel ideas.

| Cycle | Idea | Evaluation records | Mean research-window Sharpe | Retained strategy commit |
|---|---|---:|---:|---|
| `20261105-090929-472a636f9fd6` | Low-volatility replication | 5 | -0.1340 | `278c6939699d8bda26d27741787ceb561d85c0be` |
| `20261105-094443-c21530cb7897` | Trend/pullback replication | 5 | -0.9242 | `429c8bdb1d1310ca21bad18ff446e970981624d1` |
| `20261105-100046-9f1486b788e7` | Prior-high replication | 5 | -0.4519 | `613d6c3da3241080e2c705220765923d61c781b0` |
| `20261105-105903-161f8bd083ed` | Turnover-instability/session reversal | 7 | -0.3730 | `ee0265cda4dcdb9dee18b71bfc8e5afca3d08711` |

The fourth cycle is additional operation, not a higher threshold. Corrected forage
and leap generated its open idea autonomously. The installed persistent
`algua-research.timer` launched it at 10:59:03 UTC; it finished at approximately
11:10:20 UTC. The service ran as the dedicated `algua` user, peaking at about
1.2 GiB resident memory with no swap, within its 4 GiB physical limit and shared
6 GiB research slice. Its fixed three-mode sweep evaluated the hypothesis and two
predeclared controls. Common-invested-date control excess was not measured.

There were **12 research attempts: four completed empirical cycles and eight
excluded attempts**. Exclusions include setup/runtime failures, incomplete empirical
work, timeouts and optional public-memory admission failures. Some excluded attempts
produced numerical records; those records do not turn an incomplete cycle into a
completed one. The first three cycles each have two backtests (author smoke plus
registered evaluation), one walk-forward, one sweep and one singleton trial. These
are five records across four kinds, not five independent hypotheses. The fourth has three sweep
trials, hence seven records. No count here replaces the separate 100-configuration
[real-data benchmark](real-sweep-benchmark.md).

## Durable evidence and outcome

Verified public archive references, in table order:

- `mlflow:d794d7d8ef53438f9f3e188e338da1ff/public-evidence.json#sha256=a57dfe724d4083dd73fa366d719c517c858647d015e20c2516e808aa6c8ecac9`
- `mlflow:2d195855cdd64b7c9b68787ee66697bb/public-evidence.json#sha256=90b97128f09aacb3ee3b85e47831cc223a674b1a8002356ea411f8b513d021e7`
- `mlflow:a77dcea3303641329050e212345b4c0a/public-evidence.json#sha256=524c792afa183236e7dfa2a0245aa4a8549d8f760b6d11b624a55f0354d8acfe`
- `mlflow:74907724994e4cd2af0b376fba5fa10d/public-evidence.json#sha256=9ce5b95914cf0efc101edac2f6f5da7b8d4253d05859e48d085f9bdc230c0f3c`

Each controller result has phase `completed`, one terminal attempt, zero unfinished
attempts, and no write errors. Worker exit was zero; the driver/service exit was
one because qualification remained `integrity_fail`. No promotion gate was invoked,
no candidate was created, and no merge-back or paper/live deployment was requested.
The archives remain unverified-worker evidence with authority `none`; successful
archive readback does not certify evaluated-worktree identity or grant gate authority.

A separate offline CLI replay of the fourth cycle's full-period backtest from retained commit
`ee0265c` matched all seven archived in-sample scalars bit-for-bit on snapshot `61a2bda1e636d017`,
with the same config, dependency hash and null seed. Total return was -0.13557876252529666 and
Sharpe -0.25787427365969706. This one reproduction is not another hypothesis or unattended cycle;
it does not reproduce walk-forward/sweep results or prove the original evaluated worktree identity.
All pilot limitations remain.

New digest rows distinguish worker execution from qualification using the raw worker exit and
complete controller facts. A completed worker-zero `integrity_fail` can retain sanitized negative
feedback without a worker-crash alert; final driver/service exit stays one and merge-back remains
ineligible. Existing digest rows and their incident lineage are not rewritten or cleared.

All cycles used snapshot `61a2bda1e636d017`, logical content hash
`e63c513cf2b5820d0ef468de7c22e8ab53552a07c1f81a1b625c7849ac1dc550`,
with 150 current selected US equity names and approximately two years of daily bars.
All seven limitations remain: vendor-revisable adjusted prices, unverified corporate
actions, absent delisted names, unavailable event knowledge times, unavailable
historical market capitalization, unavailable point-in-time universe membership,
and survivorship-biased selection. Previously examined research windows are not
untouched out-of-sample evidence. Costs and next-bar execution stayed enabled.

## Operational handoff and remaining limits

The [VPS runbook](../../deploy/systemd/research-vps.md) records the existing systemd
research/forage/leap deployment, resource bounds and scoped stop commands. Those
three timers are enabled; no paper, live, web or merge-back-drainer service was
activated by this profile. The fourth cycle evaluated source `21641aba`; only the
runbook documentation merge `109a029` was pulled after it became terminal.

This milestone proves empirical cycle completion, retained negative results and one
actual persistent-timer run from autonomous ideation. It does not yet prove cumulative
learning. The successful optional chooser consumed structured scorecard history (seven attempts,
four families and one negative-result entry); its explanation cited excluded prior attempts.
It had one offered option and unavailable numerical archive context, so this does not demonstrate
competitive selection, archive-metric learning or economic improvement. The original optional-memory
admission failure has no established cause. Isolated nonempty memory fixtures passed, which is
narrower evidence. Real sidecar-data acceptance,
complete multimodal execution evidence, protected isolation/dashboard assessments,
and verified paper deployment remain separately open. Missing paper credentials and
saved-policy assessment denials are not waived by reducing the cycle threshold.
