import { Fragment, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, useFetch } from '../api'
import type { UseFetchResult } from '../api'
import { num, pct, utcDate } from '../format'
import type { ApiEnvelope, StrategyBoardGate, StrategyBoardPayload, StrategyBoardRow } from '../types'
import type {
  StrategyBoardComparisonEvidence,
  StrategyBoardEvaluationEvidence,
  StrategyBoardEvidence,
  StrategyBoardEvidenceWrapper,
  StrategyBoardOosEvidence,
  StrategyBoardSnapshotEvidence,
} from '../types'
import { contextKey, observedOrder, parseComparison, parseRecordedProvenance } from './boardComparison'
import type { ObservedMetric, RecordedProvenance } from './boardComparison'
import PassMark from './PassMark'
import Sparkline from './Sparkline'
import StaleNotice from './StaleNotice'
import StageChip from './StageChip'

const SCHEMA_VERSION = 'strategy-board/v1'
const EVIDENCE_SCHEMA_VERSION = 'strategy-board-evidence/v2'
export const STRATEGY_BOARD_EVIDENCE_URL = '/api/strategy-board?include_evidence=true'

type MetricKey = ObservedMetric

interface SortOption {
  key: MetricKey
  label: string
}

/** Observed research metrics; enabled only after explicit same-cohort selection. */
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
  const query = useFetch<ApiEnvelope<StrategyBoardPayload>>(
    STRATEGY_BOARD_EVIDENCE_URL,
  )
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
  const [cohort, setCohort] = useState('')
  const [order, setOrder] = useState<ObservedMetric | null>(null)

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

  const evidenceSchema = (board as unknown as Record<string, unknown>).evidence_schema_version

  if (board.rows.length === 0 && evidenceSchema !== undefined &&
      evidenceSchema !== EVIDENCE_SCHEMA_VERSION) {
    return (
      <>
        <StaleNotice env={query.data} />
        <RefreshError error={query.error} />
        <section className="panel error-panel">
          <div className="board-evidence-summary">evidence INVALID · unsupported evidence schema</div>
        </section>
      </>
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
  const parsedEvidence = new Map<number, ParsedEvidence | null>()
  const comparisons = new Map<number, StrategyBoardComparisonEvidence>()
  if (evidenceSchema === EVIDENCE_SCHEMA_VERSION) for (const row of board.rows) {
    const parsed = row.latest_gate === null ? null : parseEvidence(
      row.evidence, row.latest_gate, (row as unknown as Record<string, unknown>).recorded_provenance,
    )
    parsedEvidence.set(row.strategy_id, parsed)
    if (parsed?.comparison.status === 'COMPARABLE') comparisons.set(row.strategy_id, parsed.comparison)
  }
  const cohorts = new Map<string, { evidence: StrategyBoardComparisonEvidence; rows: StrategyBoardRow[]; conflict: boolean }>()
  for (const row of board.rows) {
    const comparison = comparisons.get(row.strategy_id)
    if (!comparison?.cohort_id || !comparison.context) continue
    const existing = cohorts.get(comparison.cohort_id)
    if (existing) {
      existing.rows.push(row)
      existing.conflict ||= contextKey(existing.evidence.context) !== contextKey(comparison.context)
    } else cohorts.set(comparison.cohort_id, { evidence: comparison, rows: [row], conflict: false })
  }
  const availableCohorts = [...cohorts.entries()].filter(([, c]) => !c.conflict && c.rows.length >= 2)
  const activeCohort = !compact && !query.data?.stale && query.error === null
    ? availableCohorts.find(([id]) => id === cohort)?.[1] : undefined
  const candidates = activeCohort === undefined ? [] : visible.filter(row =>
    comparisons.get(row.strategy_id)?.cohort_id === cohort)
  const activeOrder = order !== null && candidates.filter(r => r.latest_gate?.[order] != null).length >= 2
    ? order : null
  const ordered = activeOrder === null ? [] : observedOrder(candidates.filter(
    r => r.latest_gate?.[activeOrder] != null), activeOrder)
  const orderedIds = new Set(ordered.map(r => r.strategy_id))
  const remaining = visible.filter(r => !orderedIds.has(r.strategy_id))
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
      <p className="board-disclosure">
        {compact ? 'Comparison is available on the leaderboard with recorded context. ' :
          'Exploratory research only. Select a matching cohort to order observed OOS metrics; other rows stay unranked. '}
        Never promotion or expected profit. Paper/live results remain in their own detail sections.
      </p>

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

          {!compact && <label className="board-cohort-control">
            comparison cohort
            <select aria-label="comparison cohort" value={cohort}
              onChange={e => { setCohort(e.target.value); setOrder(null) }}>
              <option value="">select cohort · lifecycle order</option>
              {availableCohorts.map(([id, c]) => <option key={id} value={id}>
                {id.slice(0, 8)} · {c.evidence.context?.timeframe} · {c.evidence.context?.oos.start}–{c.evidence.context?.oos.end}
                {' · '}{c.rows.length} strategies
              </option>)}
            </select>
          </label>}
          {availableCohorts.length === 0 && <p className="dim-note">
            No matching recorded cohort. Metric sorting disabled; missing context stays UNKNOWN.
          </p>}
          <div className="chip-row" role="group" aria-label="comparison order">
            <button type="button" className={activeOrder === null ? 'filter-chip active' : 'filter-chip'}
              aria-pressed={activeOrder === null} onClick={() => setOrder(null)}>lifecycle</button>
            {SORT_OPTIONS.map(opt => <button key={opt.key} type="button"
              className={activeOrder === opt.key ? 'filter-chip active' : 'filter-chip'}
              aria-pressed={activeOrder === opt.key}
              disabled={!activeCohort || candidates.filter(r => r.latest_gate?.[opt.key] != null).length < 2}
              title="Choose a cohort with at least two observed values; stale/error reads cannot be ordered"
              onClick={() => setOrder(opt.key)}>{opt.label}</button>)}
          </div>
        </div>
      )}

      {activeOrder !== null && <p className="board-disclosure">
        Observed {SORT_OPTIONS.find(o => o.key === activeOrder)?.label} · descending
        {' · '}NONPIT/current-survivor proxy · {ordered.length} strategies · historical research only
      </p>}
      <div className="row-list">
        {visible.length === 0 ? <div className="panel board-filter-empty">no strategies match this stage and family</div>
          : [...ordered, ...remaining].map((row, index) => <Fragment key={row.strategy_id}>
            {activeOrder !== null && index === ordered.length &&
              <h3 className="micro-label">Other cohorts and unranked</h3>}
            <BoardRow row={row} compact={compact} evidenceSchema={evidenceSchema}
              evidence={parsedEvidence.get(row.strategy_id) ?? null} />
          </Fragment>)}
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

