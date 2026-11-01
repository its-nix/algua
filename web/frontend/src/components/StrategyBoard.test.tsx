import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { clearFetchCache } from '../api'
import type { ApiEnvelope, StrategyBoardGate, StrategyBoardPayload, StrategyBoardRow } from '../types'
import StrategyBoard, { SORT_OPTIONS } from './StrategyBoard'

function gate(overrides: Partial<StrategyBoardGate> & { run_id: number }): StrategyBoardGate {
  return {
    created_at: '2026-10-15T12:00:00+00:00',
    passed: true,
    sharpe_oos: null,
    total_return_oos: null,
    max_drawdown_oos: null,
    n_obs_oos: null,
    mean_window_sharpe: null,
    min_window_sharpe: null,
    pct_positive_windows: null,
    ...overrides,
  }
}

function row(
  id: number,
  name: string,
  stage: string,
  latest_gate: StrategyBoardGate | null,
  family: string | null = null,
): StrategyBoardRow {
  return { strategy_id: id, name, family, stage, latest_gate }
}

// Lifecycle order, as the server returns it.
const rows: StrategyBoardRow[] = [
  row(1, 'bare_idea', 'idea', null),
  row(2, 'mined_above', 'paper', gate({ run_id: 902, sharpe_oos: 1.42, mean_window_sharpe: 0.08,
                                         min_window_sharpe: -0.1, total_return_oos: 0.2,
                                         max_drawdown_oos: -0.3, pct_positive_windows: 0.25,
                                         n_obs_oos: 126, passed: false }), 'momentum'),
  row(3, 'honest_neg', 'paper', gate({ run_id: 903, sharpe_oos: -0.24, mean_window_sharpe: -0.18,
                                        min_window_sharpe: -0.4, total_return_oos: 0,
                                        max_drawdown_oos: -0.05, pct_positive_windows: 0.5,
                                        passed: false }), 'reversal'),
  row(4, 'unmeasured', 'paper', gate({ run_id: 904, passed: null })),
  row(5, 'steady', 'live', gate({ run_id: 905, sharpe_oos: 0.61, mean_window_sharpe: 0.52,
                                   min_window_sharpe: 0.2, total_return_oos: 0.1,
                                   max_drawdown_oos: -0.08, pct_positive_windows: 0.75 }), 'momentum'),
  row(6, 'tied_a', 'live', gate({ run_id: 906, sharpe_oos: 0.61, mean_window_sharpe: 0.3 })),
]

function env(payload: StrategyBoardPayload): ApiEnvelope<StrategyBoardPayload> {
  return { ok: true, fetched_at: '2026-10-19T00:00:00Z', stale: false, data: payload }
}

const populated = env({ schema_version: 'strategy-board/v1', count: rows.length, rows })

const PILOT_PROXY_LIMITATIONS = [
  'adjusted_close_vendor_revisable',
  'corporate_actions_unverified',
  'delisted_names_absent',
  'event_timing_unavailable',
  'historical_market_cap_unavailable',
  'point_in_time_universe_unavailable',
  'survivorship_biased_selection',
]

const metadataBound = {
  ...populated,
  data: {
    ...populated.data,
    evidence_schema_version: 'strategy-board-evidence/v2',
    rows: populated.data.rows.map((value, index) => index !== 1 ? { ...value, evidence: null } : {
      ...value,
      evidence: {
        run_id: 902,
        evaluation: {
          status: 'VALID', reason: null,
          value: {
            period_start: '2024-01-02', period_end: '2025-12-31', timeframe: '1d',
            metric_schema_version: 3,
          },
        },
        oos_interval: {
          status: 'VALID', reason: null,
          value: { holdout_start: '2025-07-01', holdout_end: '2025-12-31', n_bars: 126 },
        },
        snapshot_provenance: {
          status: 'VALID', reason: null,
          value: {
            schema_version: 'pilot-provenance/v1', data_tier: 'pilot_real_proxy',
            universe_method: 'fixed_proxy_selected_at_ingest',
            limitations: PILOT_PROXY_LIMITATIONS,
            coverage_start: '2023-12-15', coverage_end: '2025-12-31', provider: 'yfinance',
          },
        },
        comparison: {
          status: 'UNKNOWN', observed_metric_sort_enabled: false,
          reasons: ['recorded_inputs_unavailable'], cohort_id: null, context: null,
        },
      },
    }),
  },
}

