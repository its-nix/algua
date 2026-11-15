import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { clearFetchCache } from '../api'
import { parseEvidence } from '../components/StrategyBoard'
import Research from './Research'

function renderExpanded() {
  const view = render(<MemoryRouter><Research /></MemoryRouter>)
  const disclosure = view.container.querySelector<HTMLDetailsElement>('.research-diagnostics')!
  disclosure.open = true
  fireEvent(disclosure, new Event('toggle'))
  return view
}

const strategies = {
  ok: true,
  fetched_at: '2026-08-15T17:04:00Z',
  stale: false,
  data: {
    data: [
      { id: 1, name: 'live_one', stage: 'paper', family: 'momentum', tags: [], author: 'agent',
        hypothesis_status: 'untested', derived_from: null, description: null },
      { id: 2, name: 'benched', stage: 'retired', family: null, tags: [], author: 'agent',
        hypothesis_status: 'refuted', derived_from: null, description: null },
    ],
  },
}

const runs = {
  ok: true,
  fetched_at: '2026-08-15T17:04:00Z',
  stale: false,
  data: { count: 0, runs: [] },
}

const board = {
  ok: true,
  fetched_at: '2026-08-15T17:04:00Z',
  stale: false,
  data: {
    schema_version: 'strategy-board/v1',
    count: 2,
    rows: [
      { strategy_id: 1, name: 'live_one', family: 'momentum', stage: 'paper',
        latest_gate: { run_id: 7, created_at: '2026-08-14T00:00:00+00:00', passed: true,
                       sharpe_oos: 0.8, total_return_oos: 0.1, max_drawdown_oos: -0.05,
                       n_obs_oos: 126, mean_window_sharpe: 0.7, min_window_sharpe: 0.2,
                       pct_positive_windows: 0.75 } },
      { strategy_id: 2, name: 'benched', family: null, stage: 'retired', latest_gate: null },
    ],
  },
}

function routeBody(url: string) {
  return url.startsWith('/api/strategy-board')
    ? board
    : url.startsWith('/api/strategies')
      ? strategies
      : url.startsWith('/api/runs')
        ? runs
        : url.startsWith('/api/ops')
          ? ops
          : ideas
}

const ops = {
  ok: false,
  fetched_at: '2026-08-15T17:04:00Z',
  stale: false,
  data: {
    ok: false,
    checked_at: '2026-08-15T17:04:00Z',
    alerting: ['research'],
    loops: {
      research: { health: 'rate_limited', detail: 'provider usage limit reached',
                  last_ok_at: '2026-08-14T14:00:01+00:00', consecutive_failures: 13 },
      mergeback: { health: 'stale', queue_depth: 23 },
    },
  },
}

const ideas = {
  ok: true,
  ideas: [
    { id: 1, title: 'skip-month persistence', hypothesis: 'Returns persist after the skip month.', family: null, tags: [],
      source_type: 'paper', source_ref: null, source_date: null, status: 'open',
      created_at: '2026-08-10T00:00:00+00:00' },
  ],
  stats: { window_days: 90, counts: { open: 1, authored: 0, total: 1 } },
  stats_window_days: 90,
  depth: {
    open_unclaimed: 10, claimed: 2, needs_data: 1, refill_at: 72, ceiling: 252,
    below_refill: false,
    inputs: { runs_per_day: 12, hypotheses_per_run: 3, floor_days: 2, ceiling_days: 7 },
  },
  scorecard: {
    days: 90, min_n_for_rates: 5,
    by_venue: {
      arxiv: { n: 12, outcomes: {}, stages: {}, survivals: 3,
                integrity_yield: 0.6, walkforward_yield: 0.5, survival_yield: 0.25 },
      forums: { n: 2, outcomes: {}, stages: {}, survivals: 0,
                integrity_yield: null, walkforward_yield: null, survival_yield: null },
    },
    by_category: {}, by_obscurity: {}, by_inspiration: {},
  },
  fetched_at: '2026-08-15T17:04:00Z',
  stale: false,
}

afterEach(() => {
  cleanup()
  clearFetchCache()
  vi.unstubAllGlobals()
})

function renderResearch() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => ({
      ok: true, status: 200, json: async () => routeBody(url),
    })) as unknown as typeof fetch,
  )
  return renderExpanded()
}

function renderResearchWithOps(opsResponse: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => ({
      ok: true,
      status: 200,
      json: async () => url.startsWith('/api/ops') ? opsResponse : routeBody(url),
    })) as unknown as typeof fetch,
  )
  return renderExpanded()
}

