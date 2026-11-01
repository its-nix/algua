import { Link, useParams } from 'react-router-dom'
import { ApiError, useFetch } from '../api'
import StaleNotice from '../components/StaleNotice'
import { isBoardPayload, RefreshError } from '../components/StrategyBoard'
import type { ApiEnvelope, StrategyBoardPayload } from '../types'
import StrategyDetail from './StrategyDetail'

export default function StrategyIdResolver() {
  const { id = '' } = useParams()
  const validId = /^[1-9]\d*$/.test(id) && Number.isSafeInteger(Number(id))

  if (!validId) return <ResolverError message="invalid strategy identity" />
  return <ValidStrategyIdResolver id={Number(id)} />
}

function ValidStrategyIdResolver({ id }: { id: number }) {
  const board = useFetch<ApiEnvelope<StrategyBoardPayload>>('/api/strategy-board')

  if (board.data === undefined) {
    if (board.loading) {
      return <div className="skeleton-block" style={{ height: 320 }} role="status">
        <span className="sr-only">resolving strategy identity</span>
      </div>
    }
    const code = board.error instanceof ApiError && board.error.code !== null
      ? board.error.code
      : (board.error?.message ?? 'unknown error')
    return (
      <section className="panel error-panel">
        <span className="micro-label">identity lookup failed</span>
        <div className="error-code">{code}</div>
        <button type="button" className="retry-btn" onClick={board.refetch}>retry</button>
      </section>
    )
  }

  if (!isBoardPayload(board.data.data)) return <ResolverError message="unsupported strategy board" />
  const row = board.data.data.rows.find((candidate) => candidate.strategy_id === id)
  if (row === undefined) return <ResolverError message="strategy identity not found" />

  return (
    <>
      <StaleNotice env={board.data} />
      <RefreshError error={board.error} />
      <StrategyDetail
        strategyName={row.name}
        expectedStrategyId={id}
        onIdentityRetry={board.refetch}
      />
    </>
  )
}

function ResolverError({ message }: { message: string }) {
  return (
    <section className="panel error-panel">
      <span className="micro-label">strategy unavailable</span>
      <div className="error-code">{message}</div>
      <Link to="/" className="text-link">back to leaderboard</Link>
    </section>
  )
}
