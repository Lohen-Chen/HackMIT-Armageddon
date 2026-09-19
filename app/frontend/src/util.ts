import { useEffect, useRef, useState } from 'react'

export const pct = (p: number | null | undefined, digits = 1) =>
  p === null || p === undefined || Number.isNaN(p) ? '—' : `${(100 * p).toFixed(digits)}%`

export const fmt = (x: number | null | undefined, digits = 2) =>
  x === null || x === undefined || Number.isNaN(x) ? '—' : x.toFixed(digits)

/** Compact value formatting: integers for big counts, 3 significant digits for small shares/rates. */
export const fmtVal = (x: number | null | undefined) => {
  if (x === null || x === undefined || Number.isNaN(x)) return '—'
  const a = Math.abs(x)
  if (a >= 100) return x.toFixed(0)
  if (a >= 1) return x.toFixed(2)
  if (a === 0) return '0'
  return x.toPrecision(3).replace(/\.?0+$/, '')
}

export const brier = (p: number, y: number) => (p - y) ** 2

export const addDays = (iso: string, n: number) => {
  const d = new Date(iso + 'T00:00:00Z')
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}

export const daysBetween = (a: string, b: string) =>
  Math.round((new Date(b + 'T00:00:00Z').getTime() - new Date(a + 'T00:00:00Z').getTime()) / 86400000)

/** Snap an ISO date to the panel's Sunday grid (Sunday on or before, matches Store.week). */
export const toWeek = (iso: string) => {
  const d = new Date(iso + 'T00:00:00Z')
  d.setUTCDate(d.getUTCDate() - d.getUTCDay())
  return d.toISOString().slice(0, 10)
}

export const clamp = (x: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, x))

export type Async<T> = { status: 'idle' | 'loading' | 'ok' | 'error'; data?: T; error?: string }

/** Small data-fetching hook with stale-response protection and a debounce for slider scrubbing. */
export function useAsync<T>(fn: (() => Promise<T>) | null, deps: unknown[], debounceMs = 0): Async<T> {
  const [state, setState] = useState<Async<T>>({ status: fn ? 'loading' : 'idle' })
  const seq = useRef(0)
  useEffect(() => {
    if (!fn) {
      setState({ status: 'idle' })
      return
    }
    const id = ++seq.current
    setState((s) => ({ ...s, status: 'loading' }))
    const timer = setTimeout(() => {
      fn().then(
        (data) => {
          if (seq.current === id) setState({ status: 'ok', data })
        },
        (e: unknown) => {
          if (seq.current === id) setState({ status: 'error', error: e instanceof Error ? e.message : String(e) })
        },
      )
    }, debounceMs)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return state
}

/** Colour ramp for probabilities (rank/percentile based so tiny absolute probabilities remain visible). */
export function heat(pctile: number): string {
  const stops: [number, [number, number, number]][] = [
    [0, [27, 36, 54]],
    [0.6, [80, 40, 50]],
    [0.85, [180, 60, 50]],
    [0.95, [255, 90, 60]],
    [1, [255, 209, 102]],
  ]
  const t = clamp(pctile, 0, 1)
  for (let i = 1; i < stops.length; i++) {
    const [t0, c0] = stops[i - 1]
    const [t1, c1] = stops[i]
    if (t <= t1) {
      const u = (t - t0) / (t1 - t0)
      const c = c0.map((a, j) => Math.round(a + (c1[j] - a) * u))
      return `rgb(${c[0]},${c[1]},${c[2]})`
    }
  }
  return 'rgb(255,209,102)'
}

export const dyadParts = (dyad: string) => dyad.split('_') as [string, string]
