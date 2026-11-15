import { cleanup, render, screen } from '@testing-library/react'
import { useEffect } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import App, { useSetFetchedAt } from './App'
import { clearFetchCache } from './api'

let inboxItems: unknown[] = []

/** In-memory storage: Node 25's own experimental `localStorage` global shadows jsdom's. */
function memoryStorage(): Storage {
  const m = new Map<string, string>()
  return {
    get length() { return m.size },
    clear: () => m.clear(),
    getItem: (k) => m.get(k) ?? null,
    key: (i) => [...m.keys()][i] ?? null,
    removeItem: (k) => { m.delete(k) },
    setItem: (k, v) => { m.set(k, String(v)) },
  }
}

beforeEach(() => {
  clearFetchCache()
  inboxItems = []
  Object.defineProperty(window, 'localStorage', { value: memoryStorage(), configurable: true })
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: true, status: 200,
    json: async () => ({ ok: true, data: { ok: true, items: inboxItems }, fetched_at: '2026-11-13T00:00:00Z', stale: false }),
  })) as unknown as typeof fetch)
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

function Screen() {
  const setFetchedAt = useSetFetchedAt()
  useEffect(() => setFetchedAt('2026-11-06T10:00:00Z'), [setFetchedAt])
  return <div>content</div>
}

function mount(path = '/') {
  return render(<MemoryRouter initialEntries={[path]}>
    <Routes><Route element={<App />}><Route path="*" element={<Screen />} /></Route></Routes>
  </MemoryRouter>)
}

it('provides the three tabs Home, Strategies and Inbox in bottom navigation', () => {
  const { container } = mount()
  const nav = screen.getByRole('navigation', { name: 'Main navigation' })
  expect(nav.className).toBe('bottom-nav')
  expect(nav.querySelectorAll('a')).toHaveLength(3)
  expect(nav.querySelectorAll('svg')).toHaveLength(3)
  for (const [name, href] of [['Home', '/'], ['Strategies', '/strategies'], ['Inbox', '/inbox']]) {
    expect(screen.getByRole('link', { name }).getAttribute('href')).toBe(href)
  }
  expect(screen.getByRole('link', { name: 'Home' }).getAttribute('aria-current')).toBe('page')
  expect(container.querySelector('header nav')).toBeNull()
  expect(screen.queryByRole('link', { name: 'Portfolio' })).toBeNull()
})

it.each([
  ['Strategies', '/strategies'],
  ['Strategies', '/strategies/research'],
  ['Inbox', '/inbox'],
])('marks %s as the current section at %s', (name, path) => {
  mount(path)
  expect(screen.getByRole('link', { name }).getAttribute('aria-current')).toBe('page')
})

it('Home and the Strategies list draw their own header; other screens keep the shell header', () => {
  const home = mount('/')
  expect(home.container.querySelector('header.shell-header')).toBeNull()
  cleanup()
  const list = mount('/strategies')
  expect(list.container.querySelector('header.shell-header')).toBeNull()
  cleanup()
  const other = mount('/strategies/research')
  expect(other.container.querySelector('header.shell-header .brand')).not.toBeNull()
})

it('gives strategy pages a back-to-Strategies control and publishes update time in the footer', () => {
  const { container } = mount('/s/example')
  expect(container.querySelector('header.shell-header')).toBeNull()
  expect(screen.getByRole('button', { name: 'Strategies' })).not.toBeNull()
  expect(container.querySelector('header time')).toBeNull()
  expect(container.querySelector('footer time')?.getAttribute('datetime')).toBe('2026-11-06T10:00:00Z')
  expect(container.querySelector('footer')?.textContent).toContain('Updated')
})

it('badges Inbox with items whose journey moved since the Inbox was last viewed', async () => {
  window.localStorage.setItem('algua.inbox.seen', JSON.stringify({ 1: 'queued|Queued for the next leap', 2: 'taken|Inspiration' }))
  inboxItems = [
    { id: 1, status: 'taken', journey: [{ label: 'Inspiration', tone: 'neutral' }] },
    { id: 2, status: 'taken', journey: [{ label: 'Inspiration', tone: 'neutral' }] },
    { id: 3, status: 'queued', journey: [{ label: 'Queued for the next leap', tone: 'pending' }] },
  ]
  mount('/')
  const badge = await screen.findByTestId('inbox-badge')
  expect(badge.textContent).toBe('1')
  // The badge never changes the link's name.
  expect(screen.getByRole('link', { name: 'Inbox' })).toBeTruthy()
})

it('shows no Inbox badge on a first visit', async () => {
  inboxItems = [{ id: 1, status: 'taken', journey: [{ label: 'Inspiration', tone: 'neutral' }] }]
  mount('/')
  await new Promise((r) => setTimeout(r, 20))
  expect(screen.queryByTestId('inbox-badge')).toBeNull()
})
