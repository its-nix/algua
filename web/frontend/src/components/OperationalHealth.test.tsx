import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { clearFetchCache } from '../api'
import type { TriagePayload } from '../types'
import OperationalHealth from './OperationalHealth'

const healthyRead: TriagePayload = {
  ok: true,
  items: [],
  sources: { fleet: true, ops: true, book: true },
  headline: { fleet_ok: 2, fleet_total: 2, book_allocated: 1, book_capacity: 64, loops_alerting: 0 },
  fetched_at: '2026-10-31T10:00:00Z',
  stale: false,
}

afterEach(() => {
  cleanup()
  clearFetchCache()
  vi.unstubAllGlobals()
})

it('does not turn a failed refresh of a prior health read into a silent all-clear', async () => {
  let fail = false
  vi.stubGlobal('fetch', vi.fn(async () => fail
    ? { ok: false, status: 502, json: async () => ({ code: 'triage_timeout', error: 'timed out' }) }
    : { ok: true, status: 200, json: async () => healthyRead }) as unknown as typeof fetch)

  render(<MemoryRouter><OperationalHealth /></MemoryRouter>)
  expect(await screen.findByText(/no current warnings/i)).toBeTruthy()
  fail = true
  document.dispatchEvent(new Event('visibilitychange'))
  await waitFor(() => expect(screen.getByText('health refresh failed')).toBeTruthy())
  expect(screen.getByText(/last available read.*triage_timeout/i)).toBeTruthy()
  expect(screen.getByRole('button', { name: 'retry' })).toBeTruthy()
})
