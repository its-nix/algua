import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, it } from 'vitest'
import App from './App'

afterEach(cleanup)

it('keeps the leaderboard directly reachable in primary navigation without a bottom bar', () => {
  const { container } = render(
    <MemoryRouter initialEntries={['/']}>
      <Routes><Route element={<App />}><Route index element={<div>home</div>} /></Route></Routes>
    </MemoryRouter>,
  )

  const nav = screen.getByRole('navigation', { name: 'Main navigation' })
  expect(nav.querySelectorAll('a')).toHaveLength(4)
  expect(screen.getByRole('link', { name: 'Leaderboard' }).getAttribute('href')).toBe('/')
  expect(screen.getByRole('link', { name: 'Leaderboard' }).getAttribute('aria-current')).toBe('page')
  expect(screen.getByRole('link', { name: 'System' }).getAttribute('href')).toBe('/now')
  expect(screen.getByRole('link', { name: 'Portfolio' }).getAttribute('href')).toBe('/money')
  expect(screen.getByRole('link', { name: 'Research' }).getAttribute('href')).toBe('/research')
  expect(container.querySelector('.tabbar')).toBeNull()
})

