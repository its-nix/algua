// Synthetic API fixture generated through the actual public recorder; never market evidence.
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it } from 'vitest'
import fixture from '../fixtures/public-windows.json'
import { StrategyBoardView } from './StrategyBoard'
import type { StrategyBoardPayload } from '../types'

afterEach(cleanup)
function mount(compact = false, stale = false, payload: unknown = fixture) {
  return render(<MemoryRouter><StrategyBoardView compact={compact} query={{
    data: { ok: true, fetched_at: '2026-01-01T00:00:00Z', stale,
      data: payload as StrategyBoardPayload },
    loading: false, error: null, refetch: () => {},
  }} /></MemoryRouter>)
}
it.each([false, true])('labels full/compact public windows without OOS axes (%s)', compact => {
  mount(compact)
  const row = screen.getByRole('link', { name: /synthetic_alpha public WF window details.*run 1/i })
  expect(row.getAttribute('href')).toBe('/strategy/1?research_run=1')
  expect(row.textContent).toContain('mean Sharpe')
  expect(row.textContent).toContain('min Sharpe')
  expect(row.textContent).toContain('std Sharpe')
  expect(row.textContent).toContain('positive windows')
  expect(row.textContent).not.toMatch(/drawdown|tail OOS|sharpe_oos/)
  // R2 sampling-disclosure regression from independent review session 01a199e3-fb17-77d0-8f0d-71500a557a13.
  expect(screen.getAllByText(/in-sample.*selection.*pre-holdout/i).length).toBeGreaterThan(0)
  expect(screen.getAllByText(/not independent OOS/i).length).toBeGreaterThan(0)
  expect(document.body.textContent).not.toContain('987654.321')
})
it('orders only the explicitly selected public cohort, preserving nodes/focus and legacy UNKNOWN', () => {
  mount()
  fireEvent.click(screen.getByRole('button', { name: /board controls/i }))
  const sort = screen.getByRole('button', { name: 'mean window Sharpe' })
  expect(sort.hasAttribute('disabled')).toBe(true)
  const row = screen.getByRole('link', { name: /synthetic_alpha public WF/i })
  row.focus()
  fireEvent.change(screen.getByRole('combobox', { name: 'comparison cohort' }), {
    target: { value: fixture.rows[0].evidence.comparison.cohort_id },
  })
  fireEvent.click(sort)
  expect(screen.getByRole('link', { name: /synthetic_alpha public WF/i })).toBe(row)
  expect(document.activeElement).toBe(row)
  expect(screen.getByText(/other cohorts and unranked/i)).toBeTruthy()
  expect(screen.getAllByText(/in-sample.*selection.*pre-holdout/i).length).toBeGreaterThan(0)
  expect(screen.queryByRole('button', { name: 'oos sharpe' })).toBeNull()
})
it('disables stale ordering and refuses independently mismatched public declarations', () => {
  const damaged = structuredClone(fixture)
  damaged.rows[0].evidence.public_interval.value!.n_bars += 1
  mount(false, true, damaged)
  fireEvent.click(screen.getByRole('button', { name: /board controls/i }))
  expect(screen.getByRole('button', { name: 'mean window Sharpe' }).hasAttribute('disabled')).toBe(true)
  expect(screen.getAllByText(/evidence INVALID/i).length).toBeGreaterThan(0)
})

it('orders public zero/negative values with stable ties and keeps incompatible contexts unranked', () => {
  const data = structuredClone(fixture)
  const a = data.rows[0], b = data.rows[1]
  const stats = { mean_window_sharpe: -2, min_window_sharpe: -3,
    std_window_sharpe: 1, pct_positive_windows: 0 }
  Object.assign(a.latest_research, stats)
  Object.assign(a.evidence.statistics.value!, stats)
  mount(false, false, data)
  fireEvent.click(screen.getByRole('button', { name: /board controls/i }))
  fireEvent.change(screen.getByRole('combobox', { name: 'comparison cohort' }), {
    target: { value: b.evidence.comparison.cohort_id },
  })
  fireEvent.click(screen.getByRole('button', { name: 'mean window Sharpe' }))
  expect(screen.getAllByTestId('board-row-name').map(e => e.textContent))
    .toEqual(['synthetic_beta', 'synthetic_alpha', 'synthetic_legacy'])
  expect(screen.getAllByTestId('board-row')[0].getAttribute('href')).toBe('/strategy/2?research_run=2')
})
it('refuses a reused cohort ID with independently different public costs', () => {
  const data = structuredClone(fixture)
  const b = data.rows[1]
  b.evidence.comparison.context!.execution_costs.fees = 0.2
  b.recorded_provenance.value!.execution_costs.fees = 0.2
  mount(false, false, data)
  fireEvent.click(screen.getByRole('button', { name: /board controls/i }))
  expect((screen.getByRole('combobox', { name: 'comparison cohort' }) as HTMLSelectElement).options).toHaveLength(1)
  expect(screen.getByRole('button', { name: 'mean window Sharpe' }).hasAttribute('disabled')).toBe(true)
})
