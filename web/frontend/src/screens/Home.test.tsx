import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { clearFetchCache } from '../api'
import type {
  ApiEnvelope, BookPayload, EquityPayload, ListPayload, StrategyRecord, TriagePayload,
} from '../types'
import Home from './Home'

const env = <T,>(data: T): ApiEnvelope<T> =>
  ({ ok: true, data, fetched_at: '2026-11-13T21:00:00Z', stale: false })

/** `n` weekday sessions ending on `end`. */
function sessions(n: number, end = '2026-11-13'): string[] {
  const out: string[] = []
  const d = new Date(`${end}T00:00:00Z`)
  while (out.length < n) {
    const day = d.getUTCDay()
    if (day !== 0 && day !== 6) out.unshift(d.toISOString().slice(0, 10))
    d.setUTCDate(d.getUTCDate() - 1)
  }
  return out
}

function equity(n: number): EquityPayload {
  const points = sessions(n).map((session, i) => ({ session, pnl: i * 10, equity: 15000 + i * 10 }))
  return {
    ok: true, lane_filter: null, points,
    current_equity: n ? 15734.3 : 0, change_today: n ? 184.3 : 0,
    last_session: points.at(-1)?.session ?? null, truncated: false,
  }
}

const emptyTriage: TriagePayload = {
  ok: true, items: [], sources: { fleet: true, ops: true, book: true },
  headline: { fleet_ok: 3, fleet_total: 3, book_allocated: 2, book_capacity: 64, loops_alerting: 0 },
  fetched_at: '2026-11-13T21:00:00Z', stale: false,
}

const alertTriage: TriagePayload = {
  ...emptyTriage,
  items: [{
    kind: 'strategy', severity: 3, title: 'orderly_six_day_rebound breach',
    detail: 'realized Sharpe below its floor', since: null, route: '/s/orderly_six_day_rebound',
  }],
}

const book: BookPayload = {
  ok: true, capacity: 64, allocated: 2, count_headroom: 62, sum_allocations: 3600,
  unallocated_operational: [], live_allocated: 1,
  slices: [
    { strategy: 'a', stage: 'live', capital: 1800, last_equity: 1850, effective_ts: '2026-10-01', actor: 'human' },
    { strategy: 'b', stage: 'paper', capital: 1800, last_equity: 1790, effective_ts: '2026-10-01', actor: 'agent' },
  ],
}

const rec = (id: number, stage: string): StrategyRecord => ({
  id, name: `s${id}`, stage, family: null, tags: [], author: 'agent',
  hypothesis_status: 'untested', derived_from: null, description: null,
})
const strategies: ListPayload<StrategyRecord> = {
  data: [rec(1, 'live'), rec(2, 'paper'), rec(3, 'paper'), rec(4, 'candidate'), rec(5, 'idea'), rec(6, 'backtested')],
}

function mount(opts: { eq?: EquityPayload; triage?: TriagePayload } = {}) {
  const eq = opts.eq ?? equity(400)
  const triage = opts.triage ?? emptyTriage
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const body = url.startsWith('/api/equity') ? env(eq)
      : url.startsWith('/api/triage') ? triage
        : url.startsWith('/api/book') ? env(book)
          : url.startsWith('/api/strategies') ? env(strategies) : null
    return { ok: body !== null, status: body ? 200 : 404, json: async () => body }
  }) as unknown as typeof fetch)
  return render(<MemoryRouter><Home /></MemoryRouter>)
}

beforeEach(() => clearFetchCache())
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('Home renders big number and curve from fixture equity', async () => {
  const { container } = mount()
  expect(await screen.findByText('$15,734.30')).toBeTruthy()
  expect(screen.getByText('Portfolio equity')).toBeTruthy()
  // The last session is not today (change_today is then 0 by construction), so the change line
  // shows that session's own move and says which session it is from.
  expect(screen.getByText(/\$10\.00/)).toBeTruthy()
  expect(screen.getByText('as of 2026-11-13')).toBeTruthy()
  const line = container.querySelector('svg.equity-line')
  expect(line).not.toBeNull()
  expect(line?.querySelector('path[stroke]')).not.toBeNull()
  // Stage tiles count the registry and link to Strategies.
  expect((await screen.findByRole('link', { name: /1\s*Live/ })).getAttribute('href')).toBe('/strategies')
  expect(screen.getByRole('link', { name: /2\s*Research/ })).toBeTruthy()
  // Capital split by lane.
  expect(screen.getAllByText('$1,800').length).toBe(2)
})

it('uses change_today with "Today" when the newest session is today, red when negative', async () => {
  const today = new Date().toISOString().slice(0, 10)
  const points = [{ session: '2000-01-03', pnl: 0, equity: 100 }, { session: today, pnl: -5, equity: 95 }]
  mount({ eq: { ...equity(2), points, last_session: today, current_equity: 95, change_today: -184.3 } })
  const change = await screen.findByText(/\$184\.30/)
  expect(change.className).toContain('down')
  expect(change.textContent).toContain('▼')
  expect(screen.getByText('Today')).toBeTruthy()
})

it('Home shows no attention card when triage is empty', async () => {
  mount()
  await screen.findByText('$15,734.30')
  await screen.findByText('Capital')
  expect(screen.queryByTestId('attention')).toBeNull()
})

it('Home shows the attention card when triage has items', async () => {
  mount({ triage: alertTriage })
  const card = await screen.findByTestId('attention')
  expect(card.textContent).toContain('orderly_six_day_rebound')
  expect(card.querySelector('a')?.getAttribute('href')).toBe('/s/orderly_six_day_rebound')
})

it('Home shows empty state "No equity yet" when points is []', async () => {
  mount({ eq: equity(0) })
  expect(await screen.findByText('No equity yet')).toBeTruthy()
})

it('range pill switch filters points by date', async () => {
  const { container } = mount()
  await screen.findByText('$15,734.30')
  const count = () => Number(container.querySelector('svg.equity-line')?.getAttribute('data-points'))
  expect(screen.getByRole('button', { name: '3M' }).getAttribute('aria-pressed')).toBe('true')
  const threeMonths = count()
  expect(threeMonths).toBeGreaterThan(55)
  expect(threeMonths).toBeLessThan(70)
  fireEvent.click(screen.getByRole('button', { name: '1W' }))
  expect(count()).toBeLessThanOrEqual(6)
  fireEvent.click(screen.getByRole('button', { name: 'All' }))
  expect(count()).toBe(400)
})

it('lane picker refetches equity for the chosen lane', async () => {
  mount()
  await screen.findByText('$15,734.30')
  fireEvent.change(screen.getByLabelText('Lane'), { target: { value: 'paper' } })
  await screen.findByText('$15,734.30')
  const calls = (fetch as unknown as { mock: { calls: [string][] } }).mock.calls.map((c) => c[0])
  expect(calls).toContain('/api/equity?lane=paper')
})
