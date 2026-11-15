import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { clearFetchCache } from '../api'
import WalkForwardEvidence from './WalkForwardEvidence'

afterEach(() => { cleanup(); clearFetchCache(); vi.unstubAllGlobals() })

it('pins the requested WF run to a stable identity and refuses a mismatched response', async () => {
  const fetchMock = vi.fn(async (_url: string) => ({ ok: true, status: 200, json: async () => ({
    ok: true, fetched_at: '2026-01-01T00:00:00Z', stale: false,
    data: { strategy_id: 8, latest_research: null, evidence: null, recorded_provenance: null },
  }) }))
  vi.stubGlobal('fetch', fetchMock)
  render(<MemoryRouter initialEntries={['/strategy/7?research_run=12']}>
    <WalkForwardEvidence strategyId={7} />
  </MemoryRouter>)
  expect(await screen.findByText('research identity or run mismatch')).toBeTruthy()
  await waitFor(() => expect(fetchMock).toHaveBeenCalled())
  expect(fetchMock.mock.calls[0][0]).toBe('/api/strategy/7/research?run_id=12')
})