// `useFetch` keeps a module-level cache keyed by URL; every test brings its own payload.
beforeEach(() => clearFetchCache())

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function mockBoard(body: unknown, status = 200) {
  const fetchMock = vi.fn(async () => ({ ok: status < 400, status, json: async () => body }))
  vi.stubGlobal('fetch', fetchMock as unknown as typeof fetch)
  return fetchMock
}

function renderBoard() {
  return render(
    <MemoryRouter>
      <StrategyBoard />
    </MemoryRouter>,
  )
}

const names = () => screen.getAllByTestId('board-row-name').map((el) => el.textContent)

function openControls() {
  fireEvent.click(screen.getByRole('button', { name: /board controls/i }))
}

it('announces loading without presenting an empty board', () => {
  vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})) as unknown as typeof fetch)
  renderBoard()
  expect(screen.getByRole('status').textContent).toContain('loading strategy leaderboard')
  expect(screen.queryByText(/no strategies registered/i)).toBeNull()
})

it('keeps stage and family filters behind one control and explains why metric sorting is unavailable', async () => {
  mockBoard(populated)
  renderBoard()
  await screen.findAllByTestId('board-row')
  const controls = screen.getByRole('button', { name: /board controls.*all stages.*all families/i })
  expect(controls.getAttribute('aria-expanded')).toBe('false')
  expect(screen.queryByRole('button', { name: 'oos sharpe' })).toBeNull()
  fireEvent.click(controls)
  expect(controls.getAttribute('aria-expanded')).toBe('true')
  expect(screen.getByRole('button', { name: 'oos sharpe' }).hasAttribute('disabled')).toBe(true)
  expect(screen.getByText(/Select a matching cohort/i)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: /^live/ }))
  fireEvent.click(screen.getByRole('button', { name: /^momentum/ }))
  expect(screen.getByRole('button', { name: /board controls.*live.*momentum/i })).toBeTruthy()
})

it('renders exactly one row per registered strategy, including ones with no gate evidence', async () => {
  mockBoard(populated)
  renderBoard()
  expect(await screen.findAllByTestId('board-row')).toHaveLength(rows.length)
  expect(names()).toEqual(rows.map((r) => r.name))
  const bare = screen.getAllByTestId('board-row')[0]
  expect(within(bare).getByText(/no usable gate evidence/i)).toBeTruthy()
  expect(bare.querySelector('svg')).toBeNull()
})

it('keeps a missing metric unavailable instead of rendering it as zero', async () => {
  mockBoard(populated)
  renderBoard()
  await screen.findAllByTestId('board-row')
  const unmeasured = screen.getAllByTestId('board-row')[3]
  expect(unmeasured.textContent).not.toMatch(/\b0(\.0+)?\b/)
  expect(unmeasured.textContent).toContain('UNKNOWN')
})

it('preserves an observed zero while keeping absent and non-finite metrics unknown', async () => {
  mockBoard(populated)
  renderBoard()
  const honest = (await screen.findAllByTestId('board-row'))[2]
  expect(honest.textContent).toMatch(/return0\.0%/i)

  cleanup()
  clearFetchCache()
  const malformed = structuredClone(populated) as unknown as Record<string, unknown>
  const data = malformed.data as { rows: Array<{ latest_gate: { sharpe_oos: number } }> }
  data.rows[1].latest_gate.sharpe_oos = Number.POSITIVE_INFINITY
  mockBoard(malformed)
  renderBoard()
  expect(await screen.findByText('unsupported_schema')).toBeTruthy()
})

it('links each row by stable strategy identity', async () => {
  mockBoard(populated)
  renderBoard()
  const first = (await screen.findAllByTestId('board-row'))[1]
  expect(first.tagName).toBe('A')
  expect(first.getAttribute('href')).toBe('/strategy/2')
})

it('filters by stage and family including UNKNOWN, and explains empty intersections', async () => {
  const fetchMock = mockBoard(populated)
  renderBoard()
  await screen.findAllByTestId('board-row')
  openControls()
  fireEvent.click(screen.getByRole('button', { name: /^live/ }))
  expect(screen.getByRole('button', { name: /^live/ }).getAttribute('aria-pressed')).toBe('true')
  expect(names()).toEqual(['steady', 'tied_a'])
  fireEvent.click(screen.getByRole('button', { name: /^momentum/ }))
  expect(names()).toEqual(['steady'])
  fireEvent.click(screen.getByRole('button', { name: /^reversal/ }))
  expect(screen.queryByTestId('board-row')).toBeNull()
  expect(screen.getByText(/no strategies match this stage and family/i)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: /^all stages/ }))
  expect(names()).toEqual(['honest_neg'])
  fireEvent.click(screen.getByRole('button', { name: /^unknown family/i }))
  expect(names()).toEqual(['bare_idea', 'unmeasured', 'tied_a'])
  expect(fetchMock).toHaveBeenCalledTimes(1)
})

