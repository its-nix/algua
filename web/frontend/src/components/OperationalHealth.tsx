import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, useFetch } from '../api'
import { useSetFetchedAt } from '../App'
import { utcDateTime } from '../format'
import type { TriageItem, TriagePayload } from '../types'
import StaleNotice from './StaleNotice'

const KIND_COLOR: Record<TriageItem['kind'], string> = {
  loop_down: 'var(--red)',
  global_halt: 'var(--red)',
  capital_stranded: 'var(--amber)',
  strategy: 'var(--amber)',
  queue_wedged: 'var(--text-dim)',
}

function errorCode(error: Error | null): string {
  return error instanceof ApiError && error.code !== null ? error.code : (error?.message ?? 'unknown error')
}

export default function OperationalHealth({ updateHeader = false }: { updateHeader?: boolean }) {
  const triage = useFetch<TriagePayload>('/api/triage', { ttlMs: 10_000 })
  const setFetchedAt = useSetFetchedAt()
  const fetchedAt = triage.data?.fetched_at ?? null

  useEffect(() => {
    if (!updateHeader) return
    setFetchedAt(fetchedAt)
    return () => setFetchedAt(null)
  }, [fetchedAt, setFetchedAt, updateHeader])

  if (triage.data === undefined) {
    if (triage.loading) {
      return (
        <section className="ops-status" role="status">
          <span className="sr-only">loading operational health</span>
          <div className="skeleton-block" style={{ height: 128 }} aria-hidden="true" />
        </section>
      )
    }
    return (
      <section className="panel error-panel ops-status" aria-labelledby="ops-health-heading">
        <h2 id="ops-health-heading" className="micro-label">operational health unknown</h2>
        <div className="error-code">{errorCode(triage.error)}</div>
        <p className="dim-note">Warnings cannot be verified. Treat operations as unknown.</p>
        <div className="ops-actions">
          <button type="button" className="retry-btn" onClick={triage.refetch}>retry</button>
          <Link to="/now" className="text-link">full ops diagnostics</Link>
        </div>
      </section>
    )
  }

  const { items, headline, sources } = triage.data
  const degraded = Object.entries(sources).filter(([, ok]) => !ok).map(([name]) => name)

  return (
    <section className="ops-status" aria-labelledby="ops-health-heading">
      <StaleNotice env={triage.data} />
      {triage.error !== null && (
        <div className="banner-stale">
          <span className="micro-label">health refresh failed</span>
          <div>showing the last available read · {errorCode(triage.error)}</div>
          <button type="button" className="retry-btn" onClick={triage.refetch}>retry</button>
        </div>
      )}
      <div className="ops-status-head">
        <div>
          <h2 id="ops-health-heading" className="board-heading">Ops</h2>
          <div className="dim-note num">
            fleet {headline.fleet_total === null ? 'UNKNOWN' : `${headline.fleet_ok}/${headline.fleet_total}`}
            {' · '}loops {headline.loops_alerting}
          </div>
        </div>
        <Link to="/now" className="text-link" aria-label="full ops diagnostics">ops diagnostics</Link>
      </div>

      {degraded.length > 0 && (
        <div className="banner-stale">
          <span className="micro-label">partial read</span>
          <div>{degraded.join(', ')} unavailable — warnings may be incomplete</div>
        </div>
      )}

      {items.length === 0 ? (
        <div className="all-clear-line">no current warnings in the available health read</div>
      ) : (
        <div className="row-list ops-warning-list">
          {items.map((item, index) => <HealthWarning key={`${item.kind}-${item.title}-${index}`} item={item} />)}
        </div>
      )}
      <div className="tile-row">
        <HeadlineLink label="fleet ok" value={headline.fleet_total === null ? 'UNKNOWN' : `${headline.fleet_ok}/${headline.fleet_total}`} to="/fleet" />
        <HeadlineLink label="book" value={headline.book_capacity === null ? 'UNKNOWN' : `${headline.book_allocated}/${headline.book_capacity}`} to="/money" />
        <HeadlineLink label="loops down" value={String(headline.loops_alerting)} to="/research" alarm={headline.loops_alerting > 0} />
      </div>
    </section>
  )
}

function HeadlineLink({ label, value, to, alarm = false }: {
  label: string
  value: string
  to: string
  alarm?: boolean
}) {
  return (
    <Link to={to} className="metric-tile headline-tile">
      <div className="metric-value" style={alarm ? { color: 'var(--red)' } : undefined}>{value}</div>
      <div className="metric-label">{label}</div>
    </Link>
  )
}

function HealthWarning({ item }: { item: TriageItem }) {
  return (
    <Link to={item.route} className="triage-row">
      <span className="triage-rule" style={{ background: KIND_COLOR[item.kind] }} aria-hidden="true" />
      <div className="triage-body">
        <div className="triage-title">{item.title}</div>
        {item.detail !== null && item.detail !== '' && <div className="dim-note">{item.detail}</div>}
        {item.since !== null && <div className="dim-note num">since {utcDateTime(item.since)}</div>}
      </div>
    </Link>
  )
}
