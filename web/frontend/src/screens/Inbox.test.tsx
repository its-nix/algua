import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { clearFetchCache } from '../api'
import type { ApiEnvelope, InboxItem } from '../types'
import Inbox from './Inbox'

const env = <T,>(data: T): ApiEnvelope<T> =>
  ({ ok: true, data, fetched_at: '2026-11-14T12:00:00+00:00', stale: false })

const item = (over: Partial<InboxItem>): InboxItem => ({
  id: 1, created_at: '2026-11-14T11:59:30+00:00', kind: 'link', url: null, title: null, note: null,
  file_path: null, text: null, status: 'queued', taken_at: null, inspiration_id: null,
  journey: [{ label: 'Queued for the next leap', tone: 'pending' }], ...over,
})

const ITEMS: InboxItem[] = [
  item({ id: 4, url: 'https://www.youtube.com/watch?v=abc', title: 'Why small caps rebound' }),
  item({ id: 3, url: 'https://x.com/someone/status/1', title: null, status: 'taken',
    created_at: '2026-11-14T09:00:00+00:00',
    journey: [{ label: 'Inspiration', tone: 'neutral' }, { label: 'Idea #34', tone: 'pending' }] }),
  item({ id: 2, kind: 'file', file_path: '/data/inbox/ab/beta.pdf', title: 'Betting against beta.pdf',
    status: 'taken', created_at: '2026-11-12T12:00:00+00:00',
    journey: [{ label: 'Inspiration', tone: 'neutral' }, { label: 'Idea #31', tone: 'neutral' },
      { label: 'Candidate', tone: 'progressed' }] }),
  item({ id: 1, url: 'https://quantpedia.com/turn-of-month', title: 'Turn of the month',
    status: 'taken', created_at: '2026-11-10T12:00:00+00:00',
    journey: [{ label: 'Idea #27', tone: 'neutral' }, { label: 'Refuted: no edge after costs', tone: 'refuted' }] }),
]

type Call = { url: string; init?: RequestInit }
let calls: Call[]
let postResponse: { status: number; body: unknown }

beforeEach(() => {
  clearFetchCache()
  calls = []
  postResponse = { status: 201, body: { ok: true, item: ITEMS[0], duplicate: false } }
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init })
    if (init?.method === 'POST') {
      return { ok: postResponse.status < 300, status: postResponse.status, json: async () => postResponse.body }
    }
    if (url === '/api/inbox') return { ok: true, status: 200, json: async () => env({ ok: true, items: ITEMS }) }
    return { ok: false, status: 404, json: async () => ({ error: 'nope' }) }
  }))
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

function Where() {
  const loc = useLocation()
  return <span data-testid="where">{loc.pathname + loc.search}</span>
}

function renderInbox(path = '/inbox') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes><Route path="/inbox" element={<><Inbox /><Where /></>} /></Routes>
    </MemoryRouter>,
  )
}

const gets = () => calls.filter((c) => (c.init?.method ?? 'GET') === 'GET' && c.url === '/api/inbox')
const posts = () => calls.filter((c) => c.init?.method === 'POST')

async function send(value: string) {
  renderInbox()
  await screen.findByText('Why small caps rebound')
  fireEvent.change(screen.getByPlaceholderText('Paste a link or drop a file'), { target: { value } })
  fireEvent.click(screen.getByRole('button', { name: 'Send' }))
}

it('renders the title, the line and each item with its domain and relative time', async () => {
  renderInbox()
  expect(screen.getByRole('heading', { name: 'Inbox' })).toBeTruthy()
  expect(screen.getByText('Everything you send feeds the next leap run.')).toBeTruthy()
  await screen.findByText('Why small caps rebound')
  expect(screen.getByText('youtube.com · just now')).toBeTruthy()
  // No title: the URL host + path stands in.
  expect(screen.getByText('x.com/someone/status/1')).toBeTruthy()
  expect(screen.getByText('x.com · 3 hours ago')).toBeTruthy()
  expect(screen.getByText('Paper · 2 days ago')).toBeTruthy()
  expect(screen.getByText('quantpedia.com · 4 days ago')).toBeTruthy()
  const tiles = [...document.querySelectorAll('.inbox-src')].map((el) => el.getAttribute('data-src'))
  expect(tiles).toEqual(['video', 'chat', 'document', 'link'])
})