function BoardRow({
  row,
  compact,
  evidenceSchema,
  evidence,
}: {
  row: StrategyBoardRow
  compact: boolean
  evidenceSchema: unknown
  evidence: ParsedEvidence | null
}) {
  const gate = row.latest_gate
  if (compact) {
    return (
      <Link
        to={`/strategy/${row.strategy_id}`}
        aria-label={`View ${row.name} strategy details (ID ${row.strategy_id})`}
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
        <BoardEvidence row={row} evidenceSchema={evidenceSchema} compact evidence={evidence} />
      </Link>
    )
  }
  return (
    <Link
      to={`/strategy/${row.strategy_id}`}
      aria-label={`View ${row.name} strategy details (ID ${row.strategy_id})`}
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
        <span>observed {gate === null ? 'UNKNOWN' : utcDate(gate.created_at)}</span>
        <span>age UNKNOWN</span>
      </div>
      {gate === null && <div className="dim-note">no usable gate evidence</div>}
      <BoardEvidence row={row} evidenceSchema={evidenceSchema} compact={false} evidence={evidence} />
    </Link>
  )
}

type AtomicEvidence<T> = StrategyBoardEvidenceWrapper<T>

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' ? value as Record<string, unknown> : null
}

function exactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value).sort()
  const expected = [...keys].sort()
  return actual.length === expected.length && actual.every((key, index) => key === expected[index])
}

