import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { clearFetchCache } from '../api'
import { resolveFixture } from '../fixtures'
import type {
  ApiEnvelope,
  RunDetail,
  RunSeriesPayload,
  RunsListPayload,
  SeriesPayload,
  SeriesRow,
  StrategyDetailResponse,
} from '../types'
import StrategyDetail from './StrategyDetail'

const detail: StrategyDetailResponse = {
  ok: true,
  strategy: 'mom_breakout',
  registry: {
    id: 1,
    name: 'mom_breakout',
    stage: 'backtested',
    family: 'momentum',
    tags: ['trend'],
    author: 'agent',
    hypothesis_status: 'untested',
    derived_from: null,
    description: 'breakout over rolling high',
    transitions: [
      {
        id: 1,
        from_stage: 'idea',
        to_stage: 'backtested',
        actor: 'agent',
        reason: 'walk-forward complete',
        created_at: '2026-08-01T12:00:00+00:00',
      },
    ],
  },
  // A null part = REAL backend failure — the page must degrade, not crash.
  paper: null,
  gates: {
    strategy: 'mom_breakout',
    gate_evaluations: [
      {
        id: 7,
        passed: 0,
        actor: 'agent',
        created_at: '2026-08-02T15:00:00+00:00',
        fdr_p_value: 0.04,
        fdr_alpha_level: 0.00764,
        decision: {
          passed: false,
          dsr_confidence: 0.91,
          checks: [
            { name: 'holdout_sharpe', op: '>=', threshold: 0.62, value: 0.31, passed: false },
          ],
        },
        decision_dropped_keys: [],
      },
    ],
    forward_gate_evaluations: [],
  },
  part_errors: { paper: 'cli_failed' },
  fetched_at: '2026-08-09T14:30:00Z',
  stale: false,
}

const seriesEnvelope: ApiEnvelope<SeriesPayload> = {
  ok: true,
  fetched_at: '2026-08-09T14:30:00Z',
  stale: false,
  data: {
    strategy: 'mom_breakout',
    lane_filter: null,
    series: { paper: [], live: null },
    truncated: { paper: false, live: null },
    n_legacy_excluded: 0,
    n_unparseable: 0,
    n_invalid_lane: 0,
  },
}

// The gate bullet card (task 5) is fed `checks` directly from `detail.gates.gate_evaluations[0]
// .decision` (fix round 2 — no fetch of its own; see `GateBulletCard.tsx`'s docstring). Only
// `TrialDistribution` (task 6) still does the `/api/runs?...&kind=gate&limit=1` ->
// `/api/runs/{id}` two-step waterfall, for the deflation strip and the trial cloud's own marker
// — these two fixtures exist for THAT fetch. Same `holdout_sharpe` check value as
// `detail.gates.gate_evaluations[0].decision` so the two views agree, per both docstrings.
const runsListEnvelope: ApiEnvelope<RunsListPayload> = {
  ok: true,
  fetched_at: '2026-08-09T14:30:00Z',
  stale: false,
  data: {
    count: 1,
    runs: [
      {
        id: 70,
        kind: 'gate',
        strategy_name: 'mom_breakout',
        strategy_id: 1,
        created_at: '2026-08-02T15:00:00+00:00',
        passed: 0,
        mean_window_sharpe: null,
        sharpe_oos: null,
      },
    ],
  },
}

const runDetailEnvelope: ApiEnvelope<RunDetail> = {
  ok: true,
  fetched_at: '2026-08-09T14:30:00Z',
  stale: false,
  data: {
    id: 70,
    kind: 'gate',
    strategy_name: 'mom_breakout',
    strategy_id: 1,
    created_at: '2026-08-02T15:00:00+00:00',
    passed: 0,
    mean_window_sharpe: null,
    sharpe_oos: null,
    extra_metrics: {},
    gate_decision: {
      passed: false,
      dsr_confidence: 0.91,
      checks: [
        { name: 'holdout_sharpe', op: '>=', threshold: 0.62, value: 0.31, passed: false },
      ],
    },
  },
}

