import type { BoardComparisonContext, StrategyBoardComparisonEvidence, StrategyBoardRow } from '../types'

function exact(value: unknown, keys: string): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value) &&
    Object.keys(value).sort().join(' ') === keys.split(' ').sort().join(' ')
}
function day(v: unknown): v is string {
  if (typeof v !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(v)) return false
  const d = new Date(`${v}T00:00:00Z`)
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === v
}
function number(v: unknown): v is number { return typeof v === 'number' && Number.isFinite(v) }
function positive(v: unknown): v is number { return number(v) && Number.isSafeInteger(v) && v > 0 }
function text(v: unknown): v is string { return typeof v === 'string' && v.trim().length > 0 }
function segment(v: unknown): v is BoardComparisonContext['oos'] {
  return exact(v, 'start end n_bars') && day(v.start) && day(v.end) &&
    v.start <= v.end && positive(v.n_bars) &&
    v.n_bars <= (Date.parse(v.end) - Date.parse(v.start)) / 86400000 + 1
}
const REASONS = new Set([
  'recorded_inputs_unavailable', 'lineage_or_source_unavailable', 'comparison_context_absent',
  'invalid_recorded_context', 'unsupported_data_tier', 'invalid_source_metadata',
  'unsupported_modal_inputs', 'missing_artifact_identity', 'unsupported_metric_schema',
  'invalid_canonical_lineage', 'metric_binding_mismatch', 'execution_context_absent', 'research_record_absent',
])

const SIMULATION_SETTINGS = {
  fixed_fees: 0, min_size: 1e-8, max_size: '+inf', size_granularity: 'nan', reject_prob: 0,
  lock_cash: false, allow_partial: true, raise_reject: false, log: false, price: '+inf',
  val_price: '+inf', call_seq: 'default', ffill_val_price: true, update_value: false, seed: null,
  fillna_close: true, direction: 'both', freq: '1D', group_by: true, engine: 'numba',
  initial_cash_mode: 'fixed', vectorbt_version: '1.0.0',
}
function simulation(value: unknown): boolean {
  return exact(value, Object.keys(SIMULATION_SETTINGS).join(' ')) &&
    Object.entries(SIMULATION_SETTINGS).every(([key, expected]) => value[key] === expected)
}

export function parseCosts(value: unknown): BoardComparisonContext['execution_costs'] | null {
  return exact(value, 'schema_version model fees fees_unit slippage slippage_unit') &&
    value.schema_version === 'execution-costs/v1' && value.model === 'vectorbt.from_orders' &&
    value.fees_unit === 'fraction_of_trade_notional_per_side' &&
    value.slippage_unit === 'adverse_fill_price_fraction_per_side' &&
    number(value.fees) && value.fees >= 0 && number(value.slippage) && value.slippage >= 0
    ? value as unknown as BoardComparisonContext['execution_costs'] : null
}

export interface RecordedProvenance {
  bars_snapshot_id: string
  bars_content_hash: string | null
  execution_costs: BoardComparisonContext['execution_costs']
}

export function parseRecordedProvenance(raw: unknown): RecordedProvenance | null {
  if (!exact(raw, 'status reason value') || raw.status !== 'VALID' || raw.reason !== null ||
      !exact(raw.value, 'bars_snapshot_id bars_content_hash execution_costs') ||
      !text(raw.value.bars_snapshot_id) ||
      (raw.value.bars_content_hash !== null && !text(raw.value.bars_content_hash))) return null
  const costs = parseCosts(raw.value.execution_costs)
  return costs === null ? null : {
    bars_snapshot_id: raw.value.bars_snapshot_id,
    bars_content_hash: raw.value.bars_content_hash as string | null,
    execution_costs: costs,
  }
}

