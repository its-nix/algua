import { useState } from 'react'
import type { ReactNode } from 'react'
import { useFetch } from '../api'
import { num, parseUtc, pct } from '../format'
import type { ApiEnvelope } from '../types'
import EvidenceStatus from './EvidenceStatus'

interface Attempt {
  attempt_id: number
  evidence_id: string
  idea_id: number
  research_cycle_id: string
  outcome: string
  outcome_at: string | null
  archive_reference: string
}
interface Index {
  schema_version: 'retained-research-index/v1'
  metadata_verified: false
  evidence_mode: 'UNVERIFIED_WORKER'
  authority: 'none'
  association: 'cycle_only'
  count: number
  has_more: boolean
  limit: number
  attempts: Attempt[]
}
interface Observation {
  source_ref: string
  source_run_id: number
  kind: string
  strategy_name: string
  parent_refs: string[]
  provenance: Record<string, unknown>
  inputs: Record<string, unknown>
  model_refs: Record<string, unknown>[]
  metrics: Record<string, number | null>
  extra_metrics: Record<string, number | null>
}
interface Memory {
  schema_version: 'research-memory/v1'
  research_cycle_id: string
  evidence_mode: 'UNVERIFIED_WORKER'
  authority: 'none'
  source_commit: string
  worker_exit: number
  attempt_refs: { evidence_id: string; idea_id: number }[]
  evaluations: Observation[]
  coverage: Record<string, unknown>
}

const cycleShape = /^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$/
const object = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)
const positive = (v: unknown): v is number => Number.isSafeInteger(v) && Number(v) > 0
const numbers = (v: unknown) => object(v) && Object.values(v).every(
  value => value === null || typeof value === 'number' && Number.isFinite(value),
)

function isIndex(v: unknown): v is Index {
  return object(v) && v.schema_version === 'retained-research-index/v1'
    && v.metadata_verified === false && v.evidence_mode === 'UNVERIFIED_WORKER'
    && v.authority === 'none' && v.association === 'cycle_only'
    && typeof v.has_more === 'boolean' && positive(v.limit) && v.limit <= 100
    && Array.isArray(v.attempts) && v.attempts.length <= v.limit && v.count === v.attempts.length
    && v.attempts.every((r: unknown) => object(r) && positive(r.attempt_id) && positive(r.idea_id)
      && r.evidence_id === `idea_attempts:${r.attempt_id}`
      && typeof r.research_cycle_id === 'string' && cycleShape.test(r.research_cycle_id)
      && typeof r.outcome === 'string' && typeof r.archive_reference === 'string')
}

function isMemory(v: unknown, selected: Attempt): v is Memory {
  if (!object(v) || v.schema_version !== 'research-memory/v1'
    || v.research_cycle_id !== selected.research_cycle_id || v.authority !== 'none'
    || v.evidence_mode !== 'UNVERIFIED_WORKER' || !Number.isInteger(v.worker_exit)
    || typeof v.source_commit !== 'string' || !/^(?:[0-9a-f]{40}|[0-9a-f]{64})$/.test(v.source_commit)
    || !object(v.coverage) || !Array.isArray(v.attempt_refs) || !Array.isArray(v.evaluations)) return false
  if (!v.attempt_refs.some((r: unknown) => object(r) && r.evidence_id === selected.evidence_id
    && r.idea_id === selected.idea_id)) return false
  const refs = new Set<string>()
  return v.evaluations.every((r: unknown) => {
    if (!object(r) || !positive(r.source_run_id)
      || r.source_ref !== `scratch:${selected.research_cycle_id}:runs:${r.source_run_id}`
      || typeof r.kind !== 'string' || typeof r.strategy_name !== 'string'
      || !Array.isArray(r.parent_refs) || !Array.isArray(r.model_refs)
      || !object(r.inputs) || !object(r.provenance) || !numbers(r.metrics)
      || !numbers(r.extra_metrics) || refs.has(r.source_ref)) return false
    refs.add(r.source_ref)
    return true
  })
}

