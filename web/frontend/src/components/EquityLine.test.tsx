import { cleanup, render } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import EquityLine, { smooth } from './EquityLine'

afterEach(cleanup)

it('EquityLine end dot stays inside width', () => {
  const data = [0, 12, 8, 30, 25, 60, 90]
  const { container } = render(<EquityLine data={data} width={300} height={140} color="#2fd27a" base={0} fill />)
  const dots = [...container.querySelectorAll('circle')]
  expect(dots.length).toBe(2)
  for (const dot of dots) {
    const cx = Number(dot.getAttribute('cx'))
    expect(cx + 8).toBeLessThanOrEqual(300)
  }
  // The dotted base line spans the full width at the base value.
  expect(container.querySelector('line.equity-base')).not.toBeNull()
})

it('draws a single point without dividing by zero', () => {
  const { container } = render(<EquityLine data={[5]} width={200} height={100} color="#2fd27a" />)
  expect(container.innerHTML).not.toContain('NaN')
})

it('two fills on one page get distinct gradient ids', () => {
  const { container } = render(<>
    <EquityLine data={[0, 1, 2]} width={200} height={100} color="#2fd27a" fill />
    <EquityLine data={[0, 1, 2]} width={200} height={100} color="#2fd27a" fill />
  </>)
  const ids = [...container.querySelectorAll('linearGradient')].map((g) => g.id)
  expect(new Set(ids).size).toBe(2)
})

it('smooth keeps the last value exact', () => {
  expect(smooth([1, 5, 2, 8, 3])[4]).toBe(3)
})
