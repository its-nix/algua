import { Link } from 'react-router-dom'
import { useFetch } from '../api'
import type { ApiEnvelope, StrategyBoardPayload } from '../types'
import { declaredTier, FIXTURE_LABEL } from './BoardDataTier'
import { BoardEvidence, isBoardPayload, parseEvidence, RefreshError } from './StrategyBoard'
import EvidenceStatus from './EvidenceStatus'
import PassMark from './PassMark'
import StaleNotice from './StaleNotice'

export default function GateComparisonEvidence({ strategyId }: { strategyId: number }) {
  const query = useFetch<ApiEnvelope<StrategyBoardPayload>>('/api/strategy-board?include_evidence=true')
  if (query.data === undefined) return <EvidenceStatus title="Gate OOS" state={query.loading ? 'loading' : 'failed'}
    detail={query.loading ? 'loading recorded gate' : query.error?.message ?? 'gate unavailable'} />
  const board = query.data.data
  if (!isBoardPayload(board) || board.evidence_schema_version !== 'strategy-board-evidence/v2') {
    return <EvidenceStatus title="Gate OOS" state="failed" detail="unsupported gate evidence" />
  }
  const row = board.rows.find(r => r.strategy_id === strategyId)
  if (row === undefined) return <EvidenceStatus title="Gate OOS" state="failed" detail="gate strategy identity mismatch" />
  const gate = row.latest_gate
  if (gate === null) return <EvidenceStatus title="Gate OOS" state="empty" detail="no identity-bound gate recorded" />
  const evidence = parseEvidence(row.evidence, gate, row.recorded_provenance)
  return <section className="panel" aria-label="recorded gate comparison">
    <h2 className="micro-label">Gate OOS · run {gate.run_id} · strategy ID {strategyId}</h2>
    {declaredTier(row) === 'synthetic_fixture' && <p className="board-disclosure">{FIXTURE_LABEL}</p>}
    <PassMark passed={gate.passed} />
    <p className="dim-note">Observed comparison is display only, never promotion or forward qualification.</p>
    <StaleNotice env={query.data} /><RefreshError error={query.error} />
    <BoardEvidence row={row} evidenceSchema={board.evidence_schema_version} compact={false} evidence={evidence} />
    <Link className="text-link" to={`/runs/${gate.run_id}`}>recorded gate run {gate.run_id}</Link>
  </section>
}
