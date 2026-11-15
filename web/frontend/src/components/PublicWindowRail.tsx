import { num, pct } from '../format'
import type { PublicWindowRun } from '../types'

export default function PublicWindowRail({ run }: { run: PublicWindowRun }) {
  const items = [
    ['mean Sharpe', run.mean_window_sharpe, num],
    ['min Sharpe', run.min_window_sharpe, num],
    ['std Sharpe', run.std_window_sharpe, num],
    ['positive windows', run.pct_positive_windows, pct],
  ] as const
  return <div className="board-rail" role="group" aria-label="Public WF window statistics">
    {items.map(([label, value, format]) => <span className="board-metric" key={label}>
      <span className="board-k">{label}</span>{value === null ? 'UNKNOWN' : format(value)}
    </span>)}
  </div>
}