it('keeps deterministic server order because every current row is noncomparable', async () => {
  mockBoard(populated)
  renderBoard()
  await screen.findAllByTestId('board-row')
  openControls()
  for (const opt of SORT_OPTIONS) {
    const button = screen.getByRole('button', { name: opt.label })
    expect(button.hasAttribute('disabled')).toBe(true)
    fireEvent.click(button)
  }
  expect(names()).toEqual(rows.map((r) => r.name))
})

it('never changes which run represents a strategy when the comparison order changes', async () => {
  mockBoard(populated)
  renderBoard()
  await screen.findAllByTestId('board-row')
  openControls()
  const runIds = () =>
    Object.fromEntries(
      screen.getAllByTestId('board-row').map((el) => [el.getAttribute('data-strategy'), el.getAttribute('data-run')]),
    )
  expect(runIds().mined_above).toBe('902')
  expect(runIds().bare_idea).toBe('')
})

it('shows the latest observed OOS scalars without inferring legacy comparison metadata', async () => {
  mockBoard(populated)
  renderBoard()
  await screen.findAllByTestId('board-row')
  const measured = within(screen.getAllByTestId('board-row')[1])
  expect(measured.getByText((_, node) => node?.textContent === 'sharpe1.42')).toBeTruthy()
  expect(measured.getByText((_, node) => node?.textContent === 'return20.0%')).toBeTruthy()
  expect(measured.getByText((_, node) => node?.textContent === 'drawdown-30.0%')).toBeTruthy()
  expect(measured.getByText((_, node) => node?.textContent === 'sample126')).toBeTruthy()
  expect(measured.getByText('observed 2026-10-15')).toBeTruthy()
  expect(measured.getByText('age UNKNOWN')).toBeTruthy()
  expect(measured.getByText(/evidence extension unavailable.*no inference/i)).toBeTruthy()
  expect(measured.queryByText(/tier UNKNOWN|period UNKNOWN/)).toBeNull()
  expect(screen.getByText(/Never promotion or expected profit/i)).toBeTruthy()
})

it('opts into and renders metadata-bound evaluation, OOS, snapshot coverage, and every limitation', async () => {
  const fetchMock = mockBoard(metadataBound)
  renderBoard()

  const measuredRow = (await screen.findAllByTestId('board-row'))[1]
  const measured = within(measuredRow)
  expect(fetchMock).toHaveBeenCalledWith(
    '/api/strategy-board?include_evidence=true&research=true',
    { headers: { accept: 'application/json' } },
  )
  expect(measured.getByText(/metadata-bound only.*not payload or PIT proof/i)).toBeTruthy()
  expect(measured.getByText(/requested evaluation/i).parentElement?.textContent).toContain(
    '2024-01-02–2025-12-31 · 1d · metric schema 3',
  )
  expect(measured.getByText(/lineage-valid OOS/i).parentElement?.textContent).toContain(
    '2025-07-01–2025-12-31 · 126 bars',
  )
  expect(measured.getByText(/snapshot coverage/i).parentElement?.textContent).toContain(
    '2023-12-15–2025-12-31',
  )
  expect(measured.getByText(/data tier/i).parentElement?.textContent).toContain('pilot_real_proxy')
  for (const limitation of PILOT_PROXY_LIMITATIONS) {
    expect(measured.getByText(limitation)).toBeTruthy()
  }
  expect(measured.getByText(/comparison UNKNOWN/i)).toBeTruthy()
  expect(measuredRow.getAttribute('aria-label')).toBe('View mined_above strategy details (ID 2)')
})

