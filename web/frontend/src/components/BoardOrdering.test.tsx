// Synthetic read-model controls; economic values here are not evaluation results.
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it } from 'vitest'
import { StrategyBoardView } from './StrategyBoard'
import type { StrategyBoardPayload } from '../types'

const context = {
  schema_version: 'research-comparison/v1', protocol: 'continuous_portfolio_tail_holdout',
  metrics: 'net_daily_returns_252_rf0_ddof1_compounded_floored_drawdown/v1',
  timeframe: '1d', period_start: '2024-01-01', period_end: '2024-12-31',
  holdout_frac: 0.2, embargo: 20,
  windows: [{ start: '2024-01-02', end: '2024-05-01', n_bars: 90 },
    { start: '2024-05-02', end: '2024-09-01', n_bars: 90 }],
  oos: { start: '2024-10-01', end: '2024-12-30', n_bars: 50 },
  execution: { schema_version: 'replay-execution/v1', decision_lag_bars: 1,
    fill_basis: 'adjusted_close', valuation_basis: 'adjusted_close', sizing: 'targetpercent', cash_sharing: true,
    initial_cash: 100, symbol_order: ['AAPL', 'MSFT'], rebalance: 'every_daily_bar',
    price_units: 'vendor_adjusted', simulation: {
      fixed_fees: 0, min_size: 1e-8, max_size: '+inf', size_granularity: 'nan', reject_prob: 0,
      lock_cash: false, allow_partial: true, raise_reject: false, log: false, price: '+inf',
      val_price: '+inf', call_seq: 'default', ffill_val_price: true, update_value: false, seed: null,
      fillna_close: true, direction: 'both', freq: '1D', group_by: true, engine: 'numba',
      initial_cash_mode: 'fixed', vectorbt_version: '1.0.0',
    } },
  execution_costs: { schema_version: 'execution-costs/v1', model: 'vectorbt.from_orders',
    fees: 0.0005, fees_unit: 'fraction_of_trade_notional_per_side', slippage: 0,
    slippage_unit: 'adverse_fill_price_fraction_per_side' },
  snapshot_id: 'recorded-snapshot', content_hash: 'b'.repeat(64), data_tier: 'pilot_real_proxy',
  dependency_hash: 'recorded-dependencies',
  source: { schema_version: 'pilot-provenance/v1', data_tier: 'pilot_real_proxy',
    universe_method: 'current_survivors', coverage_start: '2024-01-02', coverage_end: '2024-12-30',
    provider: 'yfinance', limitations: ['adjusted_close_vendor_revisable', 'corporate_actions_unverified',
      'delisted_names_absent', 'event_timing_unavailable', 'historical_market_cap_unavailable',
      'point_in_time_universe_unavailable', 'survivorship_biased_selection'] },
}

function row(id: number, sharpe: number | null, cohort = 'a'.repeat(64)) {
  return { strategy_id: id, name: `strategy_${id}`, family: 'momentum', stage: id === 4 ? 'live' : 'backtested',
    latest_gate: { run_id: id + 100, created_at: '2026-01-01T00:00:00Z', passed: false,
      sharpe_oos: sharpe, total_return_oos: 0, max_drawdown_oos: -0.1, n_obs_oos: 50,
      mean_window_sharpe: 99, min_window_sharpe: -5, pct_positive_windows: 0.5 },
    recorded_provenance: { status: 'VALID', reason: null, value: {
      bars_snapshot_id: context.snapshot_id, bars_content_hash: context.content_hash,
      execution_costs: structuredClone(context.execution_costs),
    } },
    evidence: { run_id: id + 100,
      evaluation: { status: 'VALID', reason: null, value: { period_start: '2024-01-01',
        period_end: '2024-12-31', timeframe: '1d', metric_schema_version: 1 } },
      oos_interval: { status: 'VALID', reason: null, value: {
        holdout_start: '2024-10-01', holdout_end: '2024-12-30', n_bars: 50 } },
      snapshot_provenance: { status: 'VALID', reason: null, value: structuredClone(context.source) },
      comparison: { status: 'COMPARABLE', observed_metric_sort_enabled: true,
        reasons: [], cohort_id: cohort, context: structuredClone(context) } } }
}

