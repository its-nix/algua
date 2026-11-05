import { useState } from 'react'
import { useFetch } from '../api'
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

export default function RetainedExperiments() {
  const index = useFetch<ApiEnvelope<unknown>>('/api/research-memory?limit=20')
  const [selected, setSelected] = useState<Attempt | null>(null)
  const payload = index.data?.data
  return (
    <section id="retained-experiments" aria-labelledby="retained-heading">
      <h2 id="retained-heading">Retained worker experiments</h2>
      <p>UNVERIFIED_WORKER · authority: none · cycle-only association.</p>
      <p>Index metadata is not verified. These are attempt references, not independent trials or registered strategies.</p>
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
          <ul>
            {payload.attempts.map(row => <li key={row.evidence_id}>
              <button type="button" aria-pressed={selected?.evidence_id === row.evidence_id}
                onClick={() => setSelected(row)}>
                Inspect {row.research_cycle_id} · attempt {row.attempt_id} · idea {row.idea_id}
              </button>{' '}{row.outcome}
            </li>)}
          </ul>
          {payload.has_more && <p>More references exist; showing the newest {payload.limit} attempts.</p>}
        </>
      )}
      {selected !== null && <RetainedDetail key={selected.evidence_id} selected={selected} />}
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
  return (
    <div>
      {(detail.data.stale || detail.error !== null) && <EvidenceStatus title="retained archive" state="stale"
        detail={detail.error?.message ?? 'Showing cached verified readback.'} onRetry={detail.refetch} />}
      <h3>Cycle {payload.research_cycle_id}</h3>
      <p>Archive integrity checked by CLI; worker evidence remains unverified.</p>
      <p>Worker exit: {payload.worker_exit} · attempt outcome: {selected.outcome}.</p>
      <p>Execution and qualification outcomes are separate. Cycle observations are not attributed to an individual idea.</p>
      <p>Declared source commit: <code>{payload.source_commit}</code></p>
      <h4>Archival coverage</h4>
      <pre>{JSON.stringify(payload.coverage, null, 2)}</pre>
      {payload.evaluations.length === 0 ? <p>No retained numerical evaluations.</p> : <>
        <label>Evaluation{' '}
          <select aria-label="Evaluation" value={evaluation.source_ref} onChange={event => setSourceRef(event.target.value)}>
            {payload.evaluations.map(row => <option key={row.source_ref} value={row.source_ref}>
              {row.kind} · {row.source_ref}
            </option>)}
          </select>
        </label>
        <Evaluation value={evaluation} />
      </>}
    </div>
  )
}

function Evaluation({ value }: { value: Observation }) {
  return (
    <article>
      <h4>{value.strategy_name}</h4>
      <p><code>{value.source_ref}</code> · {value.kind}</p>
      <p>Public research statistics; contexts are not ranked or treated as gate passes.</p>
      <table><thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody>
        {Object.entries({ ...value.metrics, ...value.extra_metrics }).map(([key, number]) =>
          <tr key={key}><th scope="row">{key}</th><td>{number === null ? 'unavailable' : String(number)}</td></tr>)}
      </tbody></table>
      <h4>Public inputs and data qualifiers</h4>
      <pre>{JSON.stringify({ provenance: value.provenance, inputs: value.inputs, parent_refs: value.parent_refs }, null, 2)}</pre>
      <h4>Model references only</h4>
      <pre>{JSON.stringify(value.model_refs, null, 2)}</pre>
      <p>Model bytes are not preserved by this archive.</p>
    </article>
  )
}
