import { act, cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import App from './App'
import { clearFetchCache, getJSON, useFetch } from './api'

function PrivateScreen() {
  const { data, refetch } = useFetch<{ secret: string }>('/api/private')
  return <><div>{data?.secret}</div><button onClick={refetch}>refresh private data</button></>
}

afterEach(() => { cleanup(); clearFetchCache(); vi.unstubAllGlobals() })

it('replaces cached private views after a 401 with a Google sign-in navigation, without retrying', async () => {
  let expired = false
  const fetcher = vi.fn(async () => expired
    ? new Response('{"error":"authentication_required"}', { status: 401 })
    : new Response(JSON.stringify({ secret: 'cached private data', data: { items: [] } })))
  vi.stubGlobal('fetch', fetcher)
  render(<MemoryRouter><Routes><Route element={<App />}><Route index element={<PrivateScreen />} /></Route></Routes></MemoryRouter>)
  await screen.findByText('cached private data')
  expired = true
  await act(async () => { await getJSON('/api/expired').catch(() => {}) })
  expect(screen.queryByText('cached private data')).toBeNull()
  const login = screen.getByRole('link', { name: 'Sign in with Google' })
  const target = new URL(login.getAttribute('href')!, window.location.origin)
  expect(target.pathname).toBe('/oauth2/start')
  expect(target.searchParams.get('rd')).toBe(`${window.location.pathname}${window.location.search}${window.location.hash}`)
  expect(screen.queryByRole('button', { name: /retry|refresh private/ })).toBeNull()
  const calls = fetcher.mock.calls.length
  await act(async () => { document.dispatchEvent(new Event('visibilitychange')) })
  expect(fetcher.mock.calls).toHaveLength(calls)
})

it.each([403, 500])('does not turn HTTP %s into an expired session', async (status) => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status })))
  render(<MemoryRouter><Routes><Route element={<App />}><Route index element={<div>dashboard</div>} /></Route></Routes></MemoryRouter>)
  await act(async () => { await getJSON('/api/failure').catch(() => {}) })
  expect(screen.getByText('dashboard')).toBeTruthy()
  expect(screen.queryByRole('link', { name: 'Sign in with Google' })).toBeNull()
})

it.each(['inbox', 'push-key', 'push-subscribe', 'push-delete'] as const)('offers sign-in for a 401 from %s', async (path) => {
  const { addToInbox } = await import('./inboxSend')
  const { enableAlerts, disableAlerts } = await import('./push')
  const unsubscribe = vi.fn(async () => true)
  const sub = { endpoint: 'https://push.example.test/endpoint', toJSON: () => ({}), unsubscribe }
  const reg = { pushManager: { subscribe: async () => sub, getSubscription: async () => sub } }
  vi.stubGlobal('Notification', { requestPermission: async () => 'granted' })
  vi.stubGlobal('navigator', { serviceWorker: { ready: Promise.resolve(reg), getRegistration: async () => reg } })
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/inbox' && init?.method !== 'POST') return new Response('{"data":{"items":[]}}')
    if (url === '/api/push/key' && path === 'push-subscribe') return new Response('{"key":"AQID"}')
    return new Response('authentication_required', { status: 401 })
  }))
  render(<MemoryRouter><Routes><Route element={<App />}><Route index element={<div>private dashboard</div>} /></Route></Routes></MemoryRouter>)
  await act(async () => {
    const send = path === 'inbox' ? addToInbox({ text: 'test' }) : path === 'push-delete' ? disableAlerts() : enableAlerts()
    await send.catch(() => {})
  })
  expect(screen.getByRole('link', { name: 'Sign in with Google' })).toBeTruthy()
  expect(screen.queryByText('private dashboard')).toBeNull()
  if (path === 'push-subscribe') expect(unsubscribe).toHaveBeenCalledOnce()
})

it('keeps the encoded return address on this origin, including path, query and fragment', async () => {
  const original = window.location.href
  window.history.replaceState({}, '', `${window.location.origin}//example.invalid/path?next=https://other.invalid/#section`)
  try {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 401 })))
    render(<MemoryRouter><Routes><Route element={<App />}><Route index element={<div>dashboard</div>} /></Route></Routes></MemoryRouter>)
    const login = await screen.findByRole('link', { name: 'Sign in with Google' })
    const target = new URL(login.getAttribute('href')!, window.location.origin)
    const rd = target.searchParams.get('rd')!
    expect(rd).toBe('/example.invalid/path?next=https://other.invalid/#section')
    expect(new URL(rd, window.location.origin).origin).toBe(window.location.origin)
  } finally {
    window.history.replaceState({}, '', original)
  }
})
