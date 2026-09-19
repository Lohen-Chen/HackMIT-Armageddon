import { useEffect, useMemo, useRef, useState } from 'react'
import type { Meta, Onset } from '../api'
import { addDays, daysBetween, toWeek } from '../util'

type Props = {
  meta: Meta
  dyad: string
  date: string
  window: { start: string; end: string }
  label: string
  onsets: Onset[]
  onDyad: (d: string) => void
  onDate: (d: string) => void
  onWindow: (w: { start: string; end: string }) => void
  onLabel: (l: string) => void
  onHero: (h: Meta['heroes'][number]) => void
  activeHero: string | null
}

export default function Controls(p: Props) {
  const [query, setQuery] = useState('')
  const [playing, setPlaying] = useState(false)
  const timer = useRef<number | null>(null)

  const nWeeks = Math.max(1, Math.floor(daysBetween(p.window.start, p.window.end) / 7))
  const idx = Math.round(daysBetween(p.window.start, p.date) / 7)

  useEffect(() => {
    if (!playing) return
    timer.current = window.setInterval(() => {
      const next = addDays(p.date, 7)
      if (next > p.window.end) {
        setPlaying(false)
      } else {
        p.onDate(next)
      }
    }, 700)
    return () => {
      if (timer.current) window.clearInterval(timer.current)
    }
  }, [playing, p])

  const options = useMemo(() => {
    const q = query.trim().toLowerCase()
    const list = p.meta.dyads
    if (!q) return list.slice(0, 60)
    return list.filter((d) => d.label.toLowerCase().includes(q) || d.dyad.toLowerCase().includes(q)).slice(0, 60)
  }, [query, p.meta.dyads])

  const selectedLabel = p.meta.dyads.find((d) => d.dyad === p.dyad)?.label ?? p.dyad.replace('_', ' – ')

  return (
    <div className="card controls">
      <div className="row">
        <div className="hero-chips">
          <span className="small muted" style={{ alignSelf: 'center', marginRight: 4 }}>
            Seeded cases
          </span>
          {p.meta.heroes.map((h) => (
            <button
              key={h.dyad + h.start}
              className={`chip ${p.activeHero === h.dyad + h.start ? 'active' : ''}`}
              onClick={() => p.onHero(h)}
              title={h.crisis}
            >
              {h.label} · {h.start.slice(0, 4)}
            </button>
          ))}
        </div>
        <div className="spacer" />
        <label className="small muted">
          target{' '}
          <select value={p.label} onChange={(e) => p.onLabel(e.target.value)}>
            {p.meta.labels.map((l) => (
              <option key={l} value={l}>
                {l === 'y_icb' ? 'ICB crisis onset' : 'conflict-event surge'}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="row">
        <div style={{ position: 'relative', minWidth: 300 }}>
          <input
            type="text"
            placeholder={`Search country pair… (${selectedLabel})`}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{ width: 320 }}
          />
          {query && (
            <div
              className="card"
              style={{
                position: 'absolute',
                zIndex: 20,
                top: 36,
                left: 0,
                width: 360,
                maxHeight: 280,
                overflow: 'auto',
                padding: 6,
                animation: 'none',
              }}
            >
              {options.length === 0 ? (
                <div className="small muted" style={{ padding: 8 }}>
                  No pair matches “{query}” among the 400 most active dyads.
                </div>
              ) : (
                options.map((o) => (
                  <div
                    key={o.dyad}
                    className={`top-row ${o.dyad === p.dyad ? 'active' : ''}`}
                    style={{ gridTemplateColumns: '1fr auto' }}
                    onClick={() => {
                      p.onDyad(o.dyad)
                      setQuery('')
                    }}
                  >
                    <span>{o.label}</span>
                    <span className="mono muted small">{o.dyad}</span>
                  </div>
                ))
              )}
            </div>
          )}
        </div>
        <div className="mono" style={{ fontSize: 15 }}>
          {selectedLabel}
        </div>
        <div className="spacer" />
        <label className="small muted">
          window{' '}
          <select
            value={nWeeks <= 30 ? '6m' : nWeeks <= 60 ? '1y' : nWeeks <= 120 ? '2y' : '5y'}
            onChange={(e) => {
              const months = { '6m': 6, '1y': 12, '2y': 24, '5y': 60 }[e.target.value] ?? 12
              const end = addDays(p.date, Math.round((months * 30) / 3))
              const start = addDays(end, -months * 30)
              p.onWindow({
                start: start < p.meta.t_min ? p.meta.t_min : start,
                end: end > p.meta.t_max ? p.meta.t_max : end,
              })
            }}
          >
            <option value="6m">6 months</option>
            <option value="1y">1 year</option>
            <option value="2y">2 years</option>
            <option value="5y">5 years</option>
          </select>
        </label>
      </div>

      <div className="replay">
        <button className={playing ? '' : 'primary'} onClick={() => setPlaying((x) => !x)} style={{ minWidth: 76 }}>
          {playing ? '❚❚ pause' : '▶ replay'}
        </button>
        <div>
          <input
            type="range"
            min={0}
            max={nWeeks}
            value={Math.min(nWeeks, Math.max(0, idx))}
            onChange={(e) => {
              setPlaying(false)
              p.onDate(toWeek(addDays(p.window.start, Number(e.target.value) * 7)))
            }}
          />
          <div className="ticks">
            {p.onsets.map((o) => {
              const x = (100 * daysBetween(p.window.start, o.onset_date)) / (nWeeks * 7)
              if (x < 0 || x > 100) return null
              return (
                <span key={o.crisno}>
                  <span className="tick" style={{ left: `${x}%` }} title={`${o.name} onset ${o.onset_date}`} />
                  <span className="tick label" style={{ left: `${x}%` }}>
                    {o.name.length > 28 ? o.name.slice(0, 26) + '…' : o.name}
                  </span>
                </span>
              )
            })}
          </div>
        </div>
        <div className="date">{p.date}</div>
      </div>
      <div className="small muted">
        Forecasts are made with data through the Sunday shown; the horizon is the next 30 days. Nothing after the cursor is used.
      </div>
    </div>
  )
}
