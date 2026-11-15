// R1 regression adapted from independent reviewer gpt-6.1-sol/high,
// session 01a199e3-fb17-77d0-8f0d-71500a557a13; extended to both directions/schema mismatch.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { clearFetchCache } from '../api'
import fixture from '../fixtures/public-windows.json'
import StrategyBoard from './StrategyBoard'

// Synthetic gate-shaped transport control only; no positive gate authority is asserted.
const gate = { ...fixture, evidence_schema_version: 'strategy-board-evidence/v2',
  rows: fixture.rows.map(({ latest_research: _research, ...row }) => ({ ...row,
    latest_gate: null, evidence: null, recorded_provenance: null })) }
const envelope = (data: unknown) => ({ ok: true, fetched_at: '2026-11-02T00:00:00Z', stale: false, data })
function mount() { render(<MemoryRouter><StrategyBoard /></MemoryRouter>) }
afterEach(() => { cleanup(); clearFetchCache(); vi.unstubAllGlobals() })

it('retains Gate OOS evidence after an older Public WF request completes', async () => {
  let release!: (value: unknown) => void
  const publicReply = new Promise(resolve => { release = resolve })
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, status: 200,
    json: () => url.includes('research=true') ? publicReply : Promise.resolve(envelope(gate)),
  })))
  mount()
  fireEvent.click(screen.getByRole('button', { name: 'Gate OOS' }))
  await screen.findByText(/latest gate run each/)
  await act(async () => { release(envelope(fixture)); await publicReply })
  expect(screen.getByRole('button', { name: 'Gate OOS' }).getAttribute('aria-pressed')).toBe('true')
  expect(screen.queryByText(/latest WF research run each/)).toBeNull()
  expect(screen.getByText(/latest gate run each/)).toBeTruthy()
})

it('retains Public WF evidence after an older Gate OOS request completes', async () => {
  let release!: (value: unknown) => void
  const gateReply = new Promise(resolve => { release = resolve })
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, status: 200,
    json: () => url.includes('research=true') ? Promise.resolve(envelope(fixture)) : gateReply,
  })))
  mount()
  await screen.findByText(/latest WF research run each/)
  fireEvent.click(screen.getByRole('button', { name: 'Gate OOS' }))
  fireEvent.click(screen.getByRole('button', { name: 'Public WF windows' }))
  await screen.findByText(/latest WF research run each/)
  await act(async () => { release(envelope(gate)); await gateReply })
  expect(screen.getByRole('button', { name: 'Public WF windows' }).getAttribute('aria-pressed')).toBe('true')
  expect(screen.queryByText(/latest gate run each/)).toBeNull()
  expect(screen.getByText(/latest WF research run each/)).toBeTruthy()
})

it.each(['public', 'gate'])('fails closed when the selected %s mode receives the other schema', async mode => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, status: 200,
    json: async () => envelope(url.includes('research=true') ? gate : fixture),
  })))
  mount()
  if (mode === 'gate') fireEvent.click(screen.getByRole('button', { name: 'Gate OOS' }))
  await screen.findByText('unsupported_schema')
  expect(screen.queryAllByTestId('board-row')).toHaveLength(0)
  expect(screen.getByRole('button', { name: 'retry' })).toBeTruthy()
})

it('visually selects only the pressed evidence mode with the incumbent active style', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, status: 200,
    json: async () => envelope(url.includes('research=true') ? fixture : gate),
  })))
  mount()
  await screen.findByText(/latest WF research run each/)
  const publicButton = screen.getByRole('button', { name: 'Public WF windows' })
  const gateButton = screen.getByRole('button', { name: 'Gate OOS' })
  expect(publicButton.classList.contains('active')).toBe(true)
  expect(gateButton.classList.contains('active')).toBe(false)
  fireEvent.click(gateButton)
  await screen.findByText(/latest gate run each/)
  expect(publicButton.classList.contains('active')).toBe(false)
  expect(gateButton.classList.contains('active')).toBe(true)
  expect(gateButton.getAttribute('aria-pressed')).toBe('true')
  fireEvent.click(publicButton)
  await screen.findByText(/latest WF research run each/)
  expect(publicButton.classList.contains('active')).toBe(true)
  expect(gateButton.classList.contains('active')).toBe(false)
  expect(publicButton.getAttribute('aria-pressed')).toBe('true')
})
