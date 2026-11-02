import { Link, useSearchParams } from 'react-router-dom'
import { useFetch } from '../api'
import type { ApiEnvelope, StrategyBoardRow } from '../types'
import { BoardEvidence, isBoardPayload, parseEvidence, RESEARCH_SCHEMA_VERSION, RefreshError } from './StrategyBoard'
import EvidenceStatus from './EvidenceStatus'
import StaleNotice from './StaleNotice'
import PublicWindowRail from './PublicWindowRail'

type ResearchRecord = Pick<StrategyBoardRow,
  'strategy_id' | 'latest_research' | 'evidence' | 'recorded_provenance'>

export default function WalkForwardEvidence({ strategyId }: { strategyId: number }) {
  const [params] = useSearchParams()
  const requested = params.get('research_run')
  const validPointer = requested === null || (/^[1-9]\d*$/.test(requested) && Number.isSafeInteger(Number(requested)))
  const query = useFetch<ApiEnvelope<ResearchRecord>>(validPointer
    ? `/api/strategy/${strategyId}/research${requested === null ? '' : `?run_id=${requested}`}` : null)
  if (!validPointer) return <EvidenceStatus title="WF research" state="failed" detail="invalid research run pointer" />
  if (query.data === undefined) return <EvidenceStatus title="WF research" state={query.loading ? 'loading' : 'failed'}
    detail={query.loading ? 'loading recorded research' : query.error?.message ?? 'research unavailable'} />
  const data = query.data.data
  const row = { ...data, name: '', family: null, stage: '', latest_gate: null }
  if (!isBoardPayload({ schema_version: 'strategy-board/v1', evidence_schema_version: RESEARCH_SCHEMA_VERSION,
    count: 1, rows: [row] }) || data.strategy_id !== strategyId ||
    (requested !== null && data.latest_research?.run_id !== Number(requested))) {
    return <EvidenceStatus title="WF research" state="failed" detail="research identity or run mismatch" />
  }
  const run = data.latest_research
  if (run == null) return <EvidenceStatus title="WF research" state="empty" detail="no identity-bound WF runs recorded" />
  const evidence = parseEvidence(data.evidence, run, data.recorded_provenance)
  return <section className="panel" aria-label="recorded WF research">
    <h2 className="micro-label">WF research · run {run.run_id} · strategy ID {strategyId}</h2>
    <p className="dim-note">Public in-sample / selection / pre-holdout windows, not independent OOS. No gate verdict or forward qualification.</p>
    <StaleNotice env={query.data} /><RefreshError error={query.error} />
    <PublicWindowRail run={evidence?.comparison.status === 'COMPARABLE' ? run : {
      ...run, mean_window_sharpe: null, min_window_sharpe: null,
      std_window_sharpe: null, pct_positive_windows: null,
    }} />
    <BoardEvidence row={row} evidenceSchema={RESEARCH_SCHEMA_VERSION} compact={false} evidence={evidence} />
    <Link className="text-link" to={`/runs/${run.run_id}`}>recorded run {run.run_id}</Link>
  </section>
}