it('shows loading rather than inventing a blocked decision before required reads finish', () => {
  vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => {})) as unknown as typeof fetch)
  const { container } = renderExpanded()
  expect(container.querySelector('.decision-state')?.textContent).toBe('loading')
  expect(screen.getByText(/no current decision yet/i)).toBeTruthy()
  const inventory = screen.getByRole('region', { name: /lifecycle inventory/i })
  expect(within(inventory).getByTestId('evidence-status').getAttribute('data-state')).toBe('loading')
  expect(within(inventory).queryByText(/no strategies registered/i)).toBeNull()
})

it('labels an empty cached registry response as stale rather than authoritative empty inventory', async () => {
  const staleEmptyStrategies = {
    ...strategies,
    stale: true,
    data: { data: [] },
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => ({
      ok: true,
      status: 200,
      json: async () => url.startsWith('/api/strategies') ? staleEmptyStrategies : routeBody(url),
    })) as unknown as typeof fetch,
  )
  renderExpanded()
  const inventory = await screen.findByRole('region', { name: /lifecycle inventory/i })
  const status = within(inventory).getByTestId('evidence-status')
  expect(status.getAttribute('data-state')).toBe('stale')
  expect(status.textContent).toMatch(/cached.*no strategies/i)
})

it('encodes lifecycle counts proportionally without inflating small stages to a false minimum', async () => {
  const skewed = {
    ...strategies,
    data: {
      data: [
        { ...strategies.data.data[0], id: 1, stage: 'paper' },
        ...Array.from({ length: 99 }, (_, index) => ({
          ...strategies.data.data[1], id: index + 2, name: `retired_${index}`, stage: 'retired',
        })),
      ],
    },
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => ({
      ok: true,
      status: 200,
      json: async () => url.startsWith('/api/strategies') ? skewed : routeBody(url),
    })) as unknown as typeof fetch,
  )
  const view = renderExpanded()
  await screen.findByRole('region', { name: /lifecycle inventory/i })
  const widths = [...view.container.querySelectorAll<HTMLElement>('.funnel-track span')]
    .map((node) => node.style.width)

  expect(widths).toEqual(['1.0101010101010102%', '100%'])
})

it('surfaces a stopped research loop — the difference between "no ideas" and "none ever again"', async () => {
  renderResearch()
  expect(await screen.findByRole('heading', { name: /research decision/i })).toBeTruthy()
  expect(screen.getByText(/^blocked$/i)).toBeTruthy()
  expect(screen.getByText(/new evidence may not arrive/i)).toBeTruthy()
  expect(screen.getByText(/next clean research loop run/i)).toBeTruthy()
  expect(await screen.findByText('research loop')).toBeTruthy()
  expect(screen.getByText(/provider usage limit reached/)).toBeTruthy()
  expect(screen.getByText(/13 consecutive failed runs/)).toBeTruthy()
})

it('reports a wedged merge-back queue', async () => {
  renderResearch()
  expect(await screen.findByText(/merge-back queue 23 is wedged/i)).toBeTruthy()
})

it.each([
  ['absent', undefined],
  ['unknown', { health: 'mystery', queue_depth: 0 }],
])('blocks when merge-back state is %s', async (_label, mergeback) => {
  renderResearchWithOps({
    ...ops,
    data: {
      ...ops.data,
      alerting: [],
      loops: {
        research: { health: 'ok', detail: 'idle', last_ok_at: '2026-08-15T17:00:00Z', consecutive_failures: 0 },
        ...(mergeback === undefined ? {} : { mergeback }),
      },
    },
  })
  expect(await screen.findByText(/^blocked$/i)).toBeTruthy()
  expect(screen.getByText(/merge-back.*(?:absent|mystery)/i)).toBeTruthy()
})

it('qualifies a blocked loop conclusion when operations came from stale cache', async () => {
  renderResearchWithOps({ ...ops, stale: true })
  expect(await screen.findByText(/^blocked$/i)).toBeTruthy()
  expect(screen.getByText(/operations evidence is stale.*cached research loop/i)).toBeTruthy()
})

it('keeps the funnel count strip separate from the board filters', async () => {
  const { container } = renderResearch()
  await screen.findByRole('heading', { name: 'strategy board' })
  expect(screen.getByLabelText('paper: 1 strategies').closest('button')).toBeNull()
  expect(screen.getByLabelText('retired: 1 strategies').closest('button')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: /board controls/i }))
  expect(screen.getByRole('button', { name: /^paper 1$/ })).toBeTruthy()
  expect(screen.getByRole('button', { name: /^retired 1$/ })).toBeTruthy()
  expect(screen.getByRole('heading', { name: /lifecycle inventory/i })).toBeTruthy()
  expect(container.querySelector('[aria-label="strategy inventory"]')).toBeTruthy()
  expect(container.querySelectorAll('.funnel-track')).toHaveLength(2)
})

