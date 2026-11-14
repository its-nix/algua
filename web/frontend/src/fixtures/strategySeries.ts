/** Demo per-strategy tick history (`/api/strategy/{name}/series`). Invented, deterministic
 * numbers (no real account data): one weekday tick per session since the strategy entered its
 * lane, starting at its slice and ending at the book's last equity (capital + pnl). */
import type { SeriesRow } from '../types'
import { FETCHED_AT, rng, type Seed } from './steady-state'

/** Return observations (sessions after the first) per operating seed. */
const DAYS: Record<string, number> = {
  liquid10_adj_momentum: 41, orderly_six_day_rebound: 38, low_vol_skip_momentum_top3: 41,
  lagged_rank_persistence: 29, cross_horizon_low_vol: 52, dual_horizon_skip_month: 41,
  quality_momentum_qs: 18, peer_selloff_rebound: 36, cadenced_tail_risk: 68, distributed_gains_qm: 66,
}

/** `n` weekday sessions ending on the last weekday before the fixture date. */
function sessionsBefore(n: number): string[] {
  const out: string[] = []
  const d = new Date(`${FETCHED_AT.slice(0, 10)}T00:00:00Z`)
  while (out.length < n) {
    d.setUTCDate(d.getUTCDate() - 1)
    const day = d.getUTCDay()
    if (day !== 0 && day !== 6) out.unshift(d.toISOString().slice(0, 10))
  }
  return out
}

function laneSessions(seed: Seed): string[] {
  const days = DAYS[seed.name]
  return days === undefined || seed.capital <= 0 ? [] : sessionsBefore(days + 1)
}

/** When each stage was entered, for seeds whose history is drawn here: the lane's stage (paper,
 * or live) on its first session, and forward_tested on the 64th paper session. */
export function stageAnchors(seed: Seed): Record<string, string> {
  const s = laneSessions(seed)
  if (s.length === 0) return {}
  const at = (date: string) => `${date}T12:00:00+00:00`
  if (seed.stage === 'live') return { live: at(s[0]) }
  const anchors: Record<string, string> = { paper: at(s[0]) }
  if (seed.stage === 'forward_tested' && s.length > 63) anchors.forward_tested = at(s[63])
  return anchors
}

/** A noisy walk from the slice, tilted so it ends exactly at capital + pnl. */
export function seriesRowsFor(seed: Seed): SeriesRow[] {
  const s = laneSessions(seed)
  if (s.length === 0) return []
  const r = rng(seed.id * 31 + 7)
  const walk = [seed.capital]
  for (let i = 1; i < s.length; i++) walk.push(walk[i - 1] * (1 + (r() + r() + r() - 1.5) * 0.014))
  const tilt = seed.capital + seed.pnl - walk[walk.length - 1]
  let peak = -Infinity
  return s.map((date, i) => {
    const equity = Number((walk[i] + (tilt * i) / Math.max(s.length - 1, 1)).toFixed(2))
    peak = Math.max(peak, equity)
    const ts = `${date}T20:30:00+00:00`
    return { id: seed.id * 1000 + i, tick_ts: ts, recorded_at: ts, equity, peak_equity: peak, reconcile_ok: true }
  })
}