function text(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0
}

function positiveInt(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) > 0
}

function canonicalDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}

function parseAtomic<T>(
  value: unknown,
  parseValue: (candidate: unknown) => T | null,
): AtomicEvidence<T> {
  const wrapper = record(value)
  if (wrapper === null || !exactKeys(wrapper, ['status', 'reason', 'value'])) {
    return { status: 'INVALID', reason: 'malformed response', value: null }
  }
  const status = wrapper?.status
  const reason = wrapper?.reason
  if (status !== 'VALID' && status !== 'UNAVAILABLE' && status !== 'INVALID') {
    return { status: 'INVALID', reason: 'malformed response', value: null }
  }
  const boundedReason = typeof reason === 'string' && (
    status === 'UNAVAILABLE' ? UNAVAILABLE_REASONS.has(reason) : INVALID_REASONS.has(reason)
  )
  if (reason !== null && reason !== undefined && typeof reason !== 'string') {
    return { status: 'INVALID', reason: 'malformed response', value: null }
  }
  if (status !== 'VALID') {
    return wrapper?.value === null && boundedReason
      ? { status, reason: typeof reason === 'string' ? reason : null, value: null }
      : { status: 'INVALID', reason: 'malformed response', value: null }
  }
  const parsed = parseValue(wrapper?.value)
  return parsed === null || reason !== null
    ? { status: 'INVALID', reason: 'malformed response', value: null }
    : { status: 'VALID', reason: null, value: parsed }
}

function parseEvaluation(value: unknown): StrategyBoardEvaluationEvidence | null {
  const candidate = record(value)
  return candidate !== null && exactKeys(
    candidate, ['period_start', 'period_end', 'timeframe', 'metric_schema_version'],
  ) && canonicalDate(candidate.period_start) &&
    canonicalDate(candidate.period_end) && candidate.period_start <= candidate.period_end &&
    text(candidate.timeframe) && positiveInt(candidate.metric_schema_version)
    ? candidate as unknown as StrategyBoardEvaluationEvidence
    : null
}

function parseOos(value: unknown): StrategyBoardOosEvidence | null {
  const candidate = record(value)
  return candidate !== null && exactKeys(candidate, ['holdout_start', 'holdout_end', 'n_bars']) &&
    canonicalDate(candidate.holdout_start) &&
    canonicalDate(candidate.holdout_end) && candidate.holdout_start <= candidate.holdout_end &&
    positiveInt(candidate.n_bars)
    ? candidate as unknown as StrategyBoardOosEvidence
    : null
}

const DATA_TIERS = new Set(['pilot_real_proxy', 'verified_pit', 'synthetic_fixture'])
const PILOT_PROXY_LIMITATIONS = [
  'adjusted_close_vendor_revisable',
  'corporate_actions_unverified',
  'delisted_names_absent',
  'event_timing_unavailable',
  'historical_market_cap_unavailable',
  'point_in_time_universe_unavailable',
  'survivorship_biased_selection',
] as const
const SYNTHETIC_LIMITATION = 'synthetic_not_market_data'
const LIMITATION_VOCABULARY = new Set([...PILOT_PROXY_LIMITATIONS, SYNTHETIC_LIMITATION])
const UNIVERSE_METHOD = /^[a-z0-9][a-z0-9._/:+\-]{0,159}$/
const PROVIDER = /^[a-z0-9][a-z0-9._-]{0,63}$/
const UNAVAILABLE_REASONS = new Set([
  'missing_fields', 'no_holdout_pointer', 'missing_run_oos_count', 'no_snapshot_pointer',
  'snapshot_not_found', 'provenance_absent', 'source_unavailable',
])
const INVALID_REASONS = new Set([
  'malformed_fields',
  'dangling_holdout_pointer', 'strategy_mismatch', 'count_mismatch',
  'dangling_evaluation_pointer', 'evaluation_binding_mismatch', 'interval_binding_mismatch',
  'malformed_provenance', 'unsupported_provenance_schema', 'snapshot_binding_mismatch',
  'pit_verifier_unavailable', 'conflicting_snapshot_records',
])