it('wires in the IS-vs-OOS scatter and the strategy board, not the ranked run list', async () => {
  renderResearch()
  expect(await screen.findByText('is vs oos')).toBeTruthy()
  expect(await screen.findByRole('heading', { name: 'strategy board' })).toBeTruthy()
  expect(screen.queryByText('ranked runs')).toBeNull()
  // One row per registered strategy — including the one with no gate evidence.
  const boardRows = screen.getAllByTestId('board-row')
  expect(boardRows).toHaveLength(2)
  expect(within(boardRows[1]).getByText(/^no usable gate evidence$/i)).toBeTruthy()
})

it('absorbs the idea pool, keeping the windowed stats on their own line', async () => {
  renderResearch()
  expect(await screen.findByText('idea pool')).toBeTruthy()
  const idea = screen.getByRole('button', { name: /skip-month persistence/i })
  expect(idea.getAttribute('aria-expanded')).toBe('false')
  expect(screen.queryByText('Returns persist after the skip month.')).toBeNull()
  fireEvent.click(idea)
  expect(idea.getAttribute('aria-expanded')).toBe('true')
  expect(screen.getByText('Returns persist after the skip month.')).toBeTruthy()
  expect(screen.getByText(/last 90d: open 1/)).toBeTruthy()
})

it('shows pool depth above the tiles and yield-by-venue after the list', async () => {
  renderResearch()
  expect(await screen.findByText(/10 open.*refill at 72/)).toBeTruthy()
  expect(screen.queryByRole('table')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: /yield by venue/i }))
  expect(screen.getByRole('table')).toBeTruthy()
  expect(screen.getByText('arxiv')).toBeTruthy()
  expect(screen.getByText('forums')).toBeTruthy()
  expect(screen.getByText('60.0%')).toBeTruthy()  // arxiv integrity_yield
  const dashCells = screen.getAllByText('--')
  expect(dashCells.length).toBeGreaterThan(0)  // forums' null rates render as --
})

// Schema-shaped UI controls only; these values are not market evidence or executed gates.
const context = {
  schema_version: 'research-comparison/v1', protocol: 'continuous_portfolio_tail_holdout',
  metrics: 'net_daily_returns_252_rf0_ddof1_compounded_floored_drawdown/v1',
  timeframe: '1d', period_start: '2024-01-01', period_end: '2024-12-31',
  holdout_frac: 0.2, embargo: 20,
  windows: [{ start: '2024-01-02', end: '2024-05-01', n_bars: 90 },
    { start: '2024-05-02', end: '2024-09-01', n_bars: 90 }],
  oos: { start: '2024-10-01', end: '2024-12-30', n_bars: 50 },
  execution: { schema_version: 'replay-execution/v1', decision_lag_bars: 1,
    fill_basis: 'adjusted_close', valuation_basis: 'adjusted_close', sizing: 'targetpercent', cash_sharing: true,
    initial_cash: 100, symbol_order: ['AAPL', 'MSFT'], rebalance: 'every_daily_bar',
    price_units: 'vendor_adjusted', simulation: {
      fixed_fees: 0, min_size: 1e-8, max_size: '+inf', size_granularity: 'nan', reject_prob: 0,
      lock_cash: false, allow_partial: true, raise_reject: false, log: false, price: '+inf',
      val_price: '+inf', call_seq: 'default', ffill_val_price: true, update_value: false, seed: null,
      fillna_close: true, direction: 'both', freq: '1D', group_by: true, engine: 'numba',
      initial_cash_mode: 'fixed', vectorbt_version: '1.0.0',
    } },
  execution_costs: { schema_version: 'execution-costs/v1', model: 'vectorbt.from_orders',
    fees: 0.0005, fees_unit: 'fraction_of_trade_notional_per_side', slippage: 0,
    slippage_unit: 'adverse_fill_price_fraction_per_side' },
  snapshot_id: 'recorded-snapshot', content_hash: 'b'.repeat(64), data_tier: 'pilot_real_proxy',
  dependency_hash: 'recorded-dependencies',
  source: { schema_version: 'pilot-provenance/v1', data_tier: 'pilot_real_proxy',
    universe_method: 'current_survivors', coverage_start: '2024-01-02', coverage_end: '2024-12-30',
    provider: 'yfinance', limitations: ['adjusted_close_vendor_revisable', 'corporate_actions_unverified',
      'delisted_names_absent', 'event_timing_unavailable', 'historical_market_cap_unavailable',
      'point_in_time_universe_unavailable', 'survivorship_biased_selection'] },
}