function mount(rows: unknown[], stale = false, error: Error | null = null, compact = false) {
  const data = { schema_version: 'strategy-board/v1', evidence_schema_version: 'strategy-board-evidence/v2',
    count: rows.length, rows } as StrategyBoardPayload
  return render(<MemoryRouter><StrategyBoardView compact={compact} query={{ data: { ok: true, fetched_at: '2026-01-01T00:00:00Z',
    stale, data }, error, loading: false, refetch: () => {} }} /></MemoryRouter>)
}
const names = () => screen.getAllByTestId('board-row-name').map(e => e.textContent)
afterEach(cleanup)

it('requires explicit cohort selection and orders only that cohort, preserving zero, negatives and ties', () => {
  mount([row(1, -2), row(2, 0), row(3, 0), row(4, 99, 'c'.repeat(64)), row(5, null)])
  fireEvent.click(screen.getByRole('button', { name: /board controls/i }))
  const sort = screen.getByRole('button', { name: 'oos sharpe' })
  expect(sort.hasAttribute('disabled')).toBe(true)
  fireEvent.change(screen.getByRole('combobox', { name: 'comparison cohort' }), { target: { value: 'a'.repeat(64) } })
  fireEvent.click(sort)
  expect(names()).toEqual(['strategy_2', 'strategy_3', 'strategy_1', 'strategy_4', 'strategy_5'])
  expect(screen.getByText(/other cohorts and unranked/i)).toBeTruthy()
  expect(screen.getAllByTestId('board-row')[0].getAttribute('href')).toBe('/strategy/2')
  expect(screen.getAllByText(/NONPIT.*current-survivor/i)[0]).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'lifecycle' }))
  expect(names()).toEqual(['strategy_1', 'strategy_2', 'strategy_3', 'strategy_4', 'strategy_5'])
})

it.each(['cost', 'period'])('refuses mismatched %s contexts even if cohort identifiers match', field => {
  const second = row(2, 99)
  if (field === 'cost') {
    second.evidence.comparison.context.execution_costs.fees = 0.1
    second.recorded_provenance.value.execution_costs.fees = 0.1
  }
  else {
    second.evidence.comparison.context.period_start = '2023-12-31'
    second.evidence.evaluation.value.period_start = '2023-12-31'
  }
  mount([row(1, 0), second])
  fireEvent.click(screen.getByRole('button', { name: /board controls/i }))
  expect((screen.getByRole('combobox', { name: 'comparison cohort' }) as HTMLSelectElement).options).toHaveLength(1)
  expect(screen.getByRole('button', { name: 'oos sharpe' }).hasAttribute('disabled')).toBe(true)
})

it('refuses unsupported comparison fields and source/interval disagreement', () => {
  const malformed = row(1, 1)
  Object.assign(malformed.evidence.comparison.context.execution, { requested_allow_fractional: false })
  const mismatched = row(2, 2)
  mismatched.evidence.oos_interval.value.holdout_end = '2024-12-29'
  mount([malformed, mismatched])
  fireEvent.click(screen.getByRole('button', { name: /board controls/i }))
  expect((screen.getByRole('combobox', { name: 'comparison cohort' }) as HTMLSelectElement).options).toHaveLength(1)
  expect(screen.getByRole('button', { name: 'oos sharpe' }).hasAttribute('disabled')).toBe(true)
})


it('rejects an array masquerading as an effective fill basis', () => {
  const malformed = row(1, 1)
  Object.assign(malformed.evidence.comparison.context.execution, { fill_basis: ['adjusted_close'] })
  const second = structuredClone(malformed)
  second.strategy_id = 2
  mount([malformed, second])
  fireEvent.click(screen.getByRole('button', { name: /board controls/i }))
  expect((screen.getByRole('combobox', { name: 'comparison cohort' }) as HTMLSelectElement).options).toHaveLength(1)
})


it.each([['stale', true, null], ['error', false, new Error('refresh failed')]] as const)(
  'keeps %s evidence visible without enabling ordering', (_label, stale, error) => {
    mount([row(1, -2), row(2, 0)], stale, error)
    fireEvent.click(screen.getByRole('button', { name: /board controls/i }))
    fireEvent.change(screen.getByRole('combobox', { name: 'comparison cohort' }),
      { target: { value: 'a'.repeat(64) } })
    expect(screen.getByRole('button', { name: 'oos sharpe' }).hasAttribute('disabled')).toBe(true)
    expect(names()).toEqual(['strategy_1', 'strategy_2'])
  },
)

