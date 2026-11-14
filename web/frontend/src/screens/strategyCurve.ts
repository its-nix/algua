/** Pure helpers behind the Strategies list and the Strategy page top: one equity value per
 * session, the window since the current stage began, the backtest expectation and the forward
 * gate's progress. No fetching here. */
import type { GateRow, SeriesPayload, SeriesRow, Transition } from '../types'
import { rangeStart } from './homeRange'

export const STAGE_LABEL: Record<string, string> = {
  idea: 'Idea', backtested: 'Backtested', candidate: 'Candidate', paper: 'Paper',
  forward_tested: 'Forward tested', live: 'Live', dormant: 'Dormant', retired: 'Retired',
}

export const stageLabel = (stage: string) => STAGE_LABEL[stage] ?? stage

/** Lowercase label for running text ("since forward tested"). */
export const stageWords = (stage: string) => stageLabel(stage).toLowerCase()

/** The lane an operating strategy ticks in: live in the live lane, paper and forward_tested in
 * the paper lane. */
export function laneFor(stage: string): 'paper' | 'live' | null {
  if (stage === 'live') return 'live'
  if (stage === 'paper' || stage === 'forward_tested') return 'paper'
  return null
}

/** The stage whose entry opens the lane: going live, or paper intake (a forward_tested strategy
 * keeps ticking the same paper book, and its forward evidence is that whole run). */
export const laneStage = (stage: string) => (stage === 'live' ? 'live' : 'paper')

export interface DayPoint { date: string; equity: number }

/** The newest tick's equity per UTC session date, oldest first. */
export function dailyPoints(rows: SeriesRow[] | null | undefined): DayPoint[] {
  const byDate = new Map<string, { ts: string; equity: number }>()
  for (const r of rows ?? []) {
    if (!Number.isFinite(r.equity)) continue
    const date = r.tick_ts.slice(0, 10)
    const prev = byDate.get(date)
    if (prev === undefined || r.tick_ts >= prev.ts) byDate.set(date, { ts: r.tick_ts, equity: r.equity })
  }
  return [...byDate.entries()].sort(([a], [b]) => (a < b ? -1 : 1))
    .map(([date, v]) => ({ date, equity: v.equity }))
}

/** When the strategy entered its current stage (the newest transition into it). */
export function stageEntry(transitions: Transition[] | undefined, stage: string): string | null {
  const into = (transitions ?? []).filter((t) => t.to_stage === stage)
  return into.length > 0 ? into[into.length - 1].created_at : null
}

/** The lane's sessions since the current stage began. A stage entered after the newest tick
 * (just promoted) falls back to the whole lane, so the curve never goes blank. */
export function sinceStage(points: DayPoint[], entry: string | null): DayPoint[] {
  if (entry === null) return points
  const from = entry.slice(0, 10)
  const shown = points.filter((p) => p.date >= from)
  return shown.length > 0 ? shown : points
}

export function lanePoints(payload: SeriesPayload | undefined, stage: string): DayPoint[] {
  const lane = laneFor(stage)
  return lane === null || payload === undefined ? [] : dailyPoints(payload.series[lane])
}

export type Window = '1W' | '1M' | 'stage' | 'backtest'

/** 1W / 1M count back from the newest session (never the wall clock). */
export function windowPoints(stagePoints: DayPoint[], window: Window): DayPoint[] {
  if (window !== '1W' && window !== '1M') return stagePoints
  const last = stagePoints.at(-1)
  if (last === undefined) return []
  const start = rangeStart(window, last.date)
  return start === null ? stagePoints : stagePoints.filter((p) => p.date >= start)
}

export const finite = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const truthy = (v: unknown) => v === true || v === 1

export interface HoldoutRecord { sharpe: number | null; totalReturn: number | null; nObs: number | null }

/** The newest PASSING research gate row's holdout record (`registry gates`). */
export function passingHoldout(rows: GateRow[] | undefined): HoldoutRecord | null {
  const row = (rows ?? []).find((r) => truthy(r.passed))
  if (row === undefined) return null
  return { sharpe: finite(row.sharpe_oos), totalReturn: finite(row.total_return_oos), nObs: finite(row.n_obs_oos) }
}

/** `daily = (1 + total_return_oos) ** (1 / n_obs_oos) - 1`, or null when the record is missing
 * or cannot compound (n < 1, a total loss). */
export function expectedDaily(h: HoldoutRecord | null): number | null {
  if (h === null || h.totalReturn === null || h.nObs === null) return null
  if (h.nObs < 1 || h.totalReturn <= -1) return null
  return Math.pow(1 + h.totalReturn, 1 / h.nObs) - 1
}

/** The expected path: `base` compounded by `daily` once per session, `n` points. */
export function expectedPath(base: number, daily: number, n: number): number[] {
  return Array.from({ length: n }, (_, i) => base * Math.pow(1 + daily, i))
}

export interface Realized { sharpe: number | null; vol: number | null; maxDrawdown: number | null }

/** Annualized (252) Sharpe and volatility of the session returns, and the max drawdown (≤ 0). */
export function realized(points: DayPoint[]): Realized {
  const eq = points.map((p) => p.equity)
  const rets = eq.slice(1).map((v, i) => v / eq[i] - 1).filter(Number.isFinite)
  let peak = -Infinity
  let dd = 0
  for (const v of eq) {
    peak = Math.max(peak, v)
    if (peak > 0) dd = Math.min(dd, v / peak - 1)
  }
  if (rets.length < 2) return { sharpe: null, vol: null, maxDrawdown: eq.length > 0 ? dd : null }
  const mean = rets.reduce((a, b) => a + b, 0) / rets.length
  const sd = Math.sqrt(rets.reduce((a, r) => a + (r - mean) ** 2, 0) / (rets.length - 1))
  return {
    sharpe: sd > 0 ? (mean / sd) * Math.sqrt(252) : null,
    vol: sd * Math.sqrt(252),
    maxDrawdown: dd,
  }
}

/** 0.1 -> "10%", 0.034 (digits 1) -> "3.4%". */
export function fmtPct(x: number, digits = 0): string {
  return `${(x * 100).toFixed(digits)}%`
}

/** A Sharpe-like ratio to two places with a true minus sign; "—" when unknown. */
export function ratio(x: number | null): string {
  if (x === null || !Number.isFinite(x)) return '—'
  return `${x < 0 ? '−' : ''}${Math.abs(x).toFixed(2)}`
}

/** "+4.1%" / "−1.3%" (a true minus sign). */
export function signedPct(x: number): string {
  return `${x < 0 ? '−' : '+'}${Math.abs(x * 100).toFixed(1)}%`
}

/** "Oct 3". */
export function shortDate(iso: string): string {
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })
}