it('chips use tone colors', async () => {
  renderInbox()
  await screen.findByText('Why small caps rebound')
  const tone = (label: string) => screen.getByText(label).getAttribute('data-tone')
  expect(screen.getAllByText('Queued for the next leap')[0].getAttribute('data-tone')).toBe('pending')
  expect(tone('Candidate')).toBe('progressed')
  expect(tone('Refuted: no edge after costs')).toBe('refuted')
  expect(tone('Idea #31')).toBe('neutral')
  // jsdom applies no stylesheet: check the rules that give each tone its color.
  const css = readFileSync(join(process.cwd(), 'src/screens/inbox.css'), 'utf8')
  expect(css).toMatch(/\[data-tone='pending'\]\s*\{[^}]*var\(--amber\)/)
  expect(css).toMatch(/\[data-tone='progressed'\]\s*\{[^}]*var\(--green\)/)
  expect(css).toMatch(/\[data-tone='refuted'\]\s*\{[^}]*var\(--red\)/)
})

it('pasting a URL posts {url}', async () => {
  await send('  https://quantpedia.com/strategies/x  ')
  await waitFor(() => expect(posts()).toHaveLength(1))
  const [p] = posts()
  expect(p.url).toBe('/api/inbox')
  expect(new Headers(p.init?.headers).get('content-type')).toBe('application/json')
  expect(JSON.parse(String(p.init?.body))).toEqual({ url: 'https://quantpedia.com/strategies/x' })
})

it('plain text posts {text}', async () => {
  await send('Look at overnight returns in small caps')
  await waitFor(() => expect(posts()).toHaveLength(1))
  expect(JSON.parse(String(posts()[0].init?.body))).toEqual({ text: 'Look at overnight returns in small caps' })
})

it('a send refetches the list and clears the field', async () => {
  await send('https://example.com/a')
  await waitFor(() => expect(gets().length).toBeGreaterThanOrEqual(2))
  expect((screen.getByPlaceholderText('Paste a link or drop a file') as HTMLInputElement).value).toBe('')
  expect(await screen.findByText('Added to Inbox')).toBeTruthy()
})

it('a file is sent as multipart', async () => {
  renderInbox()
  await screen.findByText('Why small caps rebound')
  const file = new File(['%PDF-1.4'], 'paper.pdf', { type: 'application/pdf' })
  fireEvent.change(screen.getByLabelText('Attach a file'), { target: { files: [file] } })
  expect(screen.getByText('paper.pdf')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Send' }))
  await waitFor(() => expect(posts()).toHaveLength(1))
  const body = posts()[0].init?.body
  expect(body).toBeInstanceOf(FormData)
  expect(((body as FormData).get('file') as File).name).toBe('paper.pdf')
  // The browser sets the multipart boundary itself.
  expect(new Headers(posts()[0].init?.headers).get('content-type')).toBeNull()
})

it('403 shows "Only the owner can add to the Inbox"', async () => {
  postResponse = { status: 403, body: { ok: false, error: 'not the owner', code: 'forbidden' } }
  await send('https://example.com/a')
  expect(await screen.findByText('Only the owner can add to the Inbox')).toBeTruthy()
  // The typed link is kept so the owner can retry.
  expect((screen.getByPlaceholderText('Paste a link or drop a file') as HTMLInputElement).value)
    .toBe('https://example.com/a')
})

it('?shared=1 shows toast', async () => {
  renderInbox('/inbox?shared=1')
  expect(await screen.findByText('Added to Inbox')).toBeTruthy()
  // The flag is consumed so a reload does not repeat the toast.
  await waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/inbox'))
})

it('the share tip shows on Android only', async () => {
  vi.stubGlobal('navigator', { ...navigator, userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)' })
  const { unmount } = renderInbox()
  await screen.findByText('Why small caps rebound')
  expect(screen.queryByText('Share straight from any app')).toBeNull()
  unmount()
  vi.stubGlobal('navigator', { ...navigator, userAgent: 'Mozilla/5.0 (Linux; Android 15; Pixel 9) Chrome/131' })
  renderInbox()
  expect(await screen.findByText('Share straight from any app')).toBeTruthy()
  expect(screen.getByText('In X, YouTube or Files, tap Share, then Algua.')).toBeTruthy()
})

it('the toast goes away on its own', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  renderInbox('/inbox?shared=1')
  expect(await screen.findByText('Added to Inbox')).toBeTruthy()
  await act(async () => { vi.advanceTimersByTime(5000) })
  expect(screen.queryByText('Added to Inbox')).toBeNull()
})