// ReturnOverlay (task 7) also queries `/api/runs?...&kind=backtest` and batches its ids through
// `/api/runs/series` — no backtest/holdout series is fixtured here, so this stays an empty
// envelope; the overlay just renders its own honest empty state, same as the equity chart above.
const runSeriesEnvelope: ApiEnvelope<RunSeriesPayload> = {
  ok: true,
  fetched_at: '2026-08-09T14:30:00Z',
  stale: false,
  data: { series: {} },
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

it('renders the degraded paper banner and the rest of the page when paper is null', async () => {
  let failDetailRefresh = false
  let failSeriesRefresh = false
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      const strategySeries = url.endsWith('/series') && !url.startsWith('/api/runs/series')
      const strategyDetail = url.startsWith('/api/strategy/') && !strategySeries
      if ((strategySeries && failSeriesRefresh) || (strategyDetail && failDetailRefresh)) {
        return { ok: false, status: 503, json: async () => ({ error: 'refresh offline' }) }
      }
      return {
        ok: true,
        status: 200,
        json: async () => {
        // Registered before the `/api/runs?` and `/api/runs/{id}` checks below — its own path
        // segment ("series") would otherwise fall through to neither and hit the `detail`
        // catch-all, handing ReturnOverlay a StrategyDetailResponse where it expects
        // `{series: {...}}` (mirrors web/backend/main.py's own route-registration-order note).
        if (url.startsWith('/api/runs/series')) return runSeriesEnvelope
        if (strategySeries) return seriesEnvelope
        if (/^\/api\/runs\/\d+$/.test(url)) return runDetailEnvelope
        if (url.startsWith('/api/runs?')) return runsListEnvelope
          return detail
        },
      }
    }) as unknown as typeof fetch,
  )

  render(
    <MemoryRouter initialEntries={['/s/mom_breakout']}>
      <Routes>
        <Route path="/s/:name" element={<StrategyDetail />} />
      </Routes>
    </MemoryRouter>,
  )

  expect(await screen.findByText('mom_breakout')).toBeTruthy()
  expect(screen.getByText('breakout over rolling high')).toBeTruthy()

  fireEvent.click(screen.getByRole('button', { name: /performance evidence/i }))
  // degraded-part evidence carries the part_errors code
  expect(await screen.findByText('cli_failed')).toBeTruthy()
  expect(screen.getByText('paper state')).toBeTruthy()
  expect(screen.getByText(/no tick history recorded/i)).toBeTruthy()

  fireEvent.click(screen.getByRole('button', { name: /raw provenance/i }))
  expect(screen.getByText('idea → backtested')).toBeTruthy()
  const ordersStatus = screen.getByText('recent orders').closest('[data-state]')
  expect(ordersStatus?.getAttribute('data-state')).toBe('failed')
  expect(ordersStatus?.textContent).toContain('cli_failed')
  fireEvent.click(screen.getByRole('button', { name: /research evidence/i }))
  // The gate bullet card's checks come straight from the already-fetched composite response
  // (fix round 2 — no fetch of its own), so this is available as soon as the page renders.
  expect(await screen.findByText('holdout_sharpe')).toBeTruthy()
  expect(screen.getAllByText('fail').length).toBeGreaterThanOrEqual(2) // verdict + check row
  // empty series -> compact genuine-empty status, no false chart
  expect(screen.getByText(/no tick history recorded/i)).toBeTruthy()

  failDetailRefresh = true
  document.dispatchEvent(new Event('visibilitychange'))
  await waitFor(() => expect(screen.getByText(/cached .*last error refresh offline/i)).toBeTruthy())

  failDetailRefresh = false
  failSeriesRefresh = true
  document.dispatchEvent(new Event('visibilitychange'))
  await waitFor(() => expect(screen.getByText(/cached tick history is empty/i)).toBeTruthy())
})

// The runs-ledger-empty regression (fix round 2) lives in its own file
// (`StrategyDetail.emptyruns.test.tsx`): the funnel-wide `/api/runs?kind=sweep_trial...` URL is
// never `strategy=`-scoped, and this file's first test above already populates that URL's
// module-level fetch cache with a non-empty response — a second, empty-runs fixture for the SAME
// URL in this file would silently read back the FIRST test's cached response (the precedent
// `TrialDistribution.render.test.tsx`'s header comment documents).

// ---- Task 7: the new top (curve, expected line, metrics, next-gate card) ----

/** `n` weekday ticks from 2026-10-05 rising linearly from 1550 to `end`. */
function paperRows(n: number, end: number): SeriesRow[] {
  const out: SeriesRow[] = []
  const d = new Date('2026-10-05T20:00:00Z')
  while (out.length < n) {
    if (d.getUTCDay() !== 0 && d.getUTCDay() !== 6) {
      const i = out.length
      out.push({ id: i, tick_ts: d.toISOString(), recorded_at: d.toISOString(),
        equity: 1550 + ((end - 1550) * i) / Math.max(n - 1, 1), peak_equity: null, reconcile_ok: true })
    }
    d.setUTCDate(d.getUTCDate() + 1)
  }
  return out
}

