import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, it } from 'vitest'
import App from './App'

afterEach(cleanup)

it('uses accessible secondary monitoring links without a persistent bottom tab bar', () => {
  const { container } = render(
    <MemoryRouter initialEntries={['/']}>
      <Routes><Route element={<App />}><Route index element={<div>home</div>} /></Route></Routes>
    </MemoryRouter>,
  )

  const nav = screen.getByRole('navigation', { name: 'Secondary monitoring' })
  expect(nav.querySelectorAll('a')).toHaveLength(4)
  expect(screen.getByRole('link', { name: 'Ops' }).getAttribute('href')).toBe('/now')
  expect(screen.getByRole('link', { name: 'Fleet' }).getAttribute('href')).toBe('/fleet')
  expect(screen.getByRole('link', { name: 'Money' }).getAttribute('href')).toBe('/money')
  expect(screen.getByRole('link', { name: 'Research' }).getAttribute('href')).toBe('/research')
  expect(container.querySelector('.tabbar')).toBeNull()
})

