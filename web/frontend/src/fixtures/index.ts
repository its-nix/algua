/** URL -> fixture payload. Deliberately a MAP with an explicit unknown-URL miss rather than a
 * catch-all: a screen that calls an endpoint nobody fixtured must fail loudly in the demo
 * build (see `transport.ts`), not render a plausible-looking empty state that hides the gap. */
import {
  ACTIVITY,
  BOARD,
  BOOK,
  FETCHED_AT,
  FIXTURE_SENTINEL,
  FLEET,
  IDEAS,
  LEGACY_BOARD,
  OPERATIONAL_STAGES,
  OPS,
  RUNS,
  SEEDS,
  STRATEGIES,
  TRIAGE,
  envelope,
  rng,
  type Seed,
} from './steady-state'
import { equityFixture } from './equity'
import { INBOX } from './inbox'
import { forwardRowFor, seriesRowsFor, stageAnchors } from './strategySeries'
import type {
  GateCheck,
  GateDecision,
  GateRow,
  GatesPayload,
  PaperRollup,
  RecentOrder,
  RegistryDetail,
  RunDetail,
  RunSeriesPayload,
  SeriesPayload,
  StrategyDetailResponse,
  Transition,
} from '../types'

export { FIXTURE_SENTINEL }

// Demo-only schema parity: existing synthetic gates supply no ordinary public-window records.
// Preserve those gate rows separately, rather than inventing public statistics or lineage.
const PUBLIC_BOARD = {
  ...BOARD,
  data: { ...BOARD.data, evidence_schema_version: 'strategy-board-research/v2' as const,
    rows: BOARD.data.rows.map(row => ({ ...row, latest_research: null,
      evidence: null, recorded_provenance: null })) },
}

/** Lifecycle order (algua/contracts/lifecycle.py), used to reconstruct a plausible transition
 * history and gate-history depth for any seed on demand. */
const LIFECYCLE_ORDER = ['idea', 'backtested', 'candidate', 'paper', 'forward_tested', 'live']

const STAGE_GAP_DAYS: Record<string, number> = {
  idea: 4, backtested: 6, candidate: 15, paper: 26, forward_tested: 11, live: 1, dormant: 30,
}

const STAGE_REASON: Record<string, string> = {
  idea: 'sourced from the idea pool',
  backtested: 'strategy module authored and backtested',
  candidate: 'research promote passed the integrity floor',
  paper: 'paper intake allocated a book slice',
  forward_tested: 'paper promote passed the forward-evidence gate',
  live: 'go-live approved on a fresh forward certificate',
  dormant: 'benched pending a universe refresh',
}

function addDays(iso: string, days: number): string {
  const d = new Date(iso)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().replace(/\.\d{3}Z$/, '+00:00')
}

/** Walks the lifecycle backward from `FETCHED_AT` so the CURRENT stage lands closest to "now"
 * and earlier stages land progressively further in the past — byte-stable, no `Date.now()`. */
function transitionsFor(seed: Seed): Transition[] {
  const idx = LIFECYCLE_ORDER.indexOf(seed.stage)
  const path = idx === -1 ? ['idea'] : LIFECYCLE_ORDER.slice(0, idx + 1)
  if (seed.stage === 'dormant') path.push('dormant')
  const newestFirst = [...path].reverse()
  // A seed with drawn tick history enters its lane on its first tick's session.
  const anchors = stageAnchors(seed)
  let ts = FETCHED_AT
  const dated = newestFirst.map((stage) => {
    const at = anchors[stage] ?? ts
    ts = addDays(at, -(STAGE_GAP_DAYS[stage] ?? 7))
    return { stage, at }
  })
  const chronological = [...dated].reverse()
  return chronological.map(
    (d, i): Transition => ({
      from_stage: i === 0 ? null : chronological[i - 1].stage,
      to_stage: d.stage,
      actor: d.stage === 'live' ? 'human' : 'agent',
      reason: STAGE_REASON[d.stage] ?? null,
      created_at: d.at,
    }),
  )
}

function registryDetailFor(seed: Seed): RegistryDetail {
  return {
    id: seed.id,
    name: seed.name,
    stage: seed.stage,
    family: seed.family,
    tags: seed.tags,
    author: 'agent',
    hypothesis_status: seed.hypothesisStatus,
    derived_from: seed.derivedFrom,
    description: seed.description,
    transitions: transitionsFor(seed),
  }
}

const SYMBOLS = ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'META', 'GOOGL', 'AVGO', 'COST', 'ADBE', 'LIN']

