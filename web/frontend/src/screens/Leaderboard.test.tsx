import { cleanup, render, screen } from '@testing-library/react'
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
    schema_version: 'strategy-board/v1', count: 1, rows: [{
      strategy_id: 41, name: 'quality_momentum', family: 'momentum', stage: 'candidate',
      latest_gate: null,
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

