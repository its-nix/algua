import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, useFetch } from '../api'
import type { UseFetchResult } from '../api'
import { num, pct, utcDate } from '../format'
import type { ApiEnvelope, StrategyBoardGate, StrategyBoardPayload, StrategyBoardRow } from '../types'
import PassMark from './PassMark'
import Sparkline from './Sparkline'
import StaleNotice from './StaleNotice'
import StageChip from './StageChip'

const SCHEMA_VERSION = 'strategy-board/v1'

type MetricKey = Exclude<keyof StrategyBoardGate, 'run_id' | 'created_at' | 'passed' | 'n_obs_oos'>

interface SortOption {
  key: MetricKey
  label: string
}

/** Approved observed comparison axes. strategy-board/v1 lacks the period/tier metadata required
 * to compare them, so the controls remain visible but disabled until a reviewed contract carries
 * that metadata. No client-side ranking implementation exists in this slice. */
export const SORT_OPTIONS: SortOption[] = [
  { key: 'sharpe_oos', label: 'oos sharpe' },
  { key: 'total_return_oos', label: 'oos return' },
  { key: 'max_drawdown_oos', label: 'oos drawdown' },
]

const LIFECYCLE_ORDER = [
  'idea', 'backtested', 'candidate', 'paper', 'forward_tested', 'live', 'dormant', 'retired',
]

const UNKNOWN_FAMILY = '__unknown_family__'

