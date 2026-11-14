import type { EquityPoint } from '../types'

export const RANGES = ['1W', '1M', '3M', 'YTD', '1Y', 'All'] as const
export type Range = (typeof RANGES)[number]

/** The first session date a range includes, counted back from the newest session (never from
 * the wall clock, so a weekend or a stalled loop never empties the chart). */
export function rangeStart(range: Range, lastSession: string): string | null {
  if (range === 'All') return null
  const d = new Date(`${lastSession}T00:00:00Z`)
  if (Number.isNaN(d.getTime())) return null
  if (range === '1W') d.setUTCDate(d.getUTCDate() - 7)
  else if (range === '1M') d.setUTCMonth(d.getUTCMonth() - 1)
  else if (range === '3M') d.setUTCMonth(d.getUTCMonth() - 3)
  else if (range === '1Y') d.setUTCFullYear(d.getUTCFullYear() - 1)
  else return `${d.getUTCFullYear()}-01-01`
  return d.toISOString().slice(0, 10)
}

export function pointsInRange(points: EquityPoint[], range: Range): EquityPoint[] {
  const last = points.at(-1)
  if (last === undefined) return []
  const start = rangeStart(range, last.session)
  return start === null ? points : points.filter((p) => p.session >= start)
}

/** Today's UTC date, the clock `fleet equity` computes `change_today` against. */
export function utcToday(): string {
  return new Date().toISOString().slice(0, 10)
}

/** The change line. On a session that is today it is `change_today`; otherwise `change_today`
 * is 0 by construction, so the line shows the newest session's own P&L move, labelled with its
 * date. */
export function latestChange(
  points: EquityPoint[], changeToday: number, lastSession: string | null, today = utcToday(),
): { amount: number; asOf: string | null } {
  if (lastSession === null || lastSession === today) return { amount: changeToday, asOf: null }
  const n = points.length
  return { amount: n >= 2 ? points[n - 1].pnl - points[n - 2].pnl : 0, asOf: lastSession }
}
