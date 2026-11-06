import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { clearFetchCache } from '../api'
import Research from '../screens/Research'
import RetainedExperiments from './RetainedExperiments'

const cycle = 'fixture-retained'
const reference = 'mlflow:fixture/public-evidence.json#sha256=' + 'a'.repeat(64)
const index = {
  schema_version: 'retained-research-index/v1', metadata_verified: false,
  evidence_mode: 'UNVERIFIED_WORKER', authority: 'none', association: 'cycle_only',
  count: 1, has_more: false, limit: 20,
  attempts: [{ attempt_id: 7, evidence_id: 'idea_attempts:7', idea_id: 6,
    research_cycle_id: cycle, outcome: 'integrity_fail', outcome_at: '2026-11-05T10:59:03Z',
    archive_reference: reference }],
}
const observation = (id: number, value: number | null) => ({
  source_ref: `scratch:${cycle}:runs:${id}`, source_run_id: id, kind: 'backtest',
  strategy_name: `worker_${id}`, strategy_local_id: 1, created_at: '2026-01-01', parent_refs: [],
  provenance: { snapshot_id: 'fixture-bars', seed: null },
  inputs: { params: { lookback: id }, run_provenance: { tier: 'pilot_real_proxy' } },
  model_refs: [{ name: 'fixture-model', version: 1, digest: 'a'.repeat(16) }],
  metrics: { sharpe_is: value }, extra_metrics: {},
})
const detail = {
  schema_version: 'research-memory/v1', research_cycle_id: cycle,
  evidence_mode: 'UNVERIFIED_WORKER', authority: 'none', source_commit: 'b'.repeat(40), worker_exit: 0,
  attempt_refs: [{ evidence_id: 'idea_attempts:7', idea_id: 6 }],
  evaluations: [observation(1, null), observation(2, -0.25)],
  coverage: { retained_evaluations: 2, inherited_run_count: 0, kind_counts: { backtest: 2 },
    truncated_sweeps: [], unrecorded_variant_failures: 'UNKNOWN', model_bytes_preserved: false,
    evaluated_worktree_verified: false },
}

afterEach(() => { cleanup(); clearFetchCache(); vi.unstubAllGlobals() })

function serve(list: unknown = index, payload: unknown = detail, stale = false) {
  const fetch = vi.fn(async (url: string) => ({ ok: true, status: 200, json: async () => ({
    ok: true, data: url.includes(`/${cycle}`) ? payload : list,
    fetched_at: '2026-01-01', stale,
  }) }))
  vi.stubGlobal('fetch', fetch)
  return fetch
}

it('shows retained attempts without registered strategies and selects exact cycle observations', async () => {
  const fetch = serve()
  render(<RetainedExperiments />)
  const button = await screen.findByRole('button', { name: /Inspect.*fixture-retained/ })
  expect(fetch).toHaveBeenCalledTimes(1) // Never fan out archives on list render.
  expect(screen.getByText('1 attempt · not registered strategies')).toBeTruthy()
  expect(screen.getByText(/5 Nov.*10:59.*UTC/)).toBeTruthy()
  expect(within(button).getByText('Not qualified')).toBeTruthy()
  fireEvent.click(button)
  const title = await screen.findByRole('heading', { name: 'worker 1' })
  expect(button.closest('li')?.contains(title)).toBe(true) // Detail follows this mobile selection.
  expect(button.getAttribute('aria-pressed')).toBe('true')
  expect(within(screen.getByRole('group', { name: 'Key research metrics' }))
    .getByText('Unavailable')).toBeTruthy()
  expect(screen.getByText(/worker exit: 0/i)).toBeTruthy()
  expect(screen.getAllByText(/integrity_fail/).length).toBeGreaterThan(0)
  expect(screen.getByText(/cycle-only association/i)).toBeTruthy()
  expect(screen.getByText(/model references only/i)).toBeTruthy()
  expect(screen.getByText(/unrecorded_variant_failures/)).toBeTruthy()
  const disclosures = [...document.querySelectorAll('details')]
  expect(disclosures.length).toBeGreaterThanOrEqual(4)
  expect(disclosures.every(item => !item.open)).toBe(true)
  fireEvent.click(screen.getByText('Details', { exact: true }))
  fireEvent.change(screen.getByRole('combobox', { name: 'Evaluation' }),
    { target: { value: `scratch:${cycle}:runs:2` } })
  expect(screen.getByRole('heading', { name: 'worker 2' })).toBeTruthy()
  expect(within(screen.getByRole('group', { name: 'Key research metrics' }))
    .getByText('-0.25')).toBeTruthy()
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(document.querySelector('a[href^="/strategy/"]')).toBeNull()
})