const outcomeLabels: Record<string, string> = {
  integrity_fail: 'Not qualified', holdout_negative: 'Negative holdout',
  walkforward_refuted: 'Walk-forward refuted', sweep_unstable: 'Unstable sweep',
  candidate_preview_pass: 'Preview passed', promoted_candidate: 'Reported candidate',
  abandoned: 'Abandoned', run_error: 'Execution error',
}
const kindLabels: Record<string, string> = {
  backtest: 'Backtest', walk_forward: 'Walk-forward', sweep: 'Sweep', sweep_trial: 'Sweep variant',
}
const metricLabels = [
  ['total_return_is', 'IS return', 'percent'], ['sharpe_is', 'IS Sharpe', 'number'],
  ['max_drawdown_is', 'IS drawdown', 'percent'],
  ['mean_window_sharpe', 'Mean window Sharpe', 'number'],
  ['mean_trial_sharpe', 'Mean trial Sharpe', 'number'], ['n_obs_is', 'Observations', 'number'],
] as const

function attemptDate(value: unknown): string {
  const date = typeof value === 'string' ? parseUtc(value) : null
  return date === null ? 'Date unavailable' : new Intl.DateTimeFormat('en-GB', {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
    hour12: false, timeZone: 'UTC',
  }).format(date) + ' UTC'
}

export default function RetainedExperiments({ compact = false }: { compact?: boolean }) {
  const index = useFetch<ApiEnvelope<unknown>>('/api/research-memory?limit=20')
  const [selection, setSelected] = useState<Attempt | null | undefined>(undefined)
  const payload = index.data?.data
  const selected = selection === undefined && compact && !index.data?.stale && index.error === null
    && isIndex(payload) ? payload.attempts[0] ?? null : selection ?? null
  return (
    <section id="retained-experiments" aria-labelledby="retained-heading"
      className={`retained-results${compact ? ' retained-compact' : ''}`}>
      <header className="retained-header">
        <div>
          <h2 id="retained-heading" className="retained-heading">{compact ? 'Latest research' : 'Research results'}</h2>
          {!compact && <p className="retained-caption">{isIndex(payload)
            ? `${payload.count} ${payload.count === 1 ? 'attempt' : 'attempts'}` : 'Attempt records'}
            {' · not registered strategies'}</p>}
        </div>
      <details className="retained-disclosure retained-trust-dropdown">
        <summary className="retained-trust-badge">Unverified research</summary>
        <p>UNVERIFIED_WORKER · authority: none · cycle-only association.</p>
        <p>Index metadata is not verified. Attempt references are not independent trials or
          registered strategies. Archive integrity is checked on selection; worker evidence
          remains unverified. Execution and qualification outcomes are separate, and cycle
          observations are not attributed to an individual idea.</p>
      </details>
      </header>
      {index.data?.stale && <EvidenceStatus title="stale retained index" state="stale"
        detail="Showing cached attempt references." onRetry={index.refetch} />}
      {index.error !== null && <EvidenceStatus title="retained index" state="failed"
        detail={index.error.message} onRetry={index.refetch} />}
      {index.data === undefined ? (
        index.error === null && <EvidenceStatus title="retained index" state="loading" detail="Loading attempt references." />
      ) : !isIndex(payload) ? (
        <EvidenceStatus title="retained index" state="failed" detail="Unsupported retained index payload." />
      ) : (
        <>
          {payload.attempts.length === 0 && <p>No retained archive references recorded.</p>}
          <ul className="retained-list">
            {(compact ? payload.attempts.slice(0, 3) : payload.attempts).map(row => {
              const active = selected?.evidence_id === row.evidence_id
              return <li key={row.evidence_id} className="retained-list-item">
                <button type="button" aria-pressed={active}
                  aria-label={`Inspect ${row.research_cycle_id} · attempt ${row.attempt_id} · idea ${row.idea_id}`}
                  className={`retained-row${active ? ' is-selected' : ''}`} data-outcome={row.outcome}
                  onClick={() => setSelected(active ? null : row)}>
                  <span className="retained-row-main">
                    <strong className="retained-row-title">{attemptDate(row.outcome_at)}</strong>
                    <span className="retained-row-meta">Run {row.attempt_id}</span>
                  </span>
                  <span className="retained-outcome">{outcomeLabels[row.outcome] ?? row.outcome.replace(/_/g, ' ')}</span>
                </button>
                {active && <RetainedDetail key={row.evidence_id} selected={row} />}
              </li>
            })}
          </ul>
          {!compact && payload.has_more && <p className="retained-caption">Showing the newest {payload.limit} attempts; more are retained.</p>}
        </>
      )}
    </section>
  )
}