function parseSnapshot(value: unknown): StrategyBoardSnapshotEvidence | null {
  const candidate = record(value)
  if (candidate === null || !exactKeys(candidate, [
    'schema_version', 'data_tier', 'universe_method', 'limitations', 'coverage_start',
    'coverage_end', 'provider',
  ]) || candidate.schema_version !== 'pilot-provenance/v1' ||
      typeof candidate.data_tier !== 'string' || !DATA_TIERS.has(candidate.data_tier) ||
      typeof candidate.universe_method !== 'string' ||
      !UNIVERSE_METHOD.test(candidate.universe_method) ||
      typeof candidate.provider !== 'string' || !PROVIDER.test(candidate.provider) ||
      !Array.isArray(candidate.limitations) || !candidate.limitations.every(text) ||
      !canonicalDate(candidate.coverage_start) || !canonicalDate(candidate.coverage_end) ||
      candidate.coverage_start > candidate.coverage_end) return null

  const limitations = candidate.limitations as string[]
  const unique = new Set(limitations)
  if (unique.size !== limitations.length ||
      limitations.some((limitation) => !LIMITATION_VOCABULARY.has(limitation)) ||
      limitations.some((limitation, index) => limitation !== [...limitations].sort()[index])) {
    return null
  }
  if (candidate.data_tier === 'pilot_real_proxy' && (
    unique.has(SYNTHETIC_LIMITATION) ||
    PILOT_PROXY_LIMITATIONS.some((limitation) => !unique.has(limitation))
  )) return null
  if (candidate.data_tier === 'synthetic_fixture' && !unique.has(SYNTHETIC_LIMITATION)) return null
  if (candidate.data_tier === 'verified_pit' && [
    SYNTHETIC_LIMITATION,
    'point_in_time_universe_unavailable',
    'survivorship_biased_selection',
    'delisted_names_absent',
  ].some((limitation) => unique.has(limitation))) return null
  return candidate as unknown as StrategyBoardSnapshotEvidence
}


type ParsedEvidence = StrategyBoardEvidence & { recorded: RecordedProvenance | null }