it('retains stable row DOM identity and focus when ordering changes', () => {
  mount([row(1, -2), row(2, 0)])
  fireEvent.click(screen.getByRole('button', { name: /board controls/i }))
  fireEvent.change(screen.getByRole('combobox', { name: 'comparison cohort' }),
    { target: { value: 'a'.repeat(64) } })
  const link = screen.getAllByTestId('board-row')[0]
  link.focus()
  fireEvent.click(screen.getByRole('button', { name: 'oos sharpe' }))
  expect(screen.getAllByTestId('board-row')[1]).toBe(link)
  expect(document.activeElement).toBe(link)
})


it.each(['total_return_oos', 'max_drawdown_oos'] as const)('orders observed %s descending within one cohort', metric => {
  const rows = [row(1, 99), row(2, -99), row(3, null)]
  rows[0].latest_gate[metric] = -0.2
  rows[1].latest_gate[metric] = -0.1
  rows[2].latest_gate[metric] = 0
  mount(rows)
  fireEvent.click(screen.getByRole('button', { name: /board controls/i }))
  fireEvent.change(screen.getByRole('combobox', { name: 'comparison cohort' }),
    { target: { value: 'a'.repeat(64) } })
  fireEvent.click(screen.getByRole('button', { name: metric === 'total_return_oos' ? 'oos return' : 'oos drawdown' }))
  expect(names()).toEqual(['strategy_3', 'strategy_2', 'strategy_1'])
})


it.each(['absent', 'invalid', 'snapshot', 'content_hash', 'costs'])(
  'independent review: refuses conflicting recorded provenance (%s)', mutation => {
    const rows = [row(1, -2), row(2, 0)]
    const provenance = { status: 'VALID', reason: null, value: {
      bars_snapshot_id: context.snapshot_id, bars_content_hash: context.content_hash,
      execution_costs: structuredClone(context.execution_costs),
    } }
    Object.assign(rows[0], { recorded_provenance: structuredClone(provenance) })
    const other = structuredClone(provenance)
    if (mutation === 'invalid') Object.assign(other, { status: 'INVALID', reason: 'snapshot_binding_mismatch', value: null })
    else if (mutation === 'snapshot') other.value.bars_snapshot_id = 'different-recorded-snapshot'
    else if (mutation === 'content_hash') other.value.bars_content_hash = 'f'.repeat(64)
    else if (mutation === 'costs') other.value.execution_costs.fees = 0.1
    if (mutation === 'absent') Reflect.deleteProperty(rows[1], 'recorded_provenance')
    else Object.assign(rows[1], { recorded_provenance: other })
    mount(rows)
    fireEvent.click(screen.getByRole('button', { name: /board controls/i }))
    fireEvent.change(screen.getByRole('combobox', { name: 'comparison cohort' }),
      { target: { value: 'a'.repeat(64) } })
    for (const name of ['oos sharpe', 'oos return', 'oos drawdown']) {
      expect(screen.getByRole('button', { name }).hasAttribute('disabled')).toBe(true)
    }
    expect(names()).toEqual(['strategy_1', 'strategy_2'])
    expect(screen.getByText(/evidence INVALID.*run-bound response malformed/i)).toBeTruthy()
  },
)

it('puts the short cohort identity first in the native option label', () => {
  mount([row(1, -2), row(2, 0)])
  fireEvent.click(screen.getByRole('button', { name: /board controls/i }))
  const select = screen.getByRole('combobox', { name: 'comparison cohort' }) as HTMLSelectElement
  expect(select.options[1].textContent?.trim()).toMatch(/^aaaaaaaa · 1d/)
})

it('directs compact-board comparison to the leaderboard without promising a hidden selector', () => {
  mount([row(1, -2), row(2, 0)], false, null, true)
  expect(screen.getByText(/Comparison is available on the leaderboard/i)).toBeTruthy()
  expect(screen.queryByText(/Select a matching cohort/i)).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: /board controls/i }))
  expect(screen.queryByRole('combobox')).toBeNull()
  for (const name of ['oos sharpe', 'oos return', 'oos drawdown']) {
    expect(screen.getByRole('button', { name }).hasAttribute('disabled')).toBe(true)
  }
})
