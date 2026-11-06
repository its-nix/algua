import { cleanup, render, screen } from '@testing-library/react'
import { useEffect } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, it } from 'vitest'
import App, { useSetFetchedAt } from './App'

afterEach(cleanup)

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

it('provides three primary icon destinations in bottom navigation', () => {
  const { container } = mount()
  const nav = screen.getByRole('navigation', { name: 'Main navigation' })
  expect(nav.className).toBe('bottom-nav')
  expect(nav.querySelectorAll('a')).toHaveLength(3)
  expect(nav.querySelectorAll('svg')).toHaveLength(3)
  for (const [name, href] of [['Dashboard', '/'], ['Research', '/research'], ['Portfolio', '/money']]) {
    expect(screen.getByRole('link', { name }).getAttribute('href')).toBe(href)
  }
  expect(screen.getByRole('link', { name: 'Dashboard' }).getAttribute('aria-current')).toBe('page')
  expect(container.querySelector('header nav')).toBeNull()
  expect(screen.queryByRole('link', { name: 'System' })).toBeNull()
  expect(screen.queryByRole('link', { name: 'Fleet' })).toBeNull()
})

it.each([['Research', '/research'], ['Portfolio', '/money']])('marks %s as the current section', (name, path) => {
  mount(path)
  expect(screen.getByRole('link', { name }).getAttribute('aria-current')).toBe('page')
})

it('keeps the logo on detail screens and publishes update time in the footer', () => {
  const { container } = mount('/s/example')
  expect(container.querySelector('header .brand')).not.toBeNull()
  expect(screen.getByRole('button', { name: 'Back' })).not.toBeNull()
  expect(container.querySelector('header time')).toBeNull()
  expect(container.querySelector('footer time')?.getAttribute('datetime')).toBe('2026-11-06T10:00:00Z')
  expect(container.querySelector('footer')?.textContent).toContain('Updated')
})
