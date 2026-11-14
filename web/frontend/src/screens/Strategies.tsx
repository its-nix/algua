import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, useFetch } from '../api'
import { LEADERBOARD_PATH, useSetFetchedAt } from '../App'
import EquityLine, { smooth } from '../components/EquityLine'
import HomeIcon from '../components/HomeIcons'
import { money } from '../format'
import type { ApiEnvelope, BookPayload, ListPayload, SeriesPayload, StrategyRecord } from '../types'
import { lanePoints, signedPct, stageLabel } from './strategyCurve'
import './strategies.css'

/** The Stocks-list grammar: name and context left, its own curve in the middle, value and a
 * colored change chip right; grouped by stage. */
const SEGMENTS = [
  { key: 'operating', label: 'Operating', stages: ['live', 'forward_tested', 'paper'] },
  { key: 'candidates', label: 'Candidates', stages: ['candidate', 'dormant'] },
  { key: 'research', label: 'Research', stages: ['backtested', 'idea'] },
] as const
type Segment = (typeof SEGMENTS)[number]['key']

export default function Strategies() {
  const [segment, setSegment] = useState<Segment>('operating')
  const { data, error, loading, refetch } =
    useFetch<ApiEnvelope<ListPayload<StrategyRecord>>>('/api/strategies', { ttlMs: 60_000 })
  const book = useFetch<ApiEnvelope<BookPayload>>('/api/book').data?.data
  const setFetchedAt = useSetFetchedAt()
  const fetchedAt = data?.fetched_at ?? null
  useEffect(() => {
    setFetchedAt(fetchedAt)
    return () => setFetchedAt(null)
  }, [fetchedAt, setFetchedAt])

  const all = data?.data.data ?? []
  const current = SEGMENTS.find((s) => s.key === segment) ?? SEGMENTS[0]
  const slices = new Map((book?.slices ?? []).map((s) => [s.strategy, s.capital]))

  return (
    <div className="strats">
      <h1 className="strats-title">Strategies</h1>
      <div className="strats-seg" role="group" aria-label="Strategy groups">
        {SEGMENTS.map((s) => (
          <button key={s.key} type="button" aria-pressed={s.key === segment} onClick={() => setSegment(s.key)}>
            <span>{s.label} <b>{all.filter((r) => (s.stages as readonly string[]).includes(r.stage)).length}</b></span>
          </button>
        ))}
      </div>
      {data === undefined ? (
        loading ? <div className="skeleton-block strats-skeleton" aria-hidden="true" /> : (
          <section className="panel error-panel">
            <span className="micro-label">fetch failed</span>
            <div className="error-code">
              {error instanceof ApiError && error.code !== null ? error.code : (error?.message ?? 'unknown error')}
            </div>
            <button type="button" className="retry-btn" onClick={refetch}>retry</button>
          </section>
        )
      ) : (
        <>
          {segment === 'research' && (
            <div className="strats-links">
              <Link to={LEADERBOARD_PATH} className="strats-link">
                <span><b>Leaderboard</b><small>Every strategy's research evidence, ranked</small></span>
                <HomeIcon name="chevron-right" />
              </Link>
              <Link to="/strategies/research" className="strats-link">
                <span><b>Idea pool</b><small>Ideas, research loop and recent runs</small></span>
                <HomeIcon name="chevron-right" />
              </Link>
            </div>
          )}
          {current.stages.map((stage) => {
            const rows = all.filter((r) => r.stage === stage)
            if (rows.length === 0) return null
            return (
              <section key={stage} data-testid="stage-group" data-stage={stage}>
                <h2 className="strats-section"><span>{stageLabel(stage)}</span><span>{rows.length}</span></h2>
                {rows.map((r) => segment === 'operating'
                  ? <OperatingRow key={r.name} rec={r} slice={slices.get(r.name) ?? null} />
                  : <PlainRow key={r.name} rec={r} />)}
              </section>
            )
          })}
          {all.filter((r) => (current.stages as readonly string[]).includes(r.stage)).length === 0 && (
            <p className="strats-empty">No strategies here yet.</p>
          )}
        </>
      )}
    </div>
  )
}

/** One operating strategy: "Day N" counts sessions since it entered its lane (paper intake, or
 * going live); the value is the newest tick's equity and the chip its change over that window,
 * the same window the Strategy page opens on. */
function OperatingRow({ rec, slice }: { rec: StrategyRecord; slice: number | null }) {
  const series = useFetch<ApiEnvelope<SeriesPayload>>(`/api/strategy/${encodeURIComponent(rec.name)}/series`)
  const points = lanePoints(series.data?.data, rec.stage)
  const eq = points.map((p) => p.equity)
  const first = eq[0]
  const last = eq.at(-1)
  const change = first !== undefined && last !== undefined && first > 0 ? last / first - 1 : null
  const up = change === null || change >= 0
  const sub = [
    points.length > 0 ? `Day ${points.length - 1}`
      : series.data !== undefined ? 'No ticks yet'
        : series.error !== null ? 'Equity unavailable' : null,
    slice !== null ? `${money(slice, false)} slice` : null,
  ].filter((x): x is string => x !== null).join(' · ')
  return (
    <Link to={`/s/${encodeURIComponent(rec.name)}`} className="strats-row">
      <span className="strats-id">
        <span className="strats-name">{rec.name}</span>
        <span className="strats-sub">{sub || ' '}</span>
      </span>
      <span className="strats-spark">
        {eq.length > 1 && (
          <EquityLine data={eq.length > 2 ? smooth(eq, 1) : eq} width={60} height={32} color={up ? 'var(--green)' : 'var(--red)'}
            base={first} dot={false} strokeWidth={1.8} />
        )}
      </span>
      <span className="strats-val num-tab">
        <b>{last !== undefined ? money(last, false) : '—'}</b>
        {change !== null && (
          <span className="strats-chip" data-testid="pnl-chip" data-tone={up ? 'up' : 'down'}
            style={{ background: up ? 'var(--green)' : 'var(--red)' }}>{signedPct(change)}</span>
        )}
      </span>
    </Link>
  )
}

function PlainRow({ rec }: { rec: StrategyRecord }) {
  return (
    <Link to={`/s/${encodeURIComponent(rec.name)}`} className="strats-row strats-row-plain">
      <span className="strats-id">
        <span className="strats-name">{rec.name}</span>
        <span className="strats-sub">{rec.family ?? rec.description ?? ' '}</span>
      </span>
      <HomeIcon name="chevron-right" className="strats-chev" />
    </Link>
  )
}
