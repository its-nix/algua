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