export function parseComparison(value: unknown): StrategyBoardComparisonEvidence | null {
  if (!exact(value, 'status observed_metric_sort_enabled reasons cohort_id context') ||
      !Array.isArray(value.reasons)) return null
  if (value.status === 'UNKNOWN') {
    return value.observed_metric_sort_enabled === false && value.cohort_id === null &&
      value.context === null && value.reasons.length === 1 && REASONS.has(value.reasons[0])
      ? value as unknown as StrategyBoardComparisonEvidence : null
  }
  const c = value.context
  if (value.status !== 'COMPARABLE' || value.observed_metric_sort_enabled !== true ||
      value.reasons.length !== 0 || typeof value.cohort_id !== 'string' ||
      !/^[a-f0-9]{64}$/.test(value.cohort_id) || !exact(c,
        'schema_version protocol metrics timeframe period_start period_end holdout_frac embargo windows oos execution execution_costs snapshot_id content_hash data_tier source dependency_hash') ||
      c.schema_version !== 'research-comparison/v1' ||
      c.protocol !== 'continuous_portfolio_tail_holdout' ||
      c.metrics !== 'net_daily_returns_252_rf0_ddof1_compounded_floored_drawdown/v1' ||
      c.timeframe !== '1d' || !day(c.period_start) || !day(c.period_end) || c.period_start >= c.period_end ||
      !number(c.holdout_frac) || c.holdout_frac <= 0 || c.holdout_frac >= 1 ||
      !number(c.embargo) || !Number.isSafeInteger(c.embargo) || c.embargo < 0 ||
      !segment(c.oos) || !Array.isArray(c.windows) || c.windows.length < 2 || !c.windows.every(segment) ||
      c.data_tier !== 'pilot_real_proxy' || !text(c.snapshot_id) ||
      typeof c.content_hash !== 'string' || !/^[a-f0-9]{64}$/.test(c.content_hash) ||
      !text(c.dependency_hash)) return null
  const segments = [...c.windows, c.oos]
  if (segments.some((s, i) => i > 0 && s.start <= segments[i - 1].end) ||
      segments[0].start < c.period_start || c.oos.end >= c.period_end) return null
  const n = segments.reduce((sum, s) => sum + s.n_bars, 0) + c.embargo
  if (n > (Date.parse(c.period_end) - Date.parse(c.period_start)) / 86400000) return null
  const base = Math.floor((n - c.oos.n_bars - c.embargo) / c.windows.length)
  if (Math.floor(n * c.holdout_frac) !== c.oos.n_bars || base < 5 ||
      c.windows.slice(0, -1).some(w => w.n_bars !== base)) return null
  const e = c.execution, costs = c.execution_costs
  if (!exact(e, 'schema_version decision_lag_bars fill_basis valuation_basis sizing cash_sharing initial_cash symbol_order rebalance price_units simulation') ||
      e.schema_version !== 'replay-execution/v1' || !positive(e.decision_lag_bars) ||
      (e.fill_basis !== 'adjusted_close' && e.fill_basis !== 'adjusted_open') ||
      e.valuation_basis !== e.fill_basis || e.sizing !== 'targetpercent' ||
      !simulation(e.simulation) || e.cash_sharing !== true ||
      !number(e.initial_cash) || e.initial_cash <= 0 || !Array.isArray(e.symbol_order) ||
      !e.symbol_order.length || !e.symbol_order.every(text) || new Set(e.symbol_order).size !== e.symbol_order.length ||
      e.rebalance !== 'every_daily_bar' || e.price_units !== 'vendor_adjusted' ||
      parseCosts(costs) === null) return null
  return value as unknown as StrategyBoardComparisonEvidence
}

// A stable canonical key also detects a server cohort ID reused with conflicting contexts.
export function contextKey(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(contextKey).join(',')}]`
  if (value !== null && typeof value === 'object') return `{${Object.entries(value).sort(
    ([a], [b]) => a.localeCompare(b),
  ).map(([k, v]) => `${JSON.stringify(k)}:${contextKey(v)}`).join(',')}}`
  return JSON.stringify(value)
}

export function selectedMetrics(row: StrategyBoardRow) {
  return Object.hasOwn(row, 'latest_research') ? row.latest_research ?? null : row.latest_gate
}

export type ObservedMetric = 'sharpe_oos' | 'total_return_oos' | 'max_drawdown_oos'
export function observedOrder(rows: StrategyBoardRow[], metric: ObservedMetric): StrategyBoardRow[] {
  return [...rows].sort((a, b) => {
    const x = selectedMetrics(a)?.[metric], y = selectedMetrics(b)?.[metric]
    if (x == null && y == null) return a.strategy_id - b.strategy_id
    if (x == null) return 1
    if (y == null) return -1
    // Drawdowns are negative fractions; the value nearest zero comes first.
    return y - x || a.strategy_id - b.strategy_id
  })
}