function recentOrdersFor(seed: Seed): RecentOrder[] {
  if (seed.capital <= 0) return []
  const a = SYMBOLS[seed.id % SYMBOLS.length]
  const b = SYMBOLS[(seed.id + 3) % SYMBOLS.length]
  return [
    { symbol: a, side: 'buy', status: 'filled', broker_order_id: `ord_${seed.id}01`, submitted_ts: FETCHED_AT },
    {
      symbol: b, side: 'sell', status: 'filled',
      broker_order_id: `ord_${seed.id}00`, submitted_ts: addDays(FETCHED_AT, -1),
    },
  ]
}

/** `/api/fleet` now carries a row for EVERY registry strategy (fleet_status() emits one per
 * strategy, not just the ticked ones), so a row existing is no longer proof an operator loop
 * watches it — gate explicitly on `OPERATIONAL_STAGES` and reuse the row for the fields that
 * do apply, rather than re-deriving health/drawdown a second time. */
function paperRollupFor(seed: Seed): PaperRollup | null {
  if (!OPERATIONAL_STAGES.includes(seed.stage)) return null
  const row = FLEET.data.rows.find((r) => r.strategy === seed.name)
  if (row === undefined) return null
  return {
    strategy: row.strategy,
    stage: row.stage,
    health: row.health,
    staleness_sessions: row.staleness_sessions,
    stale_after_sessions: FLEET.data.stale_after_sessions,
    last_tick_error: row.last_tick_error,
    kill_switch: row.kill_switch,
    drawdown: row.drawdown,
    last_tick: row.positions !== null && row.positions > 0 ? { tick_ts: FETCHED_AT, reconcile_ok: true } : null,
    positions: row.positions,
    n_orders: row.n_orders,
    recent_orders: recentOrdersFor(seed),
  }
}

function buildGateCheck(
  name: string,
  threshold: number,
  value: number,
  opts?: { advisory?: boolean },
): GateCheck {
  return {
    name,
    op: '>',
    threshold,
    value: Number(value.toFixed(4)),
    passed: value > threshold,
    advisory: opts?.advisory ?? false,
  }
}

/** A dormant seed in this fixture was benched from the PAPER lane (never reached
 * forward_tested) — treat it as ranked at 'paper' for gate-history depth purposes. */
function stageRank(stage: string): number {
  if (stage === 'dormant') return LIFECYCLE_ORDER.indexOf('paper')
  return LIFECYCLE_ORDER.indexOf(stage)
}

function buildGateRow(seed: Seed, id: number, kind: 'research' | 'forward'): GateRow {
  const r = rng(seed.id * 7919 + (kind === 'research' ? 1 : 2))
  const holdoutSharpe = 0.15 + r() * 0.7
  // Drawn ONCE and reused below for both the bullet-card check's value and the ledger's
  // `dsr_confidence` scalar — they name the SAME quantity (research/gates.py never computes DSR
  // confidence twice), so two independent `r()` calls previously showed the gate card and the
  // ledger disagreeing (0.8482 vs 0.8931) on one number for the same run.
  const dsrConfidence = kind === 'research' ? Number((0.6 + r() * 0.35).toFixed(4)) : null
  // Drawn in the same order as before (the observations check came next), so earlier values hold.
  const holdoutObs = kind === 'research' ? 90 + r() * 400 : 0
  const checks: GateCheck[] =
    kind === 'research'
      ? [
          { name: 'pit_universe', passed: true },
          buildGateCheck('holdout_observations', 63, holdoutObs),
          buildGateCheck('holdout_sharpe_floor', 0, holdoutSharpe),
          buildGateCheck('dsr_confidence', 0.9, dsrConfidence as number, { advisory: true }),
        ]
      : [
          buildGateCheck('forward_sharpe_floor', holdoutSharpe * 0.5, holdoutSharpe * (0.6 + r() * 0.6)),
          buildGateCheck('sessions_observed', 63, 63 + r() * 60),
          { name: 'account_hygiene', passed: true },
        ]
  const decision: GateDecision = {
    passed: checks.every((c) => c.advisory === true || c.passed !== false),
    checks,
    dsr_confidence: dsrConfidence ?? undefined,
    appraisal_ratio: Number((0.8 + r() * 0.9).toFixed(4)),
  }
  return {
    id,
    passed: decision.passed === true,
    actor: 'agent',
    created_at: FETCHED_AT,
    consumed: true,
    decision,
    fdr_p_value: null,
    fdr_alpha_level: null,
    // `registry gates` research rows carry the holdout record the expected line compounds:
    // a 12% annualized vol, so the return follows the Sharpe over the holdout's length.
    ...(kind === 'research' ? {
      sharpe_oos: Number(holdoutSharpe.toFixed(4)),
      total_return_oos: Number((Math.pow(1 + holdoutSharpe * 0.12, holdoutObs / 252) - 1).toFixed(4)),
      n_obs_oos: Math.round(holdoutObs),
    } : {}),
  }
}

/** Only strategies at `candidate` or beyond have cleared the research gate at all; only
 * `forward_tested`/`live` (or a dormant seed benched from paper — see `stageRank`) have
 * attempted the forward gate too. */