it('distinguishes an absent legacy extension from malformed extension claims', async () => {
  mockBoard(populated)
  renderBoard()
  const legacy = within((await screen.findAllByTestId('board-row'))[1])
  expect(legacy.getByText(/evidence extension unavailable.*no inference/i)).toBeTruthy()

  cleanup()
  clearFetchCache()
  mockBoard({
    ...metadataBound,
    data: { ...metadataBound.data, evidence_schema_version: 'strategy-board-evidence/v3' },
  })
  renderBoard()
  const unsupported = within((await screen.findAllByTestId('board-row'))[1])
  expect(unsupported.getByText(/evidence INVALID.*unsupported evidence schema/i)).toBeTruthy()

  cleanup()
  clearFetchCache()
  const orphan = structuredClone(metadataBound) as typeof metadataBound
  orphan.data.rows[0] = { ...orphan.data.rows[1], latest_gate: null }
  mockBoard(orphan)
  renderBoard()
  const withoutGate = within((await screen.findAllByTestId('board-row'))[0])
  expect(withoutGate.getByText(/evidence INVALID.*without a latest gate/i)).toBeTruthy()
})

it('invalidates evidence/schema/member incoherence while preserving a truly legacy response', async () => {
  const evidenceWithoutSchema = structuredClone(metadataBound) as unknown as Record<string, unknown>
  delete (evidenceWithoutSchema.data as Record<string, unknown>).evidence_schema_version
  mockBoard(evidenceWithoutSchema)
  renderBoard()
  let measured = within((await screen.findAllByTestId('board-row'))[1])
  expect(measured.getByText(/evidence INVALID.*schema missing/i)).toBeTruthy()
  expect(measured.queryByText(/extension unavailable/i)).toBeNull()

  cleanup()
  clearFetchCache()
  const memberMissing = structuredClone(metadataBound) as unknown as Record<string, unknown>
  const memberRows = (memberMissing.data as { rows: Array<Record<string, unknown>> }).rows
  delete memberRows[1].evidence
  mockBoard(memberMissing)
  renderBoard()
  measured = within((await screen.findAllByTestId('board-row'))[1])
  expect(measured.getByText(/evidence INVALID.*member missing/i)).toBeTruthy()

  cleanup()
  clearFetchCache()
  mockBoard(env({
    schema_version: 'strategy-board/v1',
    evidence_schema_version: 'strategy-board-evidence/v3',
    count: 0,
    rows: [],
  } as unknown as StrategyBoardPayload))
  renderBoard()
  expect(await screen.findByText(/evidence INVALID.*unsupported evidence schema/i)).toBeTruthy()
  expect(screen.queryByText(/no strategies registered/i)).toBeNull()
})

it.each([
  ['invalid provider syntax', (value: Record<string, unknown>) => { value.provider = 'made up provider' }],
  ['invalid universe syntax', (value: Record<string, unknown>) => { value.universe_method = 'fixed demo symbols' }],
  ['unknown limitation', (value: Record<string, unknown>) => { value.limitations = ['invented_limit'] }],
  ['duplicate limitations', (value: Record<string, unknown>) => {
    value.limitations = [...PILOT_PROXY_LIMITATIONS, PILOT_PROXY_LIMITATIONS.at(-1)]
  }],
  ['unsorted limitations', (value: Record<string, unknown>) => {
    value.limitations = [...PILOT_PROXY_LIMITATIONS].reverse()
  }],
  ['incomplete pilot limitations', (value: Record<string, unknown>) => {
    value.limitations = PILOT_PROXY_LIMITATIONS.slice(1)
  }],
  ['synthetic limitation on proxy data', (value: Record<string, unknown>) => {
    value.limitations = [...PILOT_PROXY_LIMITATIONS, 'synthetic_not_market_data'].sort()
  }],
  ['missing synthetic limitation', (value: Record<string, unknown>) => {
    value.data_tier = 'synthetic_fixture'
    value.limitations = []
  }],
] as const)('invalidates canonical provenance with %s', async (_caseName, mutate) => {
  const malformed = structuredClone(metadataBound)
  const value = malformed.data.rows[1].evidence?.snapshot_provenance.value
  if (value === null || value === undefined) throw new Error('fixture row must carry snapshot evidence')
  mutate(value as unknown as Record<string, unknown>)
  mockBoard(malformed)
  renderBoard()

  const measured = within((await screen.findAllByTestId('board-row'))[1])
  expect(measured.getByText(/snapshot provenance/i).parentElement?.textContent).toContain(
    'INVALID · malformed response',
  )
  expect(measured.queryByText(/data tier/i)).toBeNull()
})

