import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, useFetch } from '../api'
import { useSetFetchedAt } from '../App'
import mark from '../assets/mark-reversed.png'
import EquityLine, { smooth } from '../components/EquityLine'
import HomeIcon from '../components/HomeIcons'
import { money } from '../format'
import type {
  ApiEnvelope, BookPayload, EquityPayload, ListPayload, StrategyRecord, TriagePayload,
} from '../types'
import { useWidth } from '../useWidth'
import { RANGES, latestChange, pointsInRange, type Range } from './homeRange'
import './home.css'

const GREEN = 'var(--green)'
const RED = 'var(--red)'
const LANES = [
  { value: 'all', label: 'Paper + live' },
  { value: 'paper', label: 'Paper' },
  { value: 'live', label: 'Live' },
] as const
type Lane = (typeof LANES)[number]['value']

/** Home answers "is the equity curve going up?" first; then what needs attention, where the
 * capital sits and how full each stage is. */
export default function Home() {
  const [lane, setLane] = useState<Lane>('all')
  return (
    <div className="home">
      <div className="home-top">
        <img src={mark} className="home-mark" width="26" height="26" alt="Algua" />
        <label className="lane-pick">
          <span className="lane-pill" aria-hidden="true">
            {LANES.find((l) => l.value === lane)?.label}
            <HomeIcon name="chevron-down" size={14} />
          </span>
          <select aria-label="Lane" value={lane} onChange={(e) => setLane(e.target.value as Lane)}>
            {LANES.map((l) => <option key={l.value} value={l.value}>{l.label}</option>)}
          </select>
        </label>
      </div>
      <Equity lane={lane} />
      <Attention />
      <Capital />
      <StageCounts />
    </div>
  )
}

function FetchError({ error, refetch }: { error: Error | null; refetch: () => void }) {
  return (
    <section className="panel error-panel">
      <span className="micro-label">fetch failed</span>
      <div className="error-code">
        {error instanceof ApiError && error.code !== null ? error.code : (error?.message ?? 'unknown error')}
      </div>
      <button type="button" className="retry-btn" onClick={refetch}>retry</button>
    </section>
  )
}

function Equity({ lane }: { lane: Lane }) {
  const url = lane === 'all' ? '/api/equity' : `/api/equity?lane=${lane}`
  const { data, error, loading, refetch } = useFetch<ApiEnvelope<EquityPayload>>(url)
  const [range, setRange] = useState<Range>('3M')
  const [chartRef, width] = useWidth<HTMLDivElement>(360)
  const setFetchedAt = useSetFetchedAt()
  const fetchedAt = data?.fetched_at ?? null
  useEffect(() => {
    setFetchedAt(fetchedAt)
    return () => setFetchedAt(null)
  }, [fetchedAt, setFetchedAt])

  const eq = data?.data
  const points = eq?.points ?? []
  const shown = pointsInRange(points, range)
  const pnl = shown.map((p) => p.pnl)
  const up = pnl.length < 2 || pnl[pnl.length - 1] >= pnl[0]
  const change = eq ? latestChange(points, eq.change_today, eq.last_session) : null
  const prior = eq && change ? eq.current_equity - change.amount : 0
  const changePct = prior > 0 && change ? (change.amount / prior) * 100 : null

  return (
    <>
      <div className="home-head">
        <div className="home-label">Portfolio equity</div>
        {eq === undefined
          ? (loading ? <div className="skeleton-block home-big-skeleton" aria-hidden="true" /> : <FetchError error={error} refetch={refetch} />)
          : <>
            <div className="home-big num-tab">{money(eq.current_equity)}</div>
            {points.length > 0 && change !== null && (
              <div className="home-change num-tab">
                <b className={change.amount < 0 ? 'down' : 'up'}>
                  {change.amount < 0 ? '▼' : '▲'} {money(Math.abs(change.amount))}
                  {changePct !== null && ` (${Math.abs(changePct).toFixed(2)}%)`}
                </b>
                <span>{change.asOf === null ? 'Today' : `as of ${change.asOf}`}</span>
              </div>
            )}
          </>}
      </div>
      <div className="home-chart" ref={chartRef}>
        {eq !== undefined && points.length === 0 && <div className="home-chart-empty">No equity yet</div>}
        {shown.length > 0 && (
          <EquityLine data={smooth(pnl, 1)} width={width} height={140} color={up ? GREEN : RED}
            base={pnl[0]} fill />
        )}
      </div>
      <div className="home-ranges" role="group" aria-label="Range">
        {RANGES.map((r) => (
          <button key={r} type="button" className="home-range" aria-pressed={r === range}
            data-tone={up ? 'up' : 'down'} onClick={() => setRange(r)}>
            <span>{r}</span>
          </button>
        ))}
      </div>
      {eq?.truncated && <p className="home-note">Older sessions are cut off; the curve starts later than the history.</p>}
    </>
  )
}

