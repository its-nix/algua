import { useId } from 'react'

/** A light moving average: takes the daily jitter off without moving the endpoint, which stays
 * the exact last value so the line ends where the number says it does. */
export function smooth(data: number[], k = 2): number[] {
  return data.map((_, i) => {
    const window = data.slice(Math.max(0, i - k), i + k + 1)
    return window.reduce((a, b) => a + b, 0) / window.length
  }).map((v, i, arr) => (i === arr.length - 1 ? data[data.length - 1] : v))
}

export interface EquityLineProps {
  data: number[]
  width: number
  height: number
  color: string
  /** Draws a dotted line at this value (the period's start). */
  base?: number
  /** Gradient fill under the line. */
  fill?: boolean
  dashed?: boolean
  /** Fixed scale bounds; default is the data's own min/max (and the base). */
  lo?: number
  hi?: number
  /** End dot with a halo; the line stops 18px short of the right edge to make room for it. */
  dot?: boolean
  strokeWidth?: number
  className?: string
}

/** Vertical pad: at least the halo radius (8), so a dot on the max or min never clips. */
const PAD = 8
const DOT_INSET = 18

/** An equity line scaled to its own min/max, the way Robinhood and Apple Stocks draw it. */
export default function EquityLine({
  data, width, height, color, base, fill = false, dashed = false, lo, hi, dot = true,
  strokeWidth = 2, className,
}: EquityLineProps) {
  const gid = useId().replace(/:/g, '')
  const n = data.length
  const min = lo ?? Math.min(...data, base ?? Infinity)
  const max = hi ?? Math.max(...data, base ?? -Infinity)
  const span = max - min
  // A flat series (span 0) sits on the vertical centre rather than the bottom edge.
  const y = (v: number) => span === 0 ? height / 2 : PAD + (1 - (v - min) / span) * (height - PAD * 2)
  const usable = width - (dot ? DOT_INSET : 0)
  const x = (i: number) => (n < 2 ? usable : (i / (n - 1)) * usable)
  const d = data.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join('')
  const last = n - 1
  const showDot = dot && !dashed && n > 0

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}
      className={className ? `equity-line ${className}` : 'equity-line'}
      data-points={n} aria-hidden="true" focusable="false" style={{ overflow: 'visible' }}>
      {fill && n > 1 && (
        <>
          <defs>
            <linearGradient id={`eq${gid}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.22" />
              <stop offset="100%" stopColor={color} stopOpacity="0" />
            </linearGradient>
          </defs>
          <path d={`${d}L${x(last).toFixed(1)} ${height}L0 ${height}Z`} fill={`url(#eq${gid})`} />
        </>
      )}
      {base !== undefined && n > 0 && (
        <line x1="0" x2={width} y1={y(base)} y2={y(base)} className="equity-base" />
      )}
      {n > 1 && (
        <path d={d} fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinejoin="round"
          strokeLinecap="round" strokeDasharray={dashed ? '4 5' : undefined} />
      )}
      {showDot && (
        <>
          <circle cx={x(last)} cy={y(data[last])} r="8" fill={color} opacity="0.18" />
          <circle cx={x(last)} cy={y(data[last])} r="4" fill={color} />
        </>
      )}
    </svg>
  )
}