it('keeps malformed, INVALID, and UNAVAILABLE wrappers atomic with no fallback inference', async () => {
  const malformed = structuredClone(metadataBound)
  const evidence = malformed.data.rows[1].evidence
  if (evidence === null) throw new Error('fixture row must carry evidence')
  evidence.evaluation.value = {
    ...evidence.evaluation.value!, period_start: '2025-12-31', period_end: '2024-01-02',
  }
  evidence.oos_interval.value = {
    ...evidence.oos_interval.value!, holdout_start: '2023-01-01', holdout_end: '2023-02-01',
  }
  ;(evidence as unknown as { snapshot_provenance: unknown }).snapshot_provenance = {
    status: 'UNAVAILABLE', reason: 'source_unavailable', value: null,
  }
  mockBoard(malformed)
  renderBoard()

  const measured = within((await screen.findAllByTestId('board-row'))[1])
  expect(measured.getByText(/requested evaluation/i).parentElement?.textContent).toContain(
    'INVALID · malformed response',
  )
  expect(measured.getByText(/lineage-valid OOS/i).parentElement?.textContent).toContain(
    'INVALID · malformed response',
  )
  expect(measured.getByText(/snapshot provenance/i).parentElement?.textContent).toContain(
    'UNAVAILABLE · source unavailable',
  )
  expect(measured.queryByText(/2025-12-31–2024-01-02/)).toBeNull()
  expect(measured.queryByText(/pilot_real_proxy/)).toBeNull()
})

it('invalidates contradictory OOS counts and non-allowlisted evidence fields', async () => {
  const contradictory = structuredClone(metadataBound) as typeof metadataBound & {
    data: { rows: Array<{ evidence: Record<string, unknown> | null }> }
  }
  const evidence = contradictory.data.rows[1].evidence
  if (evidence === null) throw new Error('fixture row must carry evidence')
  const oos = evidence.oos_interval as { value: { n_bars: number } }
  oos.value.n_bars = 999
  mockBoard(contradictory)
  renderBoard()
  let measured = within((await screen.findAllByTestId('board-row'))[1])
  expect(measured.getByText(/lineage-valid OOS/i).parentElement?.textContent).toContain(
    'INVALID · count mismatch',
  )
  expect(measured.queryByText(/999 bars/)).toBeNull()

  cleanup()
  clearFetchCache()
  const extra = structuredClone(metadataBound) as typeof contradictory
  if (extra.data.rows[1].evidence === null) throw new Error('fixture row must carry evidence')
  extra.data.rows[1].evidence.snapshot_id = 'forbidden-in-extension'
  mockBoard(extra)
  renderBoard()
  measured = within((await screen.findAllByTestId('board-row'))[1])
  expect(measured.getByText(/evidence INVALID.*run-bound response malformed/i)).toBeTruthy()
  expect(measured.queryByText(/pilot_real_proxy/)).toBeNull()
})

it('isolates evidence by stable strategy and run identity even when names are reused', async () => {
  const first = structuredClone(metadataBound.data.rows[1])
  const second = structuredClone(metadataBound.data.rows[1])
  first.name = 'same_name'
  second.name = 'same_name'
  second.strategy_id = 77
  second.latest_gate = { ...second.latest_gate!, run_id: 977 }
  second.evidence = {
    ...second.evidence!,
    run_id: 977,
    snapshot_provenance: {
      ...second.evidence!.snapshot_provenance,
      value: {
        ...second.evidence!.snapshot_provenance.value!,
        data_tier: 'synthetic_fixture', provider: 'fixture_generator',
        limitations: ['synthetic_not_market_data'],
      },
    },
  }
  mockBoard({
    ...metadataBound,
    data: { ...metadataBound.data, count: 2, rows: [first, second] },
  })
  renderBoard()

  const rendered = await screen.findAllByTestId('board-row')
  expect(rendered).toHaveLength(2)
  expect(rendered[0].getAttribute('href')).toBe('/strategy/2')
  expect(rendered[1].getAttribute('href')).toBe('/strategy/77')
  expect(within(rendered[0]).getByText(/yfinance/)).toBeTruthy()
  expect(within(rendered[0]).queryByText(/fixture_generator/)).toBeNull()
  expect(within(rendered[1]).getByText(/fixture_generator/)).toBeTruthy()
  expect(within(rendered[1]).queryByText(/yfinance/)).toBeNull()

  cleanup()
  clearFetchCache()
  second.evidence.run_id = 976
  mockBoard({
    ...metadataBound,
    data: { ...metadataBound.data, count: 1, rows: [second] },
  })
  renderBoard()
  expect(await screen.findByText(/evidence INVALID.*run-bound response malformed/i)).toBeTruthy()
  expect(screen.queryByText(/fixture_generator/)).toBeNull()
})

