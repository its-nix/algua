/** The Strategy page's forward-gate card (`paper promote`). A RECORDED evaluation for the
 * current paper stint is the authority and is shown as recorded; without one, the card is an
 * estimate from ticks against the default thresholds, and says so. */
import type { GateCheck, GateRow } from '../types'
import { finite, fmtPct, ratio, realized, type DayPoint } from './strategyCurve'

// `paper promote` defaults (algua/research/forward_gates.py).
export const FORWARD_DEFAULTS = {
  minObservations: 63, minCoverage: 0.9, degradationFactor: 0.5, sharpeFloor: 0.3, maxDrawdown: 0.25,
}

export interface GateCheckView { label: string; value: string; passed: boolean }
export interface ForwardGateView {
  kind: 'recorded' | 'estimate'
  /** The recorded evaluation's verdict and time (null for an estimate). */
  passed: boolean | null
  asOf: string | null
  observations: number
  required: number
  drawdownLimit: number
  checks: GateCheckView[]
}

const truthy = (v: unknown) => v === true || v === 1

/** The forward evaluation that speaks for the current stint: on forward_tested the newest one
 * (the pass that promoted it); on paper only one made since paper intake. */
export function currentForwardRow(
  rows: GateRow[] | undefined, stage: string, laneEntry: string | null,
): GateRow | null {
  const row = rows?.[0]
  if (row === undefined) return null
  if (stage === 'forward_tested') return row
  return laneEntry !== null && row.created_at >= laneEntry ? row : null
}

/** Named metric checks, in reading order: label (given the formatted threshold) and value format. */
const METRICS: { name: string; label: (t: string) => string; fmt: (v: number) => string }[] = [
  { name: 'min_forward_observations', label: (t) => `At least ${t} sessions`, fmt: (v) => String(Math.round(v)) },
  { name: 'realized_sharpe', label: (t) => `Sharpe at least ${t}`, fmt: (v) => ratio(v) },
  { name: 'realized_sharpe_lcb', label: (t) => `Sharpe 95% lower bound at least ${t}`, fmt: (v) => ratio(v) },
  { name: 'max_forward_drawdown', label: (t) => `Drawdown under ${t}`, fmt: (v) => fmtPct(Math.abs(v), 1) },
  { name: 'session_coverage', label: (t) => `Session coverage ${t}`, fmt: (v) => fmtPct(v) },
  { name: 'min_forward_vol', label: (t) => `Volatility at least ${t}`, fmt: (v) => fmtPct(v, 1) },
]

const thresholdText = (name: string, t: number) =>
  name === 'min_forward_observations' ? String(Math.round(t))
    : name.startsWith('realized_sharpe') ? ratio(t) : fmtPct(Math.abs(t))

/** The recorded evaluation exactly as `registry gates` projected it: each metric check with its
 * value, threshold and verdict; every other (integrity/account) check folded into one row. */
export function recordedForwardGate(row: GateRow): ForwardGateView {
  const checks: GateCheck[] = row.decision?.checks ?? []
  const byName = new Map(checks.map((c) => [c.name, c]))
  const views: GateCheckView[] = []
  for (const m of METRICS) {
    const c = byName.get(m.name)
    if (c === undefined) continue
    const t = finite(c.threshold)
    const v = finite(c.value)
    views.push({
      label: m.label(t === null ? '—' : thresholdText(m.name, t)),
      value: v === null ? '—' : m.fmt(v),
      passed: c.passed === true,
    })
  }
  const others = checks.filter((c) => !METRICS.some((m) => m.name === c.name))
  if (others.length > 0) {
    const ok = others.filter((c) => c.passed === true).length
    views.push({ label: 'Integrity and account checks', value: `${ok} of ${others.length}`, passed: ok === others.length })
  }
  return {
    kind: 'recorded',
    passed: truthy(row.passed),
    asOf: row.created_at,
    observations: finite(row.n_forward_observations) ?? finite(byName.get('min_forward_observations')?.value) ?? 0,
    required: finite(row.min_forward_observations) ?? FORWARD_DEFAULTS.minObservations,
    drawdownLimit: Math.abs(finite(row.max_forward_drawdown) ?? FORWARD_DEFAULTS.maxDrawdown),
    checks: views,
  }
}

