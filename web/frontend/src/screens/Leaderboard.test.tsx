import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { clearFetchCache } from '../api'
import type { ApiEnvelope, StrategyBoardPayload, TriagePayload } from '../types'
import Leaderboard from './Leaderboard'

const triage: TriagePayload = {
  ok: true,
  items: [{
    kind: 'loop_down', severity: 0, title: 'paper loop stalled', detail: 'last session incomplete',
    since: '2026-10-30T12:00:00Z', route: '/now',
  }],
  sources: { fleet: true, ops: true, book: false },
  headline: { fleet_ok: 2, fleet_total: 3, book_allocated: null, book_capacity: null, loops_alerting: 1 },
  fetched_at: '2026-10-31T10:00:00Z',
  stale: true,
  last_error_code: 'ops_timeout',
}

const board: ApiEnvelope<StrategyBoardPayload> = {
  ok: true,
  fetched_at: '2026-10-31T10:00:00Z',
  stale: false,
  data: {
    schema_version: 'strategy-board/v1', evidence_schema_version: 'strategy-board-research/v2', count: 1, rows: [{
      strategy_id: 41, name: 'quality_momentum', family: 'momentum', stage: 'candidate',
      latest_gate: null, latest_research: null,
    }],
  },
}

afterEach(() => {
  cleanup()
  clearFetchCache()
  vi.unstubAllGlobals()
})

it('leads with the strategy leaderboard while keeping stale operational warnings visible', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({
    ok: true,
    status: 200,
    json: async () => url === '/api/triage' ? triage : board,
  })) as unknown as typeof fetch)

  render(<MemoryRouter><Leaderboard /></MemoryRouter>)

  expect(screen.getByRole('heading', { name: 'Strategy leaderboard' })).toBeTruthy()
  expect(await screen.findByText('paper loop stalled')).toBeTruthy()
  expect(screen.getByText('stale data')).toBeTruthy()
  expect(screen.getByText(/book unavailable.*warnings may be incomplete/i)).toBeTruthy()
  expect(screen.getByRole('link', { name: 'full ops diagnostics' }).getAttribute('href')).toBe('/now')
  expect((await screen.findByText('quality_momentum')).closest('a')?.getAttribute('href')).toBe('/strategy/41')
})



it('F1 distinguishes public in-sample windows from separate gate observations in either mode', async () => {
  const gateBoard = structuredClone(board)
  gateBoard.data.evidence_schema_version = 'strategy-board-evidence/v2'
  for (const row of gateBoard.data.rows) delete row.latest_research
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({
    ok: true, status: 200, json: async () => url === '/api/triage' ? triage :
      url === '/api/strategy-board?include_evidence=true' ? gateBoard : board,
  })) as unknown as typeof fetch)
  render(<MemoryRouter><Leaderboard /></MemoryRouter>)
  const intro = screen.getByRole('heading', { name: 'Strategy leaderboard' }).closest('header')!
  expect(intro.textContent).toMatch(/public WF windows are in-sample/i)
  expect(intro.textContent).toMatch(/gate OOS observations are separate/i)
  expect(screen.getByRole('button', { name: 'Public WF windows' }).getAttribute('aria-pressed')).toBe('true')
  fireEvent.click(screen.getByRole('button', { name: 'Gate OOS' }))
  expect(screen.getByRole('button', { name: 'Gate OOS' }).getAttribute('aria-pressed')).toBe('true')
  expect(intro.textContent).toMatch(/public WF windows are in-sample/i)
  expect(intro.textContent).toMatch(/gate OOS observations are separate/i)
  expect(intro.textContent).toMatch(/unknown and incompatible evidence stays unranked/i)
})
