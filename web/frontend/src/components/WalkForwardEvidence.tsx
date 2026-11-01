import { Link, useSearchParams } from 'react-router-dom'
import { useFetch } from '../api'
import { num, pct } from '../format'
import type { ApiEnvelope, StrategyBoardRow } from '../types'
import { BoardEvidence, isBoardPayload, parseEvidence, RESEARCH_SCHEMA_VERSION, RefreshError } from './StrategyBoard'
import EvidenceStatus from './EvidenceStatus'
import StaleNotice from './StaleNotice'

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
    <p className="dim-note">Exploratory recorded tail OOS scalars. No gate verdict or forward qualification.</p>
    <StaleNotice env={query.data} /><RefreshError error={query.error} />
    <div className="board-rail">
      <span>Sharpe {run.sharpe_oos === null ? 'UNKNOWN' : num(run.sharpe_oos)}</span>
      <span>return {run.total_return_oos === null ? 'UNKNOWN' : pct(run.total_return_oos)}</span>
      <span>drawdown {run.max_drawdown_oos === null ? 'UNKNOWN' : pct(run.max_drawdown_oos)}</span>
      <span>sample {run.n_obs_oos ?? 'UNKNOWN'}</span>
    </div>
    <BoardEvidence row={row} evidenceSchema={RESEARCH_SCHEMA_VERSION} compact={false} evidence={evidence} />
    <Link className="text-link" to={`/runs/${run.run_id}`}>recorded run {run.run_id}</Link>
  </section>
}