/** The one-sided 95% lower bound on the annualized Sharpe, with the Lo/Mertens non-normal
 * standard error `forward_gates._forward_sharpe_lcb` uses; null when degenerate. */
export function sharpeLcb(points: DayPoint[]): number | null {
  const eq = points.map((p) => p.equity)
  const rets = eq.slice(1).map((v, i) => v / eq[i] - 1).filter(Number.isFinite)
  const t = rets.length
  if (t < 3) return null
  const mean = rets.reduce((a, b) => a + b, 0) / t
  const sd = Math.sqrt(rets.reduce((a, x) => a + (x - mean) ** 2, 0) / (t - 1))
  if (!(sd > 0)) return null
  const m2 = rets.reduce((a, x) => a + (x - mean) ** 2, 0) / t
  const skew = rets.reduce((a, x) => a + (x - mean) ** 3, 0) / t / m2 ** 1.5
  const kurt = rets.reduce((a, x) => a + (x - mean) ** 4, 0) / t / m2 ** 2
  const sr = mean / sd
  const v = 1 - skew * sr + ((kurt - 1) / 4) * sr * sr
  if (!(v > 0)) return null
  const lcb = (sr - 1.6448536 * Math.sqrt(v / (t - 1))) * Math.sqrt(252)
  return Number.isFinite(lcb) ? lcb : null
}

/** Weekdays from `from` to `to` inclusive (holidays not removed, so coverage reads low, never
 * high). */
export function weekdaysBetween(from: string, to: string): number {
  const d = new Date(`${from}T00:00:00Z`)
  const end = new Date(`${to}T00:00:00Z`)
  let n = 0
  while (d <= end) {
    if (d.getUTCDay() !== 0 && d.getUTCDay() !== 6) n += 1
    d.setUTCDate(d.getUTCDate() + 1)
  }
  return n
}

/** An ESTIMATE from ticks against the DEFAULT thresholds (never a possibly-relaxed recorded run's).
 * The Sharpe bar is the untaxed first-look `max(0.5 × holdout, 0.3)`. */
export function estimateForwardGate(lane: DayPoint[], holdoutSharpe: number | null): ForwardGateView {
  const d = FORWARD_DEFAULTS
  const r = realized(lane)
  const checks: GateCheckView[] = []
  if (holdoutSharpe !== null) {
    const bar = Math.max(d.degradationFactor * holdoutSharpe, d.sharpeFloor)
    const lcb = sharpeLcb(lane)
    checks.push({ label: `Sharpe at least ${ratio(bar)}`, value: ratio(r.sharpe),
      passed: r.sharpe !== null && r.sharpe >= bar })
    checks.push({ label: `Sharpe 95% lower bound at least ${ratio(bar)}`, value: ratio(lcb),
      passed: lcb !== null && lcb >= bar })
  }
  const dd = r.maxDrawdown === null ? null : Math.abs(r.maxDrawdown)
  checks.push({ label: `Drawdown under ${fmtPct(d.maxDrawdown)}`, value: dd === null ? '—' : fmtPct(dd, 1),
    passed: dd !== null && dd <= d.maxDrawdown })
  const first = lane[0]
  const last = lane.at(-1)
  const coverage = first && last ? lane.length / Math.max(weekdaysBetween(first.date, last.date), 1) : null
  checks.push({ label: `Session coverage ${fmtPct(d.minCoverage)}`,
    value: coverage === null ? '—' : fmtPct(Math.min(coverage, 1)), passed: coverage !== null && coverage >= d.minCoverage })
  return {
    kind: 'estimate', passed: null, asOf: null, observations: Math.max(lane.length - 1, 0),
    required: d.minObservations, drawdownLimit: d.maxDrawdown, checks,
  }
}