function parseEvidence(value: unknown, gate: StrategyBoardGate, recordedRaw: unknown): ParsedEvidence | null {
  const candidate = record(value)
  if (candidate === null || !exactKeys(candidate, [
    'run_id', 'evaluation', 'oos_interval', 'snapshot_provenance', 'comparison',
  ]) || candidate.run_id !== gate.run_id) return null
  const comparison = parseComparison(candidate.comparison)
  if (comparison === null) return null
  const evaluation = parseAtomic(candidate.evaluation, parseEvaluation)
  let oos = parseAtomic(candidate.oos_interval, parseOos)
  if (oos.value !== null) {
    const requested = evaluation.value
    if (gate.n_obs_oos === null || oos.value.n_bars !== gate.n_obs_oos) {
      oos = { status: 'INVALID', reason: 'count_mismatch', value: null }
    } else if (requested === null || oos.value.holdout_start < requested.period_start ||
        oos.value.holdout_end > requested.period_end) {
      oos = { status: 'INVALID', reason: 'malformed response', value: null }
    }
  }
  const rawSnapshot = record(candidate.snapshot_provenance)
  const rawSnapshotValue = record(rawSnapshot?.value)
  const snapshot = rawSnapshot?.status === 'VALID' && rawSnapshotValue?.data_tier === 'verified_pit'
    ? { status: 'INVALID' as const, reason: 'pit_verifier_unavailable', value: null }
    : parseAtomic(candidate.snapshot_provenance, parseSnapshot)
  const recorded = parseRecordedProvenance(recordedRaw)
  const c = comparison.context
  if (comparison.status === 'COMPARABLE' && (c === null || evaluation.value === null ||
      oos.value === null || snapshot.value === null || recorded === null ||
      recorded.bars_snapshot_id !== c.snapshot_id || recorded.bars_content_hash !== c.content_hash ||
      contextKey(recorded.execution_costs) !== contextKey(c.execution_costs) ||
      evaluation.value.metric_schema_version !== 1 || c.period_start !== evaluation.value.period_start ||
      c.period_end !== evaluation.value.period_end || c.timeframe !== evaluation.value.timeframe ||
      c.oos.start !== oos.value.holdout_start || c.oos.end !== oos.value.holdout_end ||
      c.oos.n_bars !== oos.value.n_bars || parseSnapshot(c.source) === null ||
      contextKey(c.source) !== contextKey(snapshot.value) ||
      c.windows[0].start < snapshot.value.coverage_start || c.oos.end > snapshot.value.coverage_end ||
      snapshot.value.data_tier !== 'pilot_real_proxy')) return null
  return {
    run_id: gate.run_id,
    evaluation,
    oos_interval: oos,
    snapshot_provenance: snapshot,
    comparison,
    recorded,
  }
}

function reasonLabel(reason: string | null): string {
  if (reason === null) return 'no reason supplied'
  if (reason === 'pit_verifier_unavailable') return 'PIT verifier unavailable'
  return reason.replaceAll('_', ' ')
}

function AtomicUnavailable({
  label,
  evidence,
}: {
  label: string
  evidence: AtomicEvidence<unknown>
}) {
  return (
    <div className="board-evidence-field">
      <span className="board-evidence-label">{label}</span>
      <span>{evidence.status} · {reasonLabel(evidence.reason)}</span>
    </div>
  )
}