function paperDetail(gateExtra: Record<string, unknown>): StrategyDetailResponse {
  return {
    ...detail,
    strategy: 'dual_test',
    paper: null,
    part_errors: {},
    registry: { ...detail.registry!, name: 'dual_test', stage: 'paper', transitions: [
      { from_stage: 'candidate', to_stage: 'paper', actor: 'agent', reason: null,
        created_at: '2026-10-03T12:00:00+00:00' },
    ] },
    gates: { strategy: 'dual_test', forward_gate_evaluations: [], gate_evaluations: [
      // The newest row failed: the line must come from the newest PASSING row.
      { id: 9, passed: 0, actor: 'agent', created_at: '2026-10-02T00:00:00+00:00',
        decision: { passed: false }, sharpe_oos: 0.2, total_return_oos: 0.5, n_obs_oos: 100 },
      { id: 8, passed: 1, actor: 'agent', created_at: '2026-10-01T00:00:00+00:00',
        decision: { passed: true }, ...gateExtra },
    ] },
  }
}

function stubDetail(body: StrategyDetailResponse, rowsForPaper: SeriesRow[]) {
  clearFetchCache()
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const json = url.endsWith('/series') && url.startsWith('/api/strategy/')
      ? { ...seriesEnvelope, data: { ...seriesEnvelope.data, strategy: body.strategy,
        series: { paper: rowsForPaper, live: null } } }
      : url.startsWith('/api/strategy/') ? body
        : url.startsWith('/api/runs/series') ? runSeriesEnvelope
          : /^\/api\/runs\/\d+$/.test(url) ? runDetailEnvelope
            : url.startsWith('/api/runs?') ? runsListEnvelope : undefined
    return json === undefined
      ? { ok: false, status: 404, json: async () => ({ error: 'not fixtured' }) }
      : { ok: true, status: 200, json: async () => json }
  }) as unknown as typeof fetch)
}

function mountDetail(name: string) {
  return render(
    <MemoryRouter initialEntries={[`/s/${name}`]}>
      <Routes><Route path="/s/:name" element={<StrategyDetail />} /></Routes>
    </MemoryRouter>,
  )
}

it('StrategyDetail draws expected line from passing gate', async () => {
  stubDetail(paperDetail({ sharpe_oos: 1.65, total_return_oos: 0.254, n_obs_oos: 252 }),
    paperRows(42, 1584.1))
  const { container } = mountDetail('dual_test')
  await screen.findByText('$1,584.10')
  expect(screen.getByText(/since paper · Oct 3/)).toBeTruthy()
  const line = await waitFor(() => {
    const el = container.querySelector('[data-testid="expected-line"]')
    expect(el).not.toBeNull()
    return el!
  })
  // daily = 1.254^(1/252) - 1, compounded from the first point (1550) over 41 steps.
  const daily = Math.pow(1.254, 1 / 252) - 1
  expect(Number(line.getAttribute('data-end'))).toBeCloseTo(1550 * Math.pow(1 + daily, 41), 1)
  expect(line.querySelector('svg')?.getAttribute('data-points')).toBe('42')
  expect(screen.getByText('Backtest expectation')).toBeTruthy()
  expect(screen.getByText('Backtest 1.65')).toBeTruthy()
  for (const r of ['1W', '1M', 'Since paper', 'Backtest']) {
    expect(screen.getByRole('button', { name: r })).toBeTruthy()
  }
})

it('StrategyDetail hides expected line when gate fields missing', async () => {
  stubDetail(paperDetail({}), paperRows(42, 1584.1))
  const { container } = mountDetail('dual_test')
  await screen.findByText('$1,584.10')
  expect(container.querySelector('[data-testid="expected-line"]')).toBeNull()
  expect(screen.queryByText('Backtest expectation')).toBeNull()
  expect((screen.getByRole('button', { name: 'Backtest' }) as HTMLButtonElement).disabled).toBe(true)
})

it('StrategyDetail with no ticks shows "No ticks yet"', async () => {
  stubDetail(paperDetail({ sharpe_oos: 1.65, total_return_oos: 0.254, n_obs_oos: 252 }), [])
  const { container } = mountDetail('dual_test')
  expect(await screen.findByText('No ticks yet')).toBeTruthy()
  expect(container.querySelector('[data-testid="expected-line"]')).toBeNull()
  expect(screen.getByTestId('gate-card').textContent).toContain('0 of 63 sessions')
})