function scatterRow(id: number, sharpe: number | null, cohort = 'a'.repeat(64)) {
  return { strategy_id: id, name: `strategy_${id}`, family: 'momentum', stage: id === 4 ? 'live' : 'backtested',
    latest_gate: { run_id: id + 100, created_at: '2026-01-01T00:00:00Z', passed: false,
      sharpe_oos: sharpe, total_return_oos: 0, max_drawdown_oos: -0.1, n_obs_oos: 50,
      mean_window_sharpe: 99, min_window_sharpe: -5, pct_positive_windows: 0.5 },
    recorded_provenance: { status: 'VALID', reason: null, value: {
      bars_snapshot_id: context.snapshot_id, bars_content_hash: context.content_hash,
      execution_costs: structuredClone(context.execution_costs),
    } },
    evidence: { run_id: id + 100,
      evaluation: { status: 'VALID', reason: null, value: { period_start: '2024-01-01',
        period_end: '2024-12-31', timeframe: '1d', metric_schema_version: 1 } },
      oos_interval: { status: 'VALID', reason: null, value: {
        holdout_start: '2024-10-01', holdout_end: '2024-12-30', n_bars: 50 } },
      snapshot_provenance: { status: 'VALID', reason: null, value: structuredClone(context.source) },
      comparison: { status: 'COMPARABLE', observed_metric_sort_enabled: true,
        reasons: [], cohort_id: cohort, context: structuredClone(context) } } }
}


function syntheticScatterRow(id: number) {
  const r = scatterRow(id, 1234, 'b'.repeat(64))
  const source = { ...r.evidence.snapshot_provenance.value, data_tier: 'synthetic_fixture',
    provider: 'fixture', universe_method: 'synthetic/v1', limitations: ['synthetic_not_market_data'] }
  Object.assign(r.evidence.snapshot_provenance.value, source)
  Object.assign(r.evidence.comparison.context, { data_tier: 'synthetic_fixture', source })
  return r
}

function renderScatterResearch(rows: ReturnType<typeof scatterRow>[], options: {
  evidence?: unknown
  raw?: Record<string, unknown>[]
} = {}) {
  const gateBoard = { ...board, data: { schema_version: 'strategy-board/v1',
    evidence_schema_version: 'strategy-board-evidence/v2', count: rows.length, rows } }
  const publicBoard = { ...gateBoard, data: { ...gateBoard.data,
    evidence_schema_version: 'strategy-board-research/v2', rows: rows.map(row => ({ ...row,
      latest_research: null, evidence: null, recorded_provenance: null })) } }
  const raw = options.raw ?? rows.map(r => ({
    id: r.latest_gate.run_id, strategy_id: r.strategy_id, strategy_name: r.name,
    kind: 'gate', created_at: r.latest_gate.created_at, passed: false,
    mean_window_sharpe: r.latest_gate.mean_window_sharpe, sharpe_oos: r.latest_gate.sharpe_oos,
    // Arbitrary raw metadata claims never establish the data tier for the chart.
    config_json: { data_tier: 'pilot_real_proxy' },
  }))
  const fetchMock = vi.fn(async (url: string) => ({ ok: true, status: 200,
    json: async () => url === '/api/strategy-board?include_evidence=true' ? options.evidence ?? gateBoard :
      url.startsWith('/api/strategy-board') ? publicBoard :
        url.startsWith('/api/runs') ? { ...runs, data: { count: raw.length, runs: raw } } : routeBody(url),
  }))
  vi.stubGlobal('fetch', fetchMock as unknown as typeof fetch)
  renderExpanded()
  return fetchMock
}

it('R1 excludes default synthetic scatter points even when raw metadata claims real proxy', async () => {
  const fixture = syntheticScatterRow(71)
  expect(parseEvidence(fixture.evidence, fixture.latest_gate, fixture.recorded_provenance)?.comparison.status).toBe('COMPARABLE')
  const fetchMock = renderScatterResearch([fixture])
  await screen.findByRole('heading', { name: 'strategy board' })
  expect(screen.queryAllByTestId('scatter-point')).toHaveLength(0)
  expect(screen.getByText(/in-sample.*selection.*pre-holdout windows, not independent OOS/i)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Gate OOS' }))
  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url === '/api/strategy-board?include_evidence=true')).toBe(true))
  fireEvent.click(await screen.findByRole('button', { name: /board controls/i }))
  fireEvent.change(screen.getByRole('combobox', { name: 'data tier' }), { target: { value: 'synthetic_fixture' } })
  expect(screen.getByRole('link', { name: /View strategy_71 strategy details/i })).toBeTruthy()
  expect(screen.queryAllByTestId('scatter-point')).toHaveLength(0)
})

