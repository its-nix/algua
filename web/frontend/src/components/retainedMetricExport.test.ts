import { expect, it } from 'vitest'
import { researchWindows, retainedMetricsCSV, retainedParameters } from './retainedMetricExport'

const windows = [
  { start: '2025-01-02', end: '2025-03-28', n_bars: 60, total_return: -0.12, sharpe: -0.4 },
  { start: '2025-04-01', end: '2025-06-30', n_bars: 63, total_return: null, sharpe: null },
]
const inputs = { public_window_record: { schema_version: 'public-wf-windows/v1', windows },
  params: { evaluation_role: 'benchmark' }, holdout_returns: 'PRIVATE_SENTINEL' }

it('reads only declared public window fields and preserves missing measurements', () => {
  expect(researchWindows(inputs)).toEqual(windows)
  expect(researchWindows({ window_metrics: windows })).toBeNull()
})

it('refuses malformed dates, nonfinite metrics and invalid observation counts', () => {
  for (const change of [{ start: '2025-02-30' }, { sharpe: Infinity }, { n_bars: 0 }]) {
    expect(researchWindows({ public_window_record: { schema_version: 'public-wf-windows/v1',
      windows: [windows[0], { ...windows[1], ...change }] } })).toBeNull()
  }
})

it('exports explicit scalar/window measurements with source and role, never hidden payloads', () => {
  const csv = retainedMetricsCSV('cycle-1', [{ source_ref: 'scratch:cycle-1:runs:2',
    kind: 'sweep_trial', strategy_name: 'control', inputs,
    metrics: { mean_window_sharpe: 0.3 }, extra_metrics: {} }])
  expect(csv).toContain('"2025-01-02","2025-03-28","total_return","-0.12"')
  expect(csv).toContain('"2025-04-01","2025-06-30","sharpe",""')
  expect(csv).toContain('"benchmark"')
  expect(csv).not.toMatch(/PRIVATE_SENTINEL|holdout_returns/)
})

it('escapes CSV fields and neutralizes formula-bearing worker strings without altering numbers', () => {
  const csv = retainedMetricsCSV('cycle', [{ source_ref: 'scratch:cycle:runs:1',
    kind: 'backtest', strategy_name: '=HYPERLINK("x")', inputs: {},
    metrics: { total_return_is: -0.25 }, extra_metrics: {} }])
  expect(csv).toContain('"\'=HYPERLINK(""x"")"')
  expect(csv).toContain('"-0.25"')
})

it('retains conflicting extra metrics separately and resolves only fixed grid coordinates', () => {
  expect(retainedParameters({ grid: { evaluation_role: ['benchmark'], lookback: [20, 60] } }))
    .toEqual({ evaluation_role: 'benchmark' })
  const csv = retainedMetricsCSV('cycle', [{ source_ref: '@source', kind: 'backtest',
    strategy_name: 'strategy', inputs, metrics: { sharpe_is: 0.2 },
    extra_metrics: { sharpe_is: 99, '+formula': 1 } }])
  expect(csv).toContain('"sharpe_is","0.2"')
  expect(csv).toContain('"extra.sharpe_is","99"')
  expect(csv).toContain('"\'@source"')
  expect(csv).toContain('"\'+formula"')
  expect(csv).not.toContain('"2025-01-02"') // Wrong-kind window payload is not exported.
})
