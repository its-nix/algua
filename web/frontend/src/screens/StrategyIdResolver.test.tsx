import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { clearFetchCache } from '../api'
import type { ApiEnvelope, StrategyBoardPayload } from '../types'
import StrategyIdResolver from './StrategyIdResolver'

vi.mock('./StrategyDetail', () => ({
  default: ({ strategyName, expectedStrategyId }: {
    strategyName?: string
    expectedStrategyId?: number
  }) => <div>resolved detail: {strategyName} ({expectedStrategyId})</div>,
}))

const board: ApiEnvelope<StrategyBoardPayload> = {
  ok: true, fetched_at: '2026-10-31T10:00:00Z', stale: false,
  data: {
    schema_version: 'strategy-board/v1', count: 1,
    rows: [{ strategy_id: 7, name: '123', family: null, stage: 'dormant', latest_gate: null }],
  },
}

afterEach(() => {
  cleanup()
  clearFetchCache()
  vi.unstubAllGlobals()
})

function renderResolver(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes><Route path="/strategy/:id" element={<StrategyIdResolver />} /></Routes>
    </MemoryRouter>,
  )
}

it('resolves the stable ID through the board mapping without treating a numeric name as an ID', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => board })) as unknown as typeof fetch)
  renderResolver('/strategy/7')
  expect(await screen.findByText('resolved detail: 123 (7)')).toBeTruthy()
})

it('keeps stale and refresh-error identity lookup state visible above the detail', async () => {
  const staleBoard = { ...board, stale: true, last_error_code: 'board_cached' }
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, status: 200, json: async () => staleBoard })
    .mockResolvedValue({
      ok: false, status: 503, json: async () => ({ code: 'board_refresh_failed' }),
    })
  vi.stubGlobal('fetch', fetchMock as unknown as typeof fetch)

  renderResolver('/strategy/7')

  expect(await screen.findByText('resolved detail: 123 (7)')).toBeTruthy()
  expect(screen.getByText('stale data')).toBeTruthy()
  expect(screen.getByText(/last error board_cached/)).toBeTruthy()

  document.dispatchEvent(new Event('visibilitychange'))
  expect(await screen.findByText('refresh failed')).toBeTruthy()
  expect(screen.getByText('board_refresh_failed')).toBeTruthy()
})

it('fails closed for malformed or missing identities', async () => {
  renderResolver('/strategy/007')
  expect(screen.getByText('invalid strategy identity')).toBeTruthy()
  cleanup()
  clearFetchCache()
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => board })) as unknown as typeof fetch)
  renderResolver('/strategy/8')
  expect(await screen.findByText('strategy identity not found')).toBeTruthy()
})