function Attention() {
  const { data } = useFetch<TriagePayload>('/api/triage', { ttlMs: 10_000 })
  const items = data?.items ?? []
  if (items.length === 0) return null
  const shown = items.slice(0, 3)
  return (
    <section className="home-card home-attention" data-testid="attention" aria-label="Needs attention">
      {shown.map((item) => (
        <Link key={`${item.kind}:${item.title}`} to={item.route} className="home-alert">
          <span className="home-alert-icon"><HomeIcon name="alert" /></span>
          <span className="home-alert-body">
            <span className="home-alert-title">{item.title}</span>
            {item.detail && <span className="home-alert-sub">{item.detail}</span>}
          </span>
          <HomeIcon name="chevron-right" className="home-chev" />
        </Link>
      ))}
      {items.length > shown.length && (
        <Link to="/now" className="home-more">{items.length - shown.length} more</Link>
      )}
    </section>
  )
}

/** Allocated capital by lane. The book's dollar size needs an account-equity broker read this app
 * never makes, so the free part of the book is shown in slots, not dollars. */
function Capital() {
  const { data } = useFetch<ApiEnvelope<BookPayload>>('/api/book')
  const book = data?.data
  if (book === undefined) return null
  const live = book.slices.filter((s) => s.stage === 'live')
  const paper = book.slices.filter((s) => s.stage !== 'live')
  const sum = (rows: typeof live) => rows.reduce((t, s) => t + s.capital, 0)
  const share = (n: number) => `${book.capacity > 0 ? (n / book.capacity) * 100 : 0}%`
  return (
    <section className="home-card" aria-label="Capital">
      <h2 className="home-card-title">Capital <span>{book.allocated} of {book.capacity} slots</span></h2>
      <div className="home-meter" aria-hidden="true">
        <i style={{ width: share(live.length), background: 'var(--green)' }} />
        <i style={{ width: share(paper.length), background: 'var(--ocean)' }} />
      </div>
      <div className="home-kv num-tab">
        <div><b>{money(sum(live), false)}</b><span><i className="home-sw" style={{ background: 'var(--green)' }} />Live</span></div>
        <div><b>{money(sum(paper), false)}</b><span><i className="home-sw" style={{ background: 'var(--ocean)' }} />Paper</span></div>
        <div><b>{book.count_headroom}</b><span><i className="home-sw" style={{ background: 'var(--card-3)' }} />Free slots</span></div>
      </div>
    </section>
  )
}

const STAGE_TILES: { label: string; stages: string[]; live?: boolean }[] = [
  { label: 'Live', stages: ['live'], live: true },
  { label: 'Forward', stages: ['forward_tested'] },
  { label: 'Paper', stages: ['paper'] },
  { label: 'Candidate', stages: ['candidate'] },
  { label: 'Research', stages: ['idea', 'backtested'] },
]

function StageCounts() {
  const { data } = useFetch<ApiEnvelope<ListPayload<StrategyRecord>>>('/api/strategies', { ttlMs: 60_000 })
  const rows = data?.data.data
  if (rows === undefined) return null
  return (
    <section className="home-card" aria-label="Strategies">
      <h2 className="home-card-title">
        Strategies
        <Link to="/strategies" className="home-seeall">See all <HomeIcon name="chevron-right" size={14} /></Link>
      </h2>
      <div className="home-funnel num-tab">
        {STAGE_TILES.map((t) => (
          <Link key={t.label} to="/strategies" className="home-step" data-live={t.live || undefined}>
            <b>{rows.filter((r) => t.stages.includes(r.stage)).length}</b>
            <span>{t.label}</span>
          </Link>
        ))}
      </div>
    </section>
  )
}
