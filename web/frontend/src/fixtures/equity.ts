/** Demo `/api/equity` and `/api/inbox` payloads. Invented, deterministic numbers (no real
 * account data): a P&L walk per lane over weekday sessions ending on the fixture date. */
import type { ApiEnvelope, EquityPayload, EquityPoint } from '../types'
import type { InboxListPayload } from '../inboxBadge'
import { FETCHED_AT, envelope, rng } from './steady-state'

const LAST_SESSION = FETCHED_AT.slice(0, 10)
const N = 320

function sessions(n: number): string[] {
  const out: string[] = []
  const d = new Date(`${LAST_SESSION}T00:00:00Z`)
  while (out.length < n) {
    const day = d.getUTCDay()
    if (day !== 0 && day !== 6) out.unshift(d.toISOString().slice(0, 10))
    d.setUTCDate(d.getUTCDate() - 1)
  }
  return out
}

const SESSIONS = sessions(N)

/** Cumulative P&L: drift plus noise, starting at 0 (the P&L index). Live joins later. */
function walk(seed: number, capital: number, drift: number, vol: number, from = 0): number[] {
  const r = rng(seed)
  let pnl = 0
  return SESSIONS.map((_, i) => {
    if (i <= from) return 0
    const shock = (r() + r() + r() - 1.5) * vol
    pnl += (capital + pnl) * (drift + shock)
    return pnl
  })
}

const PAPER_CAPITAL = 10150
const LIVE_CAPITAL = 5400
const PAPER = walk(424242, PAPER_CAPITAL, 0.0011, 0.0065)
const LIVE = walk(77, LIVE_CAPITAL, 0.0009, 0.006, 140)

function payload(lane: 'paper' | 'live' | null): ApiEnvelope<EquityPayload> {
  const points: EquityPoint[] = SESSIONS.map((session, i) => {
    const paper = { pnl: PAPER[i], equity: PAPER_CAPITAL + PAPER[i] }
    const live = i < 140 ? { pnl: 0, equity: 0 } : { pnl: LIVE[i], equity: LIVE_CAPITAL + LIVE[i] }
    const pick = lane === 'paper' ? paper : lane === 'live' ? live
      : { pnl: paper.pnl + live.pnl, equity: paper.equity + live.equity }
    return { session, pnl: Math.round(pick.pnl * 100) / 100, equity: Math.round(pick.equity * 100) / 100 }
  }).filter((p) => lane !== 'live' || p.equity > 0)
  return envelope({
    ok: true,
    lane_filter: lane,
    points,
    current_equity: points.at(-1)?.equity ?? 0,
    // The fixture date is never "today", and the CLI reports 0 for a session that is not today.
    change_today: 0,
    last_session: points.at(-1)?.session ?? null,
    truncated: false,
  })
}

export function equityFixture(url: string): ApiEnvelope<EquityPayload> {
  const lane = new URLSearchParams(url.split('?')[1] ?? '').get('lane')
  return payload(lane === 'paper' || lane === 'live' ? lane : null)
}

export const INBOX: ApiEnvelope<InboxListPayload> = envelope({
  ok: true,
  items: [
    { id: 3, status: 'queued', journey: [{ label: 'Queued for the next leap', tone: 'pending' }] },
    { id: 2, status: 'taken', journey: [
      { label: 'Inspiration', tone: 'neutral' }, { label: 'Idea #41', tone: 'pending' }] },
    { id: 1, status: 'taken', journey: [
      { label: 'Inspiration', tone: 'neutral' }, { label: 'Idea #37', tone: 'neutral' },
      { label: 'Candidate', tone: 'green' }] },
  ],
})
