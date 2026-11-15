import { Fragment, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useFetch } from '../api'
import ActorChip from '../components/ActorChip'
import OperationalHealth from '../components/OperationalHealth'
import { utcDate, utcTime } from '../format'
import { alertsState, disableAlerts, enableAlerts, type AlertsState } from '../push'
import type { ActivityRow, ApiEnvelope, ListPayload } from '../types'

const ACTIVITY_LIMIT = 25

export default function Now() {
  const activity = useFetch<ApiEnvelope<ListPayload<ActivityRow>>>(
    `/api/activity?limit=${ACTIVITY_LIMIT}`,
  )

  return (
    <>
      <OperationalHealth updateHeader />
      <ActivityFeed query={activity} />
      <AlertsPanel />
    </>
  )
}

/** The audit trail, absorbed from the old Activity tab. "What did the machine do while I was
 * asleep" is a Now question, not a separate destination. */
function ActivityFeed({
  query,
}: {
  query: ReturnType<typeof useFetch<ApiEnvelope<ListPayload<ActivityRow>>>>
}) {
  if (query.data === undefined) {
    if (query.loading) {
      return <div className="skeleton-block" style={{ height: 140 }} aria-hidden="true" />
    }
    return (
      <section className="panel">
        <span className="micro-label">recent activity</span>
        <div className="dim-note">activity unavailable</div>
      </section>
    )
  }
  const rows = query.data.data.data
  if (rows.length === 0) {
    return (
      <section className="panel">
        <span className="micro-label">recent activity</span>
        <div className="dim-note">nothing recorded yet</div>
      </section>
    )
  }
  let prevDate: string | null = null
  return (
    <section className="panel">
      <span className="micro-label">recent activity</span>
      <div className="alert-list">
        {rows.map((row, i) => {
          const date = utcDate(row.ts)
          const showDate = date !== prevDate
          prevDate = date
          return (
            <Fragment key={row.id ?? `${row.ts}-${i}`}>
              {showDate && <div className="date-divider num">{date}</div>}
              <div className="activity-row">
                <div className="activity-row-head">
                  <span className="num dim-note">{utcTime(row.ts)}</span>
                  <ActorChip actor={row.actor} />
                  <span className="activity-action">{row.action}</span>
                  {row.strategy != null && row.strategy !== '' && (
                    <Link to={`/s/${encodeURIComponent(row.strategy)}`} className="row-link">
                      {row.strategy}
                    </Link>
                  )}
                </div>
                {row.reason != null && row.reason !== '' && (
                  <div className="dim-note activity-reason">{row.reason}</div>
                )}
              </div>
            </Fragment>
          )
        })}
      </div>
    </section>
  )
}

function AlertsPanel() {
  const [state, setState] = useState<AlertsState | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let alive = true
    void alertsState().then((s) => {
      if (alive) setState(s)
    })
    return () => {
      alive = false
    }
  }, [])

  // Unknown yet or genuinely unsupported: no control at all.
  if (state === null || state === 'unsupported') return null

  const run = (action: () => Promise<AlertsState>) => {
    if (busy) return
    setBusy(true)
    action()
      // On failure, re-derive the truth from the browser instead of guessing.
      .then(setState)
      .catch(() => alertsState().then(setState))
      .finally(() => setBusy(false))
  }

  return (
    <section className="panel">
      <span className="micro-label">push alerts</span>
      {state === 'off' && (
        <button type="button" className="retry-btn" disabled={busy} onClick={() => run(enableAlerts)}>
          enable alerts
        </button>
      )}
      {state === 'on' && (
        <div>
          alerts on{' '}
          <button
            type="button"
            className="retry-btn"
            disabled={busy}
            onClick={() => run(disableAlerts)}
          >
            disable
          </button>
        </div>
      )}
      {state === 'denied' && <div>notifications blocked — enable in browser settings</div>}
      {state === 'needs-install' && <div>install to home screen to enable alerts</div>}
    </section>
  )
}