function gatesFor(seed: Seed): GatesPayload | null {
  const rank = stageRank(seed.stage)
  if (rank === -1 || rank < LIFECYCLE_ORDER.indexOf('candidate')) return null
  const reachedForward = rank >= LIFECYCLE_ORDER.indexOf('forward_tested')
  const research = buildGateRow(seed, 1000 + seed.id * 10, 'research')
  return {
    strategy: seed.name,
    gate_evaluations: [research],
    forward_gate_evaluations: reachedForward
      ? [forwardRowFor(seed, 1000 + seed.id * 10 + 1, Number(research.sharpe_oos))] : [],
  }
}

function strategyDetail(name: string): StrategyDetailResponse {
  const seed = SEEDS.find((s) => s.name === name) ?? SEEDS[0]
  return {
    ok: true,
    strategy: seed.name,
    registry: registryDetailFor(seed),
    paper: paperRollupFor(seed),
    gates: gatesFor(seed),
    gates_limit: 20,
    fetched_at: FETCHED_AT,
    stale: false,
  }
}

function seriesFor(name: string): SeriesPayload {
  const seed = SEEDS.find((s) => s.name === name)
  const hasSlice = seed !== undefined && seed.capital > 0
  const rowsForLane = hasSlice ? seriesRowsFor(seed) : []
  const isLive = seed?.stage === 'live'
  return {
    strategy: name,
    lane_filter: null,
    series: {
      paper: hasSlice && !isLive ? rowsForLane : hasSlice ? [] : null,
      live: hasSlice && isLive ? rowsForLane : null,
    },
    truncated: { paper: false, live: false },
    n_legacy_excluded: 0,
    n_unparseable: 0,
    n_invalid_lane: 0,
  }
}

export function resolveFixture(url: string): unknown | undefined {
  const path = url.split('?')[0]

  switch (path) {
    case '/api/research-memory': return envelope({
      schema_version: 'retained-research-index/v1', metadata_verified: false,
      evidence_mode: 'UNVERIFIED_WORKER', authority: 'none', association: 'cycle_only',
      count: 0, has_more: false, limit: 20, attempts: [],
    })
    case '/api/triage':      return TRIAGE
    case '/api/fleet':       return FLEET
    case '/api/book':        return BOOK
    case '/api/ops':         return OPS
    case '/api/ideas':       return IDEAS
    case '/api/strategies':  return STRATEGIES
    case '/api/runs':        return RUNS
    case '/api/strategy-board': {
      const params = new URLSearchParams(url.split('?')[1] ?? '')
      return params.get('research') === 'true' ? PUBLIC_BOARD :
        params.get('include_evidence') === 'true' ? BOARD : LEGACY_BOARD
    }
    case '/api/activity':    return ACTIVITY
    // The run-ledger series endpoint deliberately never returns a per-bar OOS vector
    // (holdout_returns.returns_blob is SENSITIVE) — an empty series map is the honest fixture.
    case '/api/runs/series': return envelope<RunSeriesPayload>({ series: {} })
    case '/api/push/key':    return { key: null }
    case '/api/equity':      return equityFixture(url)
    case '/api/inbox':       return INBOX
    // Fixture-only: no screen ever fetches this. The dist guard only needs FIXTURE_SENTINEL
    // present somewhere in the bundle, not inside a payload a real screen renders — parking it
    // in, say, a fleet row's `last_tick_error` would eventually print debug text on-screen.
    case '/api/__demo':      return { fixture: FIXTURE_SENTINEL }
  }

  const series = path.match(/^\/api\/strategy\/([^/]+)\/series$/)
  if (series) return envelope(seriesFor(decodeURIComponent(series[1])))

  const strategy = path.match(/^\/api\/strategy\/([^/]+)$/)
  if (strategy) return strategyDetail(decodeURIComponent(strategy[1]))

  const runId = path.match(/^\/api\/runs\/(\d+)$/)
  if (runId) {
    const run = RUNS.data.runs.find((r) => r.id === Number(runId[1])) ?? RUNS.data.runs[0]
    // Every RUNS row is `kind: 'gate'` — the gate bullet card (one of the five headline views)
    // reads its checks from HERE (RunDetail.gate_decision), never from StrategyDetailResponse.
    // Reuse the same research-gate builder as the strategy-detail composite so the two agree,
    // and so the card's binding/advisory split (a failed advisory check inside a passing gate
    // must never look like a breached binding floor) actually has something to render.
    const seed = SEEDS.find((s) => s.id === run.strategy_id)
    const gateDecision = seed !== undefined ? buildGateRow(seed, run.id, 'research').decision : null
    return envelope<RunDetail>({ ...run, extra_metrics: {}, gate_decision: gateDecision })
  }

  return undefined
}
