/** Public archive observations only. No gate, lifecycle or private holdout reconstruction. */
export interface MetricObservation {
  source_ref: string
  kind: string
  strategy_name: string
  inputs: Record<string, unknown>
  metrics: Record<string, number | null>
  extra_metrics: Record<string, number | null>
}

export interface ResearchWindow {
  start: string
  end: string
  n_bars: number
  total_return: number | null
  sharpe: number | null
}

const object = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)
const metric = (v: unknown) => v === null || typeof v === 'number' && Number.isFinite(v)
const day = (v: unknown): v is string => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v)
  && Number.isFinite(Date.parse(v)) && new Date(v).toISOString().slice(0, 10) === v

export function retainedParameters(inputs: Record<string, unknown>): Record<string, unknown> {
  if (object(inputs.params)) return inputs.params
  return object(inputs.grid) ? Object.fromEntries(Object.entries(inputs.grid)
    .filter(([, value]) => Array.isArray(value) && value.length === 1)
    .map(([key, value]) => [key, (value as unknown[])[0]])) : {}
}

export function metricEntries(value: MetricObservation): [string, number | null][] {
  return [...Object.entries(value.metrics), ...Object.entries(value.extra_metrics).map(
    ([key, number]): [string, number | null] =>
      [Object.hasOwn(value.metrics, key) ? `extra.${key}` : key, number],
  )]
}

export function researchWindows(inputs: Record<string, unknown>): ResearchWindow[] | null {
  const record = inputs.public_window_record
  if (!object(record) || record.schema_version !== 'public-wf-windows/v1'
    || !Array.isArray(record.windows) || record.windows.length < 2 || record.windows.length > 10000
    || !record.windows.every((w: unknown) => object(w) && day(w.start) && day(w.end)
      && w.start <= w.end && Number.isSafeInteger(w.n_bars) && Number(w.n_bars) > 0
      && metric(w.total_return) && metric(w.sharpe))) return null
  return record.windows.map(w => ({ start: w.start, end: w.end, n_bars: w.n_bars,
    total_return: w.total_return, sharpe: w.sharpe }))
}

function cell(value: unknown): string {
  let text = value == null ? '' : String(value)
  // Quoting alone doesn't prevent spreadsheet formulas in untrusted worker names/labels.
  if (typeof value === 'string' && /^[\s]*[=+\-@\t\r\n]/.test(value)) text = "'" + text
  return '"' + text.replaceAll('"', '""') + '"'
}

export function retainedMetricsCSV(cycle: string, observations: MetricObservation[]): string {
  const rows: unknown[][] = [['cycle', 'source', 'strategy', 'evaluation', 'role', 'evidence_mode', 'authority',
    'window_start', 'window_end', 'metric', 'value_raw']]
  for (const value of observations) {
    const params = retainedParameters(value.inputs)
    const prefix = [cycle, value.source_ref, value.strategy_name, value.kind,
      params.evaluation_role === 'benchmark' ? 'benchmark' : 'unspecified', 'UNVERIFIED_WORKER', 'none']
    for (const [name, number] of metricEntries(value)) {
      rows.push([...prefix, '', '', name, number])
    }
    const windows = ['walk_forward', 'sweep_trial'].includes(value.kind)
      ? researchWindows(value.inputs) ?? [] : []
    for (const window of windows) {
      for (const name of ['total_return', 'sharpe', 'n_bars'] as const) {
        rows.push([...prefix, window.start, window.end, name, window[name]])
      }
    }
  }
  return rows.map(row => row.map(cell).join(',')).join('\r\n') + '\r\n'
}

export function downloadRetainedMetrics(cycle: string, observations: MetricObservation[]): void {
  const url = URL.createObjectURL(new Blob([retainedMetricsCSV(cycle, observations)],
    { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `research-${cycle}.csv`
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}
