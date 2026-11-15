import { useState } from 'react'
import EquityLine, { smooth } from '../components/EquityLine'
import HomeIcon from '../components/HomeIcons'
import { money } from '../format'
import type { SeriesPayload, StrategyDetailResponse } from '../types'
import { useWidth } from '../useWidth'
import {
  expectedDaily, expectedPath, fmtPct, laneFor, lanePoints, laneStage, passingHoldout,
  ratio, realized, shortDate, sinceStage, stageEntry, stageLabel, stageWords, windowPoints, type Window,
} from './strategyCurve'
import { currentForwardRow, estimateForwardGate, recordedForwardGate } from './forwardGateView'
import './strategies.css'

const EXPECTED_COLOR = 'rgba(255, 255, 255, 0.38)'
const CHART_HEIGHT = 180
/** Room on the right for the y labels (right 16px + up to "12,345"). */
const Y_GUTTER = 58
/** EquityLine's end-dot inset (its line stops this far short of the right edge). */
const DOT_INSET = 18

/** The Strategy page top (detail.jpg): value since the lane began, the curve with the backtest's
 * expectation dashed behind it, the window control, three metrics beside their backtest or limit,
 * and progress toward the next gate. */
export default function StrategyTop({ detail, series, seriesLoading, seriesError }: {
  detail: StrategyDetailResponse
  series: SeriesPayload | undefined
  seriesLoading: boolean
  seriesError: boolean
}) {
  const stage = detail.registry?.stage ?? null
  const [win, setWin] = useState<Window>('stage')
  const [chartRef, width] = useWidth<HTMLDivElement>(360)

  const operating = stage !== null && laneFor(stage) !== null
  const entryStage = stage === null ? 'paper' : laneStage(stage)
  const entry = stage === null ? null : stageEntry(detail.registry?.transitions, entryStage)
  const since = sinceStage(lanePoints(series, stage ?? ''), entry)
  const holdout = passingHoldout(detail.gates?.gate_evaluations)
  const daily = expectedDaily(holdout)
  const hasTicks = since.length > 0
  const noTicks = operating && !hasTicks && series !== undefined
  const seriesFailed = operating && series === undefined && seriesError

  const raw = windowPoints(since, win === 'backtest' && daily === null ? 'stage' : win).map((p) => p.equity)
  const n = raw.length
  // Drawn lightly smoothed (the end point stays exact); the expectation starts at the true first value.
  const shown = n > 2 ? smooth(raw, 1) : raw
  const backtest = win === 'backtest' && daily !== null
  const expectedLen = backtest ? Math.max(n, Math.round(holdout?.nObs ?? 0)) : n
  const expected = daily !== null && n > 0 ? expectedPath(raw[0], daily, expectedLen) : null
  const lo = Math.min(...shown, ...(expected ?? []))
  const hi = Math.max(...shown, ...(expected ?? []))
  const up = n < 2 || raw[n - 1] >= raw[0]
  const labelled = n > 1 && hi > lo
  // The lines stop short of the y labels; both share one x scale (the end dot's inset included).
  const plotWidth = Math.max(width - (labelled ? Y_GUTTER : 0), 40)
  const expectedWidth = backtest ? plotWidth : plotWidth - DOT_INSET
  // In the Backtest window the actual curve covers only its share of the holdout's length.
  const actualWidth = backtest && expectedLen > 1 ? Math.max(((n - 1) / (expectedLen - 1)) * plotWidth, 1) : plotWidth

  const first = since[0]
  const last = since.at(-1)
  const change = first && last ? last.equity - first.equity : 0
  const changePct = first && first.equity > 0 ? change / first.equity : null
  const r = realized(since)
  const record = stage === null ? null : currentForwardRow(detail.gates?.forward_gate_evaluations, stage, entry)
  const gate = stage === 'paper' || stage === 'forward_tested'
    ? (record !== null ? recordedForwardGate(record) : estimateForwardGate(since, holdout?.sharpe ?? null))
    : null
  const ddLimit = gate?.drawdownLimit ?? null
  const windows: { key: Window; label: string; disabled?: boolean }[] = [
    { key: '1W', label: '1W' }, { key: '1M', label: '1M' },
    { key: 'stage', label: `Since ${stageWords(entryStage)}` },
    { key: 'backtest', label: 'Backtest', disabled: daily === null },
  ]

  return (
    <section className="sd-top" aria-label="Performance">
      <div className="sd-pad">
        <div className="sd-ident">
          <h1 className="sd-name" title={detail.strategy}>{detail.strategy}</h1>
          {stage !== null && <span className="sd-stage">{stageLabel(stage)}</span>}
        </div>
        {operating && (hasTicks ? (
          <>
            <div className="sd-big num-tab">{money(last!.equity)}</div>
            <div className="sd-change num-tab">
              <b className={change < 0 ? 'down' : 'up'}>
                {change < 0 ? '▼' : '▲'} {money(Math.abs(change))}
                {changePct !== null && ` (${Math.abs(changePct * 100).toFixed(1)}%)`}
              </b>
              <span>since {stageWords(entryStage)} · {shortDate(entry ?? first!.date)}</span>
            </div>
          </>
        ) : seriesLoading && series === undefined && <div className="skeleton-block sd-big-skeleton" aria-hidden="true" />)}
      </div>

      {operating && <div className="sd-chart" ref={chartRef}>
        {noTicks && <div className="sd-chart-empty">No ticks yet</div>}
        {seriesFailed && <div className="sd-chart-empty">Equity unavailable</div>}
        {expected !== null && n > 1 && (
          <div data-testid="expected-line" data-end={expected[expected.length - 1].toFixed(2)}>
            <EquityLine data={expected} width={expectedWidth} height={CHART_HEIGHT} color={EXPECTED_COLOR}
              dashed lo={lo} hi={hi} dot={false} strokeWidth={1.5} />
          </div>
        )}
        {n > 0 && (
          <div>
            <EquityLine data={shown} width={actualWidth} height={CHART_HEIGHT} lo={lo} hi={hi} fill
              color={up ? 'var(--green)' : 'var(--red)'} dot={!backtest} />
          </div>
        )}
        {labelled && (
          <div className="sd-yaxis num-tab" aria-hidden="true">
            {[hi, (hi + lo) / 2, lo].map((v, i) => <span key={i}>{Math.round(v).toLocaleString('en-US')}</span>)}
          </div>
        )}
      </div>}

      {n > 1 && (
        <div className="sd-legend">
          <span><i style={{ borderColor: up ? 'var(--green)' : 'var(--red)' }} />{stageLabel(entryStage)}</span>
          {expected !== null && (
            <span><i style={{ borderColor: EXPECTED_COLOR, borderTopStyle: 'dashed' }} />Backtest expectation</span>
          )}
        </div>
      )}

      {operating && (
        <>
          <div className="sd-segctl" role="group" aria-label="Window">
            {windows.map((w) => (
              <button key={w.key} type="button" aria-pressed={w.key === win} disabled={w.disabled}
                onClick={() => setWin(w.key)}><span>{w.label}</span></button>
            ))}
          </div>
          <div className="sd-cells num-tab">
            <Cell label="Sharpe" value={ratio(r.sharpe)}
              note={holdout?.sharpe != null ? `Backtest ${ratio(holdout.sharpe)}` : null} />
            <Cell label="Max drawdown" value={r.maxDrawdown === null ? '—' : r.maxDrawdown < 0
              ? `−${fmtPct(-r.maxDrawdown, 1)}` : fmtPct(0, 1)}
              note={ddLimit !== null ? `Limit ${fmtPct(ddLimit)}` : null} />
            <Cell label="Volatility" value={r.vol === null ? '—' : fmtPct(r.vol, 1)} note={null} />
          </div>
        </>
      )}

      {gate !== null && (
        <div className="sd-card" data-testid="gate-card" data-kind={gate.kind}>
          <h2 className="sd-card-title">Forward gate <span className="num-tab">
            {gate.passed !== null && `${gate.passed ? 'Passed' : 'Failed'} · `}
            {gate.observations} of {gate.required} sessions
          </span></h2>
          <p className="sd-card-note">
            {gate.kind === 'recorded' && gate.asOf !== null
              ? `Recorded evaluation · as of ${shortDate(gate.asOf)}`
              : 'Estimate from ticks — not the gate'}
          </p>
          <div className="sd-meter" role="progressbar" aria-label="Sessions observed" aria-valuemin={0}
            aria-valuemax={gate.required} aria-valuenow={Math.min(gate.observations, gate.required)}>
            <i style={{ width: `${Math.min(gate.observations / gate.required, 1) * 100}%` }} />
          </div>
          <div className="sd-checks num-tab">
            {gate.checks.map((c) => (
              <div key={c.label} className="sd-check" data-testid="gate-check" data-pass={c.passed}>
                <HomeIcon name={c.passed ? 'check' : 'x'} size={16} />
                <span className="sd-check-label">{c.label}</span>
                <b>{c.value}</b>
                <span className="sr-only">{c.passed ? 'passing' : 'not yet'}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}

function Cell({ label, value, note }: { label: string; value: string; note: string | null }) {
  return (
    <div className="sd-cell">
      <span>{label}</span>
      <b>{value}</b>
      {note !== null && <small>{note}</small>}
    </div>
  )
}
