import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { clearFetchCache } from '../api'
import StrategyIdResolver from './StrategyIdResolver'

const registry = {
  id: 7, name: 'same_name', stage: 'candidate', family: null, tags: [],
  author: 'agent', hypothesis_status: 'untested', derived_from: null,
  description: 'verified matching evidence', transitions: [],
}
const board = {
  ok: true, fetched_at: '2026-10-31T10:00:00Z', stale: false,
  data: { schema_version: 'strategy-board/v1', count: 1, rows: [
    { strategy_id: 7, name: 'same_name', stage: 'candidate', family: null, latest_gate: null },
  ] },
}

afterEach(() => { cleanup(); clearFetchCache(); vi.unstubAllGlobals() })

it.each([
  ['null', null, 'strategy identity unverified'],
  ['mismatched', { ...registry, id: 8, description: 'unverified foreign evidence' }, 'strategy identity mismatch'],
])('retries board and %s detail, recovering unchanged mapping only after identity verification', async (_case, initialRegistry, message) => {
  let detailCalls = 0
  let recover: (() => void) | undefined
  const recovery = new Promise<void>((resolve) => { recover = resolve })
  const fetchMock = vi.fn(async (url: string) => {
    let payload: unknown = board
    if (url === '/api/strategy/same_name') {
      detailCalls += 1
      if (detailCalls > 1) await recovery
      payload = {
        ok: true, strategy: 'same_name', registry: detailCalls > 1 ? registry : initialRegistry,
        paper: null, gates: null, fetched_at: '2026-10-31T10:00:00Z', stale: false,
      }
    } else if (url.endsWith('/series')) {
      payload = { ok: true, fetched_at: '2026-10-31T10:00:00Z', stale: false,
        data: { series: { paper: [], live: [] } } }
    }
    return { ok: true, status: 200, json: async () => payload }
  })
  vi.stubGlobal('fetch', fetchMock as unknown as typeof fetch)
  render(<MemoryRouter initialEntries={['/strategy/7']}>
    <Routes><Route path="/strategy/:id" element={<StrategyIdResolver />} /></Routes>
  </MemoryRouter>)
  expect(await screen.findByText(message)).toBeTruthy()
  expect(screen.queryByText('unverified foreign evidence')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'retry' }))
  await waitFor(() => {
    expect(fetchMock.mock.calls.filter(([url]) => url === '/api/strategy-board')).toHaveLength(2)
    expect(detailCalls).toBe(2)
  })
  expect(screen.queryByText('verified matching evidence')).toBeNull()
  expect(fetchMock.mock.calls.some(([url]) => url.endsWith('/series'))).toBe(false)
  recover?.()
  expect(await screen.findByText('verified matching evidence')).toBeTruthy()
  await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('/series'))).toHaveLength(1))
  expect(screen.queryByText(message)).toBeNull()
})


it('keeps the synthetic nonqualification label visible on stable-ID gate detail', async () => {
  const evidenceBoard = structuredClone(board)
  Object.assign(evidenceBoard.data, { evidence_schema_version: 'strategy-board-evidence/v2' })
  Object.assign(evidenceBoard.data.rows[0], {
    latest_gate: { run_id: 77, created_at: '2026-01-01T00:00:00Z', passed: false,
      sharpe_oos: 0, total_return_oos: -0.1, max_drawdown_oos: -0.2, n_obs_oos: 63,
      mean_window_sharpe: 0, min_window_sharpe: -1, pct_positive_windows: 0.5 },
    evidence: { run_id: 77, comparison: { status: 'UNKNOWN', observed_metric_sort_enabled: false,
      reasons: ['comparison_context_absent'], cohort_id: null, context: null },
      evaluation: { status: 'UNAVAILABLE', reason: 'missing_fields', value: null },
      oos_interval: { status: 'UNAVAILABLE', reason: 'missing_fields', value: null },
      snapshot_provenance: { status: 'VALID', reason: null, value: {
        schema_version: 'pilot-provenance/v1', data_tier: 'synthetic_fixture',
        provider: 'fixture', universe_method: 'synthetic/v1',
        limitations: ['synthetic_not_market_data'], coverage_start: '2021-01-01', coverage_end: '2024-12-31',
      } } },
  })
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, status: 200,
    json: async () => url === '/api/strategy-board?include_evidence=true' ? evidenceBoard :
      url === '/api/strategy-board' ? board : url.endsWith('/series') ? {
        ok: true, data: { series: { paper: [], live: [] } }, stale: false,
      } : url === '/api/strategy/same_name' ? {
        ok: true, strategy: 'same_name', registry: { ...registry, stage: 'backtested' },
        paper: null, gates: null, fetched_at: '2026-01-01T00:00:00Z', stale: false,
      } : { ok: true, data: { runs: [], count: 0 }, stale: false },
  })))
  render(<MemoryRouter initialEntries={['/strategy/7']}>
    <Routes><Route path="/strategy/:id" element={<StrategyIdResolver />} /></Routes>
  </MemoryRouter>)
  expect(await screen.findByText(/Synthetic fixture.*not market data.*not qualification/i)).toBeTruthy()
  expect(screen.getByText(/Gate OOS.*run 77.*strategy ID 7/i)).toBeTruthy()
})