it('gate card shows 41 of 63 sessions from fixture', async () => {
  clearFetchCache()
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const json = resolveFixture(url)
    return json === undefined
      ? { ok: false, status: 404, json: async () => ({ error: 'not fixtured' }) }
      : { ok: true, status: 200, json: async () => json }
  }) as unknown as typeof fetch)
  mountDetail('dual_horizon_skip_month')
  const card = await screen.findByTestId('gate-card')
  await waitFor(() => expect(card.textContent).toContain('41 of 63 sessions'))
  expect(card.textContent).toContain('Forward gate')
  // No recorded evaluation this paper stint: an estimate, labelled as such, with the lower
  // bound as its own row.
  expect(card.getAttribute('data-kind')).toBe('estimate')
  expect(card.textContent).toContain('Estimate from ticks — not the gate')
  const labels = within(card).getAllByTestId('gate-check').map((c) => c.textContent ?? '')
  expect(labels.length).toBe(4)
  expect(labels.some((l) => l.startsWith('Sharpe 95% lower bound at least'))).toBe(true)
})

/** Falling ticks: a recomputation would fail every check the recorded pass cleared. */
function fallingRows(n: number): SeriesRow[] {
  return paperRows(n, 1550).map((r, i) => ({ ...r, equity: 1550 * (1 - 0.004 * i) + (i % 2) * 3 }))
}

function forwardTestedDetail(): StrategyDetailResponse {
  const base = paperDetail({ sharpe_oos: 1.65, total_return_oos: 0.254, n_obs_oos: 252 })
  return {
    ...base,
    registry: { ...base.registry!, stage: 'forward_tested', transitions: [
      ...base.registry!.transitions,
      { from_stage: 'paper', to_stage: 'forward_tested', actor: 'agent', reason: null,
        created_at: '2026-12-31T12:00:00+00:00' },
    ] },
    gates: { ...base.gates!, forward_gate_evaluations: [{
      id: 50, passed: 1, actor: 'agent', created_at: '2026-12-31T12:00:00+00:00', consumed: 1,
      n_forward_observations: 64, min_forward_observations: 63, max_forward_drawdown: 0.25,
      decision: { passed: true, checks: [
        { name: 'min_forward_observations', op: '>=', threshold: 63, value: 64, passed: true },
        { name: 'realized_sharpe', op: '>=', threshold: 0.83, value: 1.12, passed: true },
        { name: 'realized_sharpe_lcb', op: '>=', threshold: 0.83, value: 0.9, passed: true },
        { name: 'max_forward_drawdown', op: '<=', threshold: 0.25, value: 0.034, passed: true },
        { name: 'session_coverage', op: '>=', threshold: 0.9, value: 0.98, passed: true },
        { name: 'reconcile_ok', passed: true },
        { name: 'single_account', passed: true },
      ] },
    }] },
  }
}

it('forward_tested renders the recorded evaluation, not a recomputation from ticks', async () => {
  stubDetail(forwardTestedDetail(), fallingRows(65))
  mountDetail('dual_test')
  const card = await screen.findByTestId('gate-card')
  expect(card.getAttribute('data-kind')).toBe('recorded')
  expect(card.textContent).toContain('Passed · 64 of 63 sessions')
  expect(card.textContent).toContain('as of Dec 31')
  const rows = within(card).getAllByTestId('gate-check')
  expect(rows.map((r) => r.getAttribute('data-pass'))).not.toContain('false')
  const text = rows.map((r) => r.textContent).join('|')
  expect(text).toContain('Sharpe at least 0.831.12')
  expect(text).toContain('Sharpe 95% lower bound at least 0.830.90')
  expect(text).toContain('Integrity and account checks2 of 2')
  expect(card.textContent).not.toContain('Estimate from ticks')
})

it('paper with only an earlier-stint evaluation shows the estimate, at default thresholds', async () => {
  const d = forwardTestedDetail()
  const old = { ...d.gates!.forward_gate_evaluations[0], created_at: '2026-09-01T00:00:00+00:00',
    max_forward_drawdown: 0.4 }
  stubDetail({ ...paperDetail({ sharpe_oos: 1.65, total_return_oos: 0.254, n_obs_oos: 252 }),
    gates: { ...d.gates!, forward_gate_evaluations: [old] } }, paperRows(42, 1584.1))
  mountDetail('dual_test')
  const card = await screen.findByTestId('gate-card')
  await waitFor(() => expect(card.textContent).toContain('Estimate from ticks — not the gate'))
  expect(card.textContent).toContain('Drawdown under 25%')
})

it('a non-operating strategy draws no chart box', async () => {
  stubDetail({ ...paperDetail({}), registry: { ...paperDetail({}).registry!, stage: 'candidate' } }, [])
  const { container } = mountDetail('dual_test')
  await screen.findByText('dual_test')
  expect(container.querySelector('.sd-chart')).toBeNull()
  expect(screen.queryByText('No ticks yet')).toBeNull()
  expect(screen.queryByTestId('gate-card')).toBeNull()
})
