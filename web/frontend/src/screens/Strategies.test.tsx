import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { clearFetchCache } from '../api'
import type {
  ApiEnvelope, BookPayload, ListPayload, SeriesPayload, SeriesRow, StrategyRecord,
} from '../types'
import Strategies from './Strategies'

const env = <T,>(data: T): ApiEnvelope<T> =>
  ({ ok: true, data, fetched_at: '2026-11-13T21:00:00Z', stale: false })

const rec = (id: number, name: string, stage: string): StrategyRecord => ({
  id, name, stage, family: null, tags: [], author: 'agent',
  hypothesis_status: 'untested', derived_from: null, description: null,
})

const STRATEGIES = [
  rec(1, 'paper_one', 'paper'),
  rec(2, 'live_one', 'live'),
  rec(3, 'ft_one', 'forward_tested'),
  rec(4, 'live_two', 'live'),
  rec(5, 'cand_one', 'candidate'),
  rec(6, 'idea_one', 'idea'),
  rec(7, 'bt_one', 'backtested'),
]

const book: BookPayload = {
  ok: true, capacity: 64, allocated: 4, count_headroom: 60, sum_allocations: 6600,
  unallocated_operational: [], live_allocated: 2,
  slices: [
    { strategy: 'live_one', stage: 'live', capital: 1800, last_equity: 1874, effective_ts: '2026-10-01', actor: 'human' },
    { strategy: 'live_two', stage: 'live', capital: 1800, last_equity: 1777, effective_ts: '2026-10-01', actor: 'human' },
    { strategy: 'ft_one', stage: 'forward_tested', capital: 1200, last_equity: 1220, effective_ts: '2026-10-01', actor: 'agent' },
    { strategy: 'paper_one', stage: 'paper', capital: 1550, last_equity: 1584, effective_ts: '2026-10-01', actor: 'agent' },
  ],
}

/** Weekday ticks from 1000 to `end`. */
function rows(n: number, end: number): SeriesRow[] {
  const out: SeriesRow[] = []
  const d = new Date('2026-09-01T20:00:00Z')
  while (out.length < n) {
    if (d.getUTCDay() !== 0 && d.getUTCDay() !== 6) {
      const i = out.length
      out.push({
        id: i, tick_ts: d.toISOString(), recorded_at: d.toISOString(),
        equity: 1000 + ((end - 1000) * i) / (n - 1), peak_equity: null, reconcile_ok: true,
      })
    }
    d.setUTCDate(d.getUTCDate() + 1)
  }
  return out
}

function series(name: string, lane: 'paper' | 'live', r: SeriesRow[]): ApiEnvelope<SeriesPayload> {
  return env({
    strategy: name, lane_filter: null,
    series: { paper: lane === 'paper' ? r : [], live: lane === 'live' ? r : null },
    truncated: { paper: false, live: false }, n_legacy_excluded: 0, n_unparseable: 0, n_invalid_lane: 0,
  })
}

const SERIES: Record<string, ApiEnvelope<SeriesPayload>> = {
  live_one: series('live_one', 'live', rows(42, 1041)),
  live_two: series('live_two', 'live', rows(39, 987)),
  ft_one: series('ft_one', 'paper', rows(64, 1017)),
  paper_one: series('paper_one', 'paper', rows(42, 1022)),
}

beforeEach(() => {
  clearFetchCache()
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const m = url.match(/^\/api\/strategy\/([^/]+)\/series$/)
    const body = url === '/api/strategies' ? env<ListPayload<StrategyRecord>>({ data: STRATEGIES })
      : url === '/api/book' ? env(book)
        : m ? SERIES[decodeURIComponent(m[1])]
          : undefined
    return body === undefined
      ? { ok: false, status: 404, json: async () => ({ error: 'nope' }) }
      : { ok: true, status: 200, json: async () => body }
  }) as unknown as typeof fetch)
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

function mount() {
  return render(<MemoryRouter initialEntries={['/strategies']}><Strategies /></MemoryRouter>)
}

it('Strategies groups operating rows by stage in order Live, Forward tested, Paper', async () => {
  mount()
  expect(await screen.findByRole('heading', { name: 'Strategies', level: 1 })).toBeTruthy()
  await screen.findByText('live_one')
  const groups = screen.getAllByTestId('stage-group')
  expect(groups.map((g) => g.getAttribute('data-stage'))).toEqual(['live', 'forward_tested', 'paper'])
  expect(within(groups[0]).getByText('Live')).toBeTruthy()
  expect(within(groups[1]).getByText('Forward tested')).toBeTruthy()
  expect(within(groups[2]).getByText('Paper')).toBeTruthy()
  expect(within(groups[0]).getAllByRole('link').map((a) => a.getAttribute('href')))
    .toEqual(['/s/live_one', '/s/live_two'])
  // Segment counts: operating = live + forward_tested + paper.
  expect(screen.getByRole('button', { name: /Operating 4/ }).getAttribute('aria-pressed')).toBe('true')
  expect(screen.getByRole('button', { name: /Candidates 1/ })).toBeTruthy()
  expect(screen.getByRole('button', { name: /Research 2/ })).toBeTruthy()
  // Row content: "Day N · $slice slice", value from the newest tick, P&L since the stage began.
  const row = screen.getByText('live_one').closest('a')!
  await waitFor(() => expect(row.textContent).toContain('Day 41 · $1,800 slice'))
  expect(row.textContent).toContain('$1,041')
  expect(within(row).getByTestId('pnl-chip').textContent).toBe('+4.1%')
  expect(row.querySelector('svg.equity-line')?.getAttribute('width')).toBe('60')
})

it('negative P&L chip is red', async () => {
  mount()
  const row = (await screen.findByText('live_two')).closest('a')!
  await waitFor(() => expect(within(row).getByTestId('pnl-chip').textContent).toBe('−1.3%'))
  const chip = within(row).getByTestId('pnl-chip')
  expect(chip.getAttribute('data-tone')).toBe('down')
  expect(chip.style.background).toBe('var(--red)')
  expect(within(screen.getByText('live_one').closest('a')!).getByTestId('pnl-chip').style.background)
    .toBe('var(--green)')
})

it('a row whose series fetch failed says so instead of going blank', async () => {
  const saved = SERIES.paper_one
  delete SERIES.paper_one
  try {
    mount()
    const row = (await screen.findByText('paper_one')).closest('a')!
    await waitFor(() => expect(row.textContent).toContain('Equity unavailable'))
    expect(row.textContent).toContain('$1,550 slice')
  } finally {
    SERIES.paper_one = saved
  }
})

it('Research segment links to the moved Leaderboard and Research views', async () => {
  mount()
  fireEvent.click(await screen.findByRole('button', { name: /Research 2/ }))
  expect(screen.getByRole('link', { name: /Leaderboard/ }).getAttribute('href'))
    .toBe('/strategies/research/leaderboard')
  expect(screen.getByRole('link', { name: /Idea pool/ }).getAttribute('href')).toBe('/strategies/research')
  expect(screen.getByText('idea_one')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: /Candidates 1/ }))
  expect(screen.getByText('cand_one').closest('a')?.getAttribute('href')).toBe('/s/cand_one')
})