function finite(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

function nullableFinite(v: unknown): boolean {
  return v === null || finite(v) !== null
}

export function isBoardPayload(value: unknown): value is StrategyBoardPayload {
  if (value === null || typeof value !== 'object') return false
  const candidate = value as Record<string, unknown>
  if (candidate.schema_version !== SCHEMA_VERSION || !Array.isArray(candidate.rows)) return false
  if (!Number.isInteger(candidate.count) || candidate.count !== candidate.rows.length) return false
  return candidate.rows.every((value) => {
    if (value === null || typeof value !== 'object') return false
    const row = value as Record<string, unknown>
    if (!Number.isInteger(row.strategy_id) || typeof row.name !== 'string' ||
        (row.family !== null && typeof row.family !== 'string') || typeof row.stage !== 'string') {
      return false
    }
    if (row.latest_gate === null) return true
    if (typeof row.latest_gate !== 'object') return false
    const gate = row.latest_gate as Record<string, unknown>
    return Number.isInteger(gate.run_id) && typeof gate.created_at === 'string' &&
      (gate.passed === null || typeof gate.passed === 'boolean') &&
      nullableFinite(gate.sharpe_oos) && nullableFinite(gate.total_return_oos) &&
      nullableFinite(gate.max_drawdown_oos) &&
      (gate.n_obs_oos === null || (Number.isInteger(gate.n_obs_oos) && Number(gate.n_obs_oos) >= 0)) &&
      nullableFinite(gate.mean_window_sharpe) && nullableFinite(gate.min_window_sharpe) &&
      nullableFinite(gate.pct_positive_windows)
  })
}

function ErrorCode({ error }: { error: Error | null }) {
  const code = error instanceof ApiError && error.code !== null
    ? error.code
    : (error?.message ?? 'unknown error')
  return <div className="error-code">{code}</div>
}

export function RefreshError({ error }: { error: Error | null }) {
  if (error === null) return null
  return (
    <section className="banner-stale">
      <span className="micro-label">refresh failed</span>
      <ErrorCode error={error} />
    </section>
  )
}

/**
 * The research strategy board: exactly one row per registered strategy, joined to that
 * identity's latest gate run (`runs board`). Stage/family filtering is client-side over the
 * complete payload and never replaces which run represents a strategy. Read-only: rows navigate
 * through the stable-ID resolver and nothing here mutates state.
 */
export default function StrategyBoard() {
  const query = useFetch<ApiEnvelope<StrategyBoardPayload>>('/api/strategy-board')
  return <StrategyBoardView query={query} />
}

export function StrategyBoardView({
  query,
  compact = false,
}: {
  query: UseFetchResult<ApiEnvelope<StrategyBoardPayload>>
  compact?: boolean
}) {
  const [stage, setStage] = useState<string | null>(null)
  const [family, setFamily] = useState<string | null>(null)
  const [controlsOpen, setControlsOpen] = useState(false)

  const board = isBoardPayload(query.data?.data) ? query.data.data : undefined

  if (board === undefined) {
    if (query.data === undefined && query.loading) {
      return (
        <div className="skeleton-block" style={{ height: 220 }} role="status">
          <span className="sr-only">loading strategy leaderboard</span>
        </div>
      )
    }
    // A failed or unrecognised read is an error, never an empty board.
    return (
      <section className="panel error-panel">
        <span className="micro-label">fetch failed</span>
        {query.data !== undefined ? <div className="error-code">unsupported_schema</div> :
          <ErrorCode error={query.error} />}
        <button type="button" className="retry-btn" onClick={query.refetch}>
          retry
        </button>
      </section>
    )
  }

  if (board.rows.length === 0) {
    return (
      <>
        <StaleNotice env={query.data} />
        <RefreshError error={query.error} />
        <section className="panel all-clear">
          <span className="micro-label">strategy board</span>
          no strategies registered — add one with <code>algua registry add &lt;name&gt;</code>
        </section>
      </>
    )
  }

  const stages = [
    ...LIFECYCLE_ORDER.filter((s) => board.rows.some((r) => r.stage === s)),
    ...new Set(board.rows.map((r) => r.stage).filter((s) => !LIFECYCLE_ORDER.includes(s))),
  ]
  const activeStage = stage !== null && stages.includes(stage) ? stage : null
  const families = [...new Set(board.rows.map((r) => r.family).filter((f): f is string => f !== null))]
    .sort((a, b) => a.localeCompare(b))
  const hasUnknownFamily = board.rows.some((r) => r.family === null)
  const activeFamily = family === UNKNOWN_FAMILY && hasUnknownFamily
    ? family
    : family !== null && families.includes(family) ? family : null
  const visible = board.rows.filter((row) =>
    (activeStage === null || row.stage === activeStage) &&
    (activeFamily === null || (activeFamily === UNKNOWN_FAMILY ? row.family === null : row.family === activeFamily)),
  )
  const familyLabel = activeFamily === UNKNOWN_FAMILY ? 'unknown family' : activeFamily ?? 'all families'

  return (
    <section aria-labelledby="strategy-board-heading">
      <StaleNotice env={query.data} />
      <RefreshError error={query.error} />
      <h2 id="strategy-board-heading" className={compact ? 'micro-label' : 'board-heading'}>
        {compact ? 'strategy board' : 'Strategy evidence'}
      </h2>
      <div className="dim-note num">
        {activeStage === null && activeFamily === null ? board.count : `${visible.length} of ${board.count}`} strategies ·
        latest gate run each
      </div>
      {compact ? (
        <p className="board-disclosure">
          Noncomparable: period/tier unavailable. Metric sorting disabled; exploratory only,
          never promotion or expected profit.
        </p>
      ) : (
        <p className="board-disclosure">
          Exploratory evidence only — not a promotion signal or expected-profit claim. All current
          rows are noncomparable because comparison period and data tier are unavailable; metric
          sorting is disabled and registry order is retained.
        </p>
      )}

      <button
        type="button"
        className="board-controls-toggle"
        aria-expanded={controlsOpen}
        aria-controls="board-controls"
        onClick={() => setControlsOpen((open) => !open)}
      >
        <span>board controls</span>
        <span className="num">{activeStage === null ? 'all stages' : activeStage}</span>
        <span className="num">{familyLabel}</span>
      </button>

      {controlsOpen && (
        <div id="board-controls" className="board-controls-panel">
          <div className="chip-row" role="group" aria-label="strategy stage">
          <button
            type="button"
            className={activeStage === null ? 'filter-chip active' : 'filter-chip'}
            aria-pressed={activeStage === null}
            onClick={() => setStage(null)}
          >
            all stages <span className="num">{board.count}</span>
          </button>
          {stages.map((s) => (
            <button
              key={s}
              type="button"
              className={s === activeStage ? 'filter-chip active' : 'filter-chip'}
              aria-pressed={s === activeStage}
              onClick={() => setStage(s === activeStage ? null : s)}
            >
              {s} <span className="num">{board.rows.filter((r) => r.stage === s).length}</span>
            </button>
          ))}
          </div>

          <div className="chip-row" role="group" aria-label="strategy family">
            <button
              type="button"
              className={activeFamily === null ? 'filter-chip active' : 'filter-chip'}
              aria-pressed={activeFamily === null}
              onClick={() => setFamily(null)}
            >
              all families <span className="num">{board.count}</span>
            </button>
            {families.map((value) => (
              <button
                key={value}
                type="button"
                className={value === activeFamily ? 'filter-chip active' : 'filter-chip'}
                aria-pressed={value === activeFamily}
                onClick={() => setFamily(value === activeFamily ? null : value)}
              >
                {value} <span className="num">{board.rows.filter((r) => r.family === value).length}</span>
              </button>
            ))}
            {hasUnknownFamily && (
              <button
                type="button"
                className={activeFamily === UNKNOWN_FAMILY ? 'filter-chip active' : 'filter-chip'}
                aria-pressed={activeFamily === UNKNOWN_FAMILY}
                onClick={() => setFamily(activeFamily === UNKNOWN_FAMILY ? null : UNKNOWN_FAMILY)}
              >
                unknown family <span className="num">{board.rows.filter((r) => r.family === null).length}</span>
              </button>
            )}
          </div>

          <div className="chip-row" role="group" aria-label="comparison order">
          <button
            type="button"
            className="filter-chip active"
            aria-pressed="true"
          >
            lifecycle
          </button>
          {SORT_OPTIONS.map((opt) => (
            <button
              key={opt.key}
              type="button"
              className="filter-chip"
              aria-pressed="false"
              disabled
              title="Unavailable: comparison period and data tier are not present in strategy-board/v1"
            >
              {opt.label}
            </button>
          ))}
          </div>
        </div>
      )}

      <div className="row-list">
        {visible.length === 0 ? (
          <div className="panel board-filter-empty">no strategies match this stage and family</div>
        ) : visible.map((row) => <BoardRow key={row.strategy_id} row={row} compact={compact} />)}
      </div>
    </section>
  )
}

function BoardMetric({ label, value }: { label: string; value: string }) {
  return <span className="board-metric"><span className="board-k">{label}</span>{value}</span>
}

function known(value: number | null, format: (metric: number | null) => string): string {
  return value === null ? 'UNKNOWN' : format(value)
}

function BoardRow({ row, compact }: { row: StrategyBoardRow; compact: boolean }) {
  const gate = row.latest_gate
  if (compact) {
    return (
      <Link
        to={`/strategy/${row.strategy_id}`}
        className="board-row"
        data-testid="board-row"
        data-strategy={row.name}
        data-run={gate === null ? '' : String(gate.run_id)}
      >
        <div className="board-row-head">
          <span className="row-link board-name" data-testid="board-row-name">{row.name}</span>
          <StageChip stage={row.stage} />
        </div>
        {gate === null ? <div className="dim-note">no usable gate evidence</div> : (
          <div className="board-rail">
            <BoardMetric label="oos" value={known(finite(gate.sharpe_oos), num)} />
            <BoardMetric label="wf" value={known(finite(gate.mean_window_sharpe), num)} />
            <Sparkline
              values={[finite(gate.min_window_sharpe), finite(gate.mean_window_sharpe), finite(gate.sharpe_oos)]}
              label="latest gate: worst walk-forward, mean walk-forward, OOS Sharpe"
            />
            <PassMark passed={gate.passed} />
          </div>
        )}
      </Link>
    )
  }
  return (
    <Link
      to={`/strategy/${row.strategy_id}`}
      className="board-row"
      data-testid="board-row"
      data-strategy={row.name}
      data-run={gate === null ? '' : String(gate.run_id)}
    >
      <div className="board-row-head">
        <div>
          <span className="row-link board-name" data-testid="board-row-name">{row.name}</span>
          <span className="board-identity num">ID {row.strategy_id} · {row.family ?? 'UNKNOWN family'}</span>
        </div>
        <div className="board-tags"><StageChip stage={row.stage} />{gate !== null && <PassMark passed={gate.passed} />}</div>
      </div>
      <div className="board-rail">
        <BoardMetric label="sharpe" value={known(finite(gate?.sharpe_oos), num)} />
        <BoardMetric label="return" value={known(finite(gate?.total_return_oos), pct)} />
        <BoardMetric label="drawdown" value={known(finite(gate?.max_drawdown_oos), pct)} />
        <BoardMetric label="sample" value={gate?.n_obs_oos == null ? 'UNKNOWN' : num(gate.n_obs_oos)} />
      </div>
      <div className="board-meta num">
        <span>tier UNKNOWN</span><span>period UNKNOWN</span>
        <span>observed {gate === null ? 'UNKNOWN' : utcDate(gate.created_at)}</span>
        <span>age UNKNOWN</span>
      </div>
      {gate === null && <div className="dim-note">no usable gate evidence</div>}
    </Link>
  )
}
