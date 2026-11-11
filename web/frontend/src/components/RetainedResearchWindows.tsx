import { num, pct } from '../format'
import { researchWindows } from './retainedMetricExport'

export default function RetainedResearchWindows({ inputs }: { inputs: Record<string, unknown> }) {
  const windows = researchWindows(inputs)
  if (windows === null) return <p className="retained-caption">Dated window metrics unavailable for this evaluation.</p>
  return <section className="retained-windows" aria-label="Research windows">
    <h4>Research windows</h4>
    <p className="retained-caption">Worker-reported windows · unverified</p>
    <div className="retained-window-scroll" role="region" aria-label="Window metric table" tabIndex={0}>
      <table className="retained-metric-table">
        <thead><tr><th scope="col">Start</th><th scope="col">End</th><th scope="col">Return</th>
          <th scope="col">Sharpe</th><th scope="col">Bars</th></tr></thead>
        <tbody>{windows.slice(0, 100).map((window, i) => <tr key={`${window.start}-${i}`}>
          <td>{window.start}</td><td>{window.end}</td>
          <td>{window.total_return === null ? 'Unavailable' : pct(window.total_return)}</td>
          <td>{window.sharpe === null ? 'Unavailable' : num(window.sharpe)}</td>
          <td>{window.n_bars}</td>
        </tr>)}</tbody>
      </table>
    </div>
    {windows.length > 100 && <p className="retained-caption">Showing 100 of {windows.length} windows. The CSV contains all retained windows.</p>}
  </section>
}
