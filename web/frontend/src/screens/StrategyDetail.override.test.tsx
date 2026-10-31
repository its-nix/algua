import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { clearFetchCache } from '../api'
import type { StrategyDetailResponse } from '../types'
import StrategyDetail from './StrategyDetail'

const detail: StrategyDetailResponse = {
  ok: true,
  strategy: 'reused_name',
  registry: {
    id: 8,
    name: 'reused_name',
    stage: 'candidate',
    family: null,
    tags: [],
    author: 'agent',
    hypothesis_status: 'untested',
    derived_from: null,
    description: 'evidence belonging to another strategy identity',
    transitions: [],
  },
  paper: null,
  gates: null,
  fetched_at: '2026-10-31T10:00:00Z',
  stale: false,
}

afterEach(() => {
  cleanup()
  clearFetchCache()
  vi.unstubAllGlobals()
})

it('fetches detail and series by the resolver-provided name without parsing numeric names as IDs', async () => {
  const fetchMock = vi.fn(async (_url: string) => ({
    ok: false, status: 503, json: async () => ({ code: 'offline' }),
  }))
  vi.stubGlobal('fetch', fetchMock as unknown as typeof fetch)
  render(<MemoryRouter><StrategyDetail strategyName="123" /></MemoryRouter>)
  await waitFor(() => expect(fetchMock).toHaveBeenCalled())
  expect(fetchMock.mock.calls.map(([url]) => url)).toEqual(expect.arrayContaining([
    '/api/strategy/123', '/api/strategy/123/series',
  ]))
})

it.each([
  ['mismatched', detail, 'strategy identity mismatch'],
  ['unverifiable', { ...detail, registry: null }, 'strategy identity unverified'],
])('refuses %s name-keyed evidence for a stable-ID route', async (_case, response, message) => {
  const fetchMock = vi.fn(async (_url: string) => ({
    ok: true, status: 200, json: async () => response,
  }))
  vi.stubGlobal('fetch', fetchMock as unknown as typeof fetch)

  render(
    <MemoryRouter>
      <StrategyDetail strategyName="reused_name" expectedStrategyId={7} />
    </MemoryRouter>,
  )

  expect(await screen.findByText(message)).toBeTruthy()
  expect(screen.queryByText('evidence belonging to another strategy identity')).toBeNull()
  expect(screen.getByRole('button', { name: 'retry' })).toBeTruthy()
  expect(screen.getByRole('link', { name: 'back to leaderboard' })).toBeTruthy()
  expect(fetchMock.mock.calls.map(([url]) => url)).toEqual(['/api/strategy/reused_name'])
})
