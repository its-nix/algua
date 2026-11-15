import { useLayoutEffect, useRef, useState } from 'react'

/** The element's own width, kept current with a ResizeObserver (`fallback` until measured). */
export function useWidth<T extends HTMLElement>(fallback: number) {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(fallback)
  useLayoutEffect(() => {
    const el = ref.current
    if (el === null) return
    const measure = () => { if (el.clientWidth > 0) setWidth(el.clientWidth) }
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, width] as const
}