function RetainedDetail({ selected }: { selected: Attempt }) {
  const detail = useFetch<ApiEnvelope<unknown>>(`/api/research-memory/${encodeURIComponent(selected.research_cycle_id)}`)
  const [sourceRef, setSourceRef] = useState<string | null>(null)
  const payload = detail.data?.data
  if (detail.data === undefined) return <EvidenceStatus title="retained archive"
    state={detail.error === null ? 'loading' : 'failed'}
    detail={detail.error?.message ?? 'Verifying retained archive.'} onRetry={detail.refetch} />
  if (!isMemory(payload, selected)) return <EvidenceStatus title="retained archive" state="failed"
    detail="Retained evidence does not match the selected attempt or supported schema." />
  const evaluation = payload.evaluations.find(row => row.source_ref === sourceRef) ?? payload.evaluations[0]
  const archiveDetails = (
      <details className="retained-disclosure">
        <summary>Run &amp; archive details</summary>
        <p>Worker exit: {payload.worker_exit} · attempt outcome: {selected.outcome}.</p>
        <pre className="retained-raw">{JSON.stringify({ research_cycle_id: payload.research_cycle_id,
          evidence_id: selected.evidence_id, idea_id: selected.idea_id,
          archive_reference: selected.archive_reference, source_commit: payload.source_commit,
          coverage: payload.coverage }, null, 2)}</pre>
      </details>
  )
  return (
    <div className="retained-detail">
      {(detail.data.stale || detail.error !== null) && <EvidenceStatus title="retained archive" state="stale"
        detail={detail.error?.message ?? 'Showing cached verified readback.'} onRetry={detail.refetch} />}
      {payload.evaluations.length === 0 ? <p>No retained numerical evaluations.</p> : <>
        <header className="retained-detail-header">
          <h3 className="retained-detail-title">{evaluation.strategy_name.replaceAll('_', ' ')}</h3>
          <p className="retained-detail-meta">{kindLabels[evaluation.kind] ?? evaluation.kind}</p>
        </header>
        <Evaluation value={evaluation}>
        <label className="retained-evaluation-control">Evaluation{' '}
          <select aria-label="Evaluation" value={evaluation.source_ref} onChange={event => setSourceRef(event.target.value)}>
            {payload.evaluations.map((row, i) => <option key={row.source_ref} value={row.source_ref}>
              {i + 1}. {row.strategy_name.replaceAll('_', ' ')} · {kindLabels[row.kind] ?? row.kind}
            </option>)}
          </select>
        </label>
        {archiveDetails}
        </Evaluation>
      </>}
      {payload.evaluations.length === 0 && archiveDetails}
    </div>
  )
}

function Evaluation({ value, children }: { value: Observation; children: ReactNode }) {
  const metrics = { ...value.metrics, ...value.extra_metrics }
  const highlights = metricLabels.filter(([key]) => Object.hasOwn(metrics, key)).slice(0, 3)
  return (
    <article>
      <div className="retained-metrics" role="group" aria-label="Key research metrics">
        {highlights.map(([key, label, format]) => <div key={key} className="retained-metric">
          <span className="retained-metric-label">{label}</span>
          <strong className="retained-metric-value">{metrics[key] == null ? 'Unavailable'
            : format === 'percent' ? pct(metrics[key]) : num(metrics[key])}</strong>
        </div>)}
        {highlights.length === 0 && <p className="retained-caption">No summary metrics recorded.</p>}
      </div>
      <details className="retained-disclosure retained-more">
      <summary>Details</summary>
      {children}
      <details className="retained-disclosure">
        <summary>All recorded metrics</summary>
        <p>Public research statistics; contexts are not ranked or treated as gate passes.</p>
        <table className="retained-metric-table"><thead><tr><th>Metric</th><th>Raw value</th></tr></thead><tbody>
          {Object.entries(metrics).map(([key, number]) =>
            <tr key={key}><th scope="row">{key}</th><td>{number === null ? 'Unavailable' : String(number)}</td></tr>)}
        </tbody></table>
      </details>
      <details className="retained-disclosure">
        <summary>Inputs &amp; provenance</summary>
        <pre className="retained-raw">{JSON.stringify({ source_ref: value.source_ref,
          strategy_name: value.strategy_name, provenance: value.provenance, inputs: value.inputs, parent_refs: value.parent_refs }, null, 2)}</pre>
      </details>
      <details className="retained-disclosure">
        <summary>Model references only</summary>
        <pre className="retained-raw">{JSON.stringify(value.model_refs, null, 2)}</pre>
        <p>Model bytes are not preserved by this archive.</p>
      </details>
      </details>
    </article>
  )
}