it('refuses a VALID verified_pit metadata claim when no independent PIT verifier exists', async () => {
  const unverifiedPit = structuredClone(metadataBound)
  const evidence = unverifiedPit.data.rows[1].evidence
  if (evidence?.snapshot_provenance.value === null || evidence === null) {
    throw new Error('fixture row must carry snapshot evidence')
  }
  evidence.snapshot_provenance.value.data_tier = 'verified_pit'
  mockBoard(unverifiedPit)
  renderBoard()

  const measured = within((await screen.findAllByTestId('board-row'))[1])
  expect(measured.getByText(/snapshot provenance/i).parentElement?.textContent).toContain(
    'INVALID · PIT verifier unavailable',
  )
  expect(measured.queryByText(/data tier.*verified_pit/i)).toBeNull()
})

it('shows a directed empty state for an empty registry, not an error', async () => {
  mockBoard(env({ schema_version: 'strategy-board/v1', count: 0, rows: [] }))
  renderBoard()
  expect(await screen.findByText(/no strategies registered/i)).toBeTruthy()
  expect(screen.getByText(/registry add/i)).toBeTruthy()
  expect(screen.queryByText(/fetch failed/i)).toBeNull()
})

it('never presents a stale empty registry as current', async () => {
  mockBoard({
    ...env({ schema_version: 'strategy-board/v1', count: 0, rows: [] }),
    stale: true,
    last_error_code: 'cli_timeout',
  })
  renderBoard()
  expect(await screen.findByText('stale data')).toBeTruthy()
  expect(screen.getByText(/last error cli_timeout/i)).toBeTruthy()
  expect(screen.getByText(/no strategies registered/i)).toBeTruthy()
})

it('shows the error treatment with retry on a backend failure — never a false empty board', async () => {
  const fetchMock = mockBoard({ ok: false, error: 'boom', code: 'cli_timeout' }, 502)
  renderBoard()
  expect(await screen.findByText('fetch failed')).toBeTruthy()
  expect(screen.getByText('cli_timeout')).toBeTruthy()
  expect(screen.queryByText(/no strategies registered/i)).toBeNull()
  expect(screen.queryByTestId('board-row')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'retry' }))
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
})

it('refuses an unknown schema version rather than guessing at its shape', async () => {
  mockBoard(env({ schema_version: 'strategy-board/v2', count: 1, rows } as unknown as StrategyBoardPayload))
  renderBoard()
  expect(await screen.findByText('fetch failed')).toBeTruthy()
  expect(screen.queryByTestId('board-row')).toBeNull()
})

it('refuses null or malformed versioned data instead of throwing while rendering', async () => {
  mockBoard({ ...populated, data: null })
  renderBoard()
  expect(await screen.findByText('unsupported_schema')).toBeTruthy()
  cleanup()
  clearFetchCache()
  mockBoard({ ...populated, data: { ...populated.data, count: 1, rows: [null] } })
  renderBoard()
  expect(await screen.findByText('unsupported_schema')).toBeTruthy()
})

it('exposes no action that mutates state', async () => {
  mockBoard(populated)
  const { container } = renderBoard()
  await screen.findAllByTestId('board-row')
  expect(container.querySelector('form, input, select, textarea')).toBeNull()
  const labels = screen.getAllByRole('button').map((b) => b.textContent ?? '')
  expect(labels.join(' ')).not.toMatch(/promote|retire|allocate|trade|approve/i)
})

it('discloses recorded costs even when the execution context remains unranked', async () => {
  const payload = structuredClone(metadataBound)
  Object.assign(payload.data.rows[1], { recorded_provenance: { status: 'VALID', reason: null,
    value: { bars_snapshot_id: 'recorded-snapshot', bars_content_hash: 'b'.repeat(64),
      execution_costs: { schema_version: 'execution-costs/v1', model: 'vectorbt.from_orders',
        fees: 0.0005, fees_unit: 'fraction_of_trade_notional_per_side', slippage: 0,
        slippage_unit: 'adverse_fill_price_fraction_per_side' } } } })
  mockBoard(payload)
  renderBoard()
  expect(await screen.findByText(/Recorded fees 0.0005 of trade notional\/side/)).toBeTruthy()
  expect(screen.getByText(/slippage 0 adverse price fraction\/side/)).toBeTruthy()
})