it('integrates the retained section into Research even when the main strategy board is empty', async () => {
  const envelope = (data: unknown) => ({ ok: true, data, stale: false, fetched_at: '2026-01-01' })
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, status: 200, json: async () => {
    if (url.startsWith('/api/research-memory')) return envelope(index)
    if (url.startsWith('/api/strategies')) return envelope({ data: [] })
    if (url.startsWith('/api/strategy-board')) return envelope({
      schema_version: 'strategy-board/v1', count: 0, rows: [],
    })
    if (url.startsWith('/api/ops')) return envelope({ ok: true, loops: {}, alerting: [] })
    if (url.startsWith('/api/runs')) return envelope({ count: 0, runs: [] })
    return { ok: true, ideas: [], stats: { counts: {} }, stats_window_days: 90, stale: false }
  } })))
  render(<MemoryRouter><Research /></MemoryRouter>)
  expect(await screen.findByRole('button', { name: /Inspect.*fixture-retained/ })).toBeTruthy()
  expect(screen.getByRole('heading', { name: 'Research results' })).toBeTruthy()
  expect(screen.queryByText('No registered strategies yet')).toBeNull()
  expect(document.querySelector<HTMLDetailsElement>('.research-diagnostics')?.open).toBe(false)
})

it('does not display metrics when show does not bind the selected attempt', async () => {
  serve(index, { ...detail, attempt_refs: [{ evidence_id: 'idea_attempts:99', idea_id: 6 }] })
  render(<RetainedExperiments />)
  fireEvent.click(await screen.findByRole('button', { name: /Inspect/ }))
  expect(await screen.findByText(/does not match the selected attempt/i)).toBeTruthy()
  expect(screen.queryByText('worker_1')).toBeNull()
})

it('shows empty and stale index states honestly', async () => {
  serve({ ...index, attempts: [], count: 0 }, detail, true)
  render(<RetainedExperiments />)
  expect(await screen.findByText('No retained archive references recorded.')).toBeTruthy()
  expect(screen.getByText(/stale retained index/i)).toBeTruthy()
})

it('shows archive failure instead of inventing an evaluation', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => url.includes(`/${cycle}`)
    ? { ok: false, status: 502, json: async () => ({ error: 'archive integrity mismatch' }) }
    : { ok: true, status: 200, json: async () => ({ ok: true, data: index, stale: false }) }))
  render(<RetainedExperiments />)
  fireEvent.click(await screen.findByRole('button', { name: /Inspect/ }))
  expect(await screen.findByText('archive integrity mismatch')).toBeTruthy()
  expect(screen.queryByRole('combobox')).toBeNull()
})

it('formats known in-sample metrics while preserving exact raw values behind disclosure', async () => {
  const metrics = { total_return_is: -0.1234, sharpe_is: null, max_drawdown_is: -0.2 }
  serve(index, { ...detail, evaluations: [{ ...observation(1, null), metrics }] })
  render(<RetainedExperiments compact />)
  const group = await screen.findByRole('group', { name: 'Key research metrics' })
  expect(within(group).getByText('IS return')).toBeTruthy()
  expect(within(group).getByText('-12.3%')).toBeTruthy()
  expect(within(group).getByText('-20.0%')).toBeTruthy()
  expect(within(group).getByText('Unavailable')).toBeTruthy()
  expect(document.querySelector<HTMLDetailsElement>('.retained-more')?.open).toBe(false)
  fireEvent.click(screen.getByText('Details', { exact: true }))
  const summary = screen.getByText('All recorded metrics')
  const disclosure = summary.closest('details')!
  expect(disclosure.open).toBe(false)
  fireEvent.click(summary)
  expect(disclosure.open).toBe(true)
  expect(within(disclosure).getByText('-0.1234')).toBeTruthy()
  expect(screen.getByText(/lookback/).closest('details')?.open).toBe(false)
  expect(screen.getByText(/fixture-model/).closest('details')?.open).toBe(false)
  expect(document.querySelector('.retained-compact')).toBeTruthy()
})

it('keeps missing dates honest and execution errors distinct from qualification', async () => {
  serve({ ...index, attempts: [{ ...index.attempts[0], outcome: 'run_error', outcome_at: null }] })
  render(<RetainedExperiments />)
  const row = await screen.findByRole('button', { name: /Inspect/ })
  expect(within(row).getByText('Execution error')).toBeTruthy()
  expect(within(row).getByText(/Date unavailable/)).toBeTruthy()
  expect(screen.queryByText('Not qualified')).toBeNull()
})


it('limits the home preview to three rows and links to the complete archive', async () => {
  const many = { ...index, count: 5, attempts: Array.from({ length: 5 }, (_, i) => ({
    ...index.attempts[0], attempt_id: i + 7, evidence_id: `idea_attempts:${i + 7}`,
  })) }
  const fetch = serve(many)
  render(<RetainedExperiments compact />)
  expect(await screen.findAllByRole('button', { name: /Inspect/ })).toHaveLength(3)
  expect(await screen.findByRole('heading', { name: 'worker 1' })).toBeTruthy()
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(screen.getByRole('link', { name: /View all research/ }).getAttribute('href')).toBe('/research')
  expect(document.querySelector<HTMLDetailsElement>('.retained-more')?.open).toBe(false)
})