function BoardEvidence({
  row,
  evidenceSchema,
  compact,
  evidence,
}: {
  row: StrategyBoardRow
  evidenceSchema: unknown
  compact: boolean
  evidence: ParsedEvidence | null
}) {
  // Research already has its own dense decision/evidence surfaces. Keep this secondary inventory
  // lean; the primary leaderboard renders the complete evidence ledger and every limitation.
  if (compact) return null
  const gate = row.latest_gate
  const hasEvidenceMember = Object.hasOwn(row, 'evidence')
  if (evidenceSchema === undefined) {
    return hasEvidenceMember
      ? <div className="board-evidence-summary">evidence INVALID · evidence schema missing</div>
      : <div className="board-evidence-summary">evidence extension unavailable · no inference</div>
  }
  if (evidenceSchema !== EVIDENCE_SCHEMA_VERSION) {
    return <div className="board-evidence-summary">evidence INVALID · unsupported evidence schema</div>
  }
  if (!hasEvidenceMember) {
    return <div className="board-evidence-summary">evidence INVALID · evidence member missing</div>
  }
  const rawEvidence = (row as unknown as Record<string, unknown>).evidence
  if (gate === null) {
    return rawEvidence === null
      ? <div className="board-evidence-summary">evidence unavailable · no identity-bound gate run</div>
      : <div className="board-evidence-summary">evidence INVALID · evidence supplied without a latest gate</div>
  }
  if (evidence === null) {
    return <div className="board-evidence-summary">evidence INVALID · run-bound response malformed</div>
  }
  const snapshot = evidence.snapshot_provenance
  const costs = evidence.recorded?.execution_costs ?? null
  return (
    <div className="board-evidence" data-testid="board-evidence">
      <div className="board-evidence-trust">
        Metadata-bound only — VALID is not payload or PIT proof and does not qualify a strategy.
      </div>
      <div className="board-evidence-grid">
        {evidence.evaluation.value === null ? (
          <AtomicUnavailable label="requested evaluation" evidence={evidence.evaluation} />
        ) : (
          <div className="board-evidence-field">
            <span className="board-evidence-label">requested evaluation</span>
            <span className="num">
              {evidence.evaluation.value.period_start}–{evidence.evaluation.value.period_end} ·{' '}
              {evidence.evaluation.value.timeframe} · metric schema{' '}
              {evidence.evaluation.value.metric_schema_version}
            </span>
          </div>
        )}
        {evidence.oos_interval.value === null ? (
          <AtomicUnavailable label="lineage-valid OOS" evidence={evidence.oos_interval} />
        ) : (
          <div className="board-evidence-field">
            <span className="board-evidence-label">lineage-valid OOS</span>
            <span className="num">
              {evidence.oos_interval.value.holdout_start}–{evidence.oos_interval.value.holdout_end} ·{' '}
              {evidence.oos_interval.value.n_bars} bars
            </span>
          </div>
        )}
        {snapshot.value === null ? (
          <AtomicUnavailable label="snapshot provenance" evidence={snapshot} />
        ) : (
          <>
            <div className="board-evidence-field">
              <span className="board-evidence-label">snapshot coverage</span>
              <span className="num">{snapshot.value.coverage_start}–{snapshot.value.coverage_end}</span>
            </div>
            <div className="board-evidence-field">
              <span className="board-evidence-label">data tier</span>
              <span>{snapshot.value.data_tier}</span>
            </div>
            <div className="board-evidence-field">
              <span className="board-evidence-label">source context</span>
              <span>{snapshot.value.provider} · {snapshot.value.universe_method}</span>
            </div>
            <div className="board-evidence-limitations">
              <span className="board-evidence-label">declared limitations · all</span>
              {snapshot.value.limitations.length === 0 ? (
                <span>none declared</span>
              ) : (
                <ul>{snapshot.value.limitations.map((limitation) => (
                  <li key={limitation}>{limitation}</li>
                ))}</ul>
              )}
            </div>
          </>
        )}
      </div>
      {costs !== null && evidence.comparison.status === 'UNKNOWN' && <div className="board-evidence-comparison">
        <div>Recorded fees {costs.fees} of trade notional/side</div>
        <div>slippage {costs.slippage} adverse price fraction/side · {costs.model}</div>
      </div>}
      <div className="board-evidence-comparison">
        {evidence.comparison.status === 'COMPARABLE' && evidence.comparison.context !== null ? <>
          Research cohort {evidence.comparison.cohort_id?.slice(0, 8)} · NONPIT/current-survivor proxy
          <div>Continuous portfolio tail holdout · {evidence.comparison.context.windows.length} windows
            {' · '}embargo {evidence.comparison.context.embargo} bars
            {' · '}holdout fraction {evidence.comparison.context.holdout_frac}</div>
          <div>Net daily returns · Sharpe √252, rf 0, sample std · compounded return · drawdown ≤ 0</div>
          <div>Fees {evidence.comparison.context.execution_costs.fees} of trade notional/side
            {' · '}slippage {evidence.comparison.context.execution_costs.slippage} adverse price fraction/side
            {' · '}vectorbt.from_orders</div>
          <div>Lag {evidence.comparison.context.execution.decision_lag_bars} bars
            {' · '}fill {evidence.comparison.context.execution.fill_basis.replaceAll('_', ' ')}
            {' · '}valuation {evidence.comparison.context.execution.valuation_basis.replaceAll('_', ' ')}
            {' · '}vendor-adjusted units · fractional target weights · cash shared
            {' · '}initial simulated cash {evidence.comparison.context.execution.initial_cash}</div>
          <div>Snapshot {evidence.comparison.context.snapshot_id}
            {' · '}selected research gate run <span className="num">{gate.run_id}</span></div>
        </> : <>comparison UNKNOWN · {evidence.comparison.reasons.map(reasonLabel).join(' · ')}</>}
      </div>
    </div>
  )
}