it('R1 separates mixed tiers in Research while retaining real observed zero and negative points', async () => {
  const real = [scatterRow(61, 0), scatterRow(62, -0.5)]
  const fixture = syntheticScatterRow(71)
  for (const row of [...real, fixture]) {
    expect(parseEvidence(row.evidence, row.latest_gate, row.recorded_provenance)?.comparison.status).toBe('COMPARABLE')
  }
  const fetchMock = renderScatterResearch([...real, fixture])
  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url === '/api/strategy-board?include_evidence=true')).toBe(true))
  await waitFor(() => expect(screen.getAllByTestId('scatter-point')).toHaveLength(2))
  expect(screen.getByRole('img', { name: /in-sample versus out-of-sample Sharpe scatter/i })).toBeTruthy()
  expect(screen.queryByText('1234.00')).toBeNull()
})

it.each(['missing', 'unknown', 'malformed', 'cost', 'stale', 'unsupported_schema', 'wrong_strategy', 'wrong_run', 'metric_drift', 'cohort_conflict'])
('R1 omits raw chart observations with %s comparison evidence', async damage => {
  const real = scatterRow(61, 0)
  const other = scatterRow(62, -0.5)
  const payload = { ...board, data: { schema_version: 'strategy-board/v1',
    evidence_schema_version: 'strategy-board-evidence/v2', count: 2, rows: [real, other] } }
  const raw = [real, other].map(r => ({ id: r.latest_gate.run_id, kind: 'gate',
    strategy_id: r.strategy_id, strategy_name: r.name, created_at: r.latest_gate.created_at,
    passed: false, mean_window_sharpe: r.latest_gate.mean_window_sharpe, sharpe_oos: r.latest_gate.sharpe_oos,
    config_json: { data_tier: 'pilot_real_proxy' } }))
  if (damage === 'missing') Reflect.deleteProperty(real, 'evidence')
  if (damage === 'unknown') Object.assign(real.evidence.comparison, { status: 'UNKNOWN',
    observed_metric_sort_enabled: false, reasons: ['comparison_context_absent'], cohort_id: null, context: null })
  if (damage === 'malformed') Object.assign(real.evidence.comparison.context, { future: true })
  if (damage === 'cost') real.recorded_provenance.value.execution_costs.fees = 0.9
  if (damage === 'stale') payload.stale = true
  if (damage === 'unsupported_schema') payload.data.evidence_schema_version = 'strategy-board-evidence/future'
  if (damage === 'wrong_strategy') raw[0].strategy_id = 999
  if (damage === 'wrong_run') raw[0].id = 999
  if (damage === 'metric_drift') raw[0].sharpe_oos = 999
  if (damage === 'cohort_conflict') {
    real.evidence.comparison.context.execution_costs.fees = 0.9
    real.recorded_provenance.value.execution_costs.fees = 0.9
  }
  const fetchMock = renderScatterResearch([real, other], { evidence: payload, raw })
  await screen.findByRole('heading', { name: 'strategy board' })
  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url === '/api/strategy-board?include_evidence=true')).toBe(true))
  await waitFor(() => expect(screen.queryAllByTestId('scatter-point')).toHaveLength(
    ['stale', 'unsupported_schema', 'cohort_conflict'].includes(damage) ? 0 : 1))
})


it('opens on results and defers diagnostic API reads until requested', async () => {
  const fetch = vi.fn(async (url: string) => ({
    ok: true, status: 200, json: async () => routeBody(url),
  }))
  vi.stubGlobal('fetch', fetch)
  const { container } = render(<MemoryRouter><Research /></MemoryRouter>)
  await screen.findByRole('heading', { name: 'Research' })
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2))
  expect(fetch.mock.calls.map(([url]) => url).sort()).toEqual([
    '/api/ideas', '/api/research-memory?limit=20',
  ])
  expect(screen.queryByRole('heading', { name: /research decision/i })).toBeNull()
  const disclosure = container.querySelector<HTMLDetailsElement>('.research-diagnostics')!
  expect(disclosure.open).toBe(false)
  disclosure.open = true
  fireEvent(disclosure, new Event('toggle'))
  expect(await screen.findByRole('heading', { name: /research decision/i })).toBeTruthy()
  expect(fetch.mock.calls.some(([url]) => url === '/api/ops')).toBe(true)
})
