import { useEffect, useMemo, useState } from 'react'
import { geoNaturalEarth1, geoPath, geoGraticule10 } from 'd3-geo'
import { feature } from 'topojson-client'
import type { FeatureCollection, Geometry } from 'geojson'
import type { Topology, GeometryCollection } from 'topojson-specification'
import type { Country, MapSnapshot } from '../api'
import { heat, dyadParts, pct } from '../util'
import { Skeleton } from './States'

const W = 900
const H = 440

type Props = {
  snapshot: MapSnapshot | undefined
  loading: boolean
  countries: Record<string, Country>
  selected: string
  onSelect: (dyad: string) => void
}

type WorldFC = FeatureCollection<Geometry, { name: string }>

let worldCache: Promise<WorldFC> | null = null
function loadWorld(): Promise<WorldFC> {
  if (!worldCache) {
    worldCache = import('world-atlas/countries-110m.json').then((m) => {
      const topo = (m.default ?? m) as unknown as Topology<{ countries: GeometryCollection<{ name: string }> }>
      return feature(topo, topo.objects.countries) as WorldFC
    })
  }
  return worldCache
}

export default function WorldMap({ snapshot, loading, countries, selected, onSelect }: Props) {
  const [world, setWorld] = useState<WorldFC | null>(null)
  const [hover, setHover] = useState<string | null>(null)
  useEffect(() => {
    loadWorld().then(setWorld)
  }, [])

  const projection = useMemo(() => geoNaturalEarth1().fitSize([W, H], { type: 'Sphere' }), [])
  const path = useMemo(() => geoPath(projection), [projection])
  const numToIso3 = useMemo(() => {
    const m: Record<string, string> = {}
    for (const c of Object.values(countries)) m[c.iso_num] = c.iso3
    return m
  }, [countries])

  const arcs = useMemo(() => {
    if (!snapshot) return []
    return snapshot.top.slice(0, 20).flatMap((row, i) => {
      const [a, b] = dyadParts(row.dyad)
      const ca = countries[a]
      const cb = countries[b]
      if (!ca?.lat || !cb?.lat || ca.lon === null || cb.lon === null) return []
      const p1 = projection([ca.lon, ca.lat])
      const p2 = projection([cb.lon, cb.lat])
      if (!p1 || !p2) return []
      const mx = (p1[0] + p2[0]) / 2
      const my = (p1[1] + p2[1]) / 2 - Math.min(80, Math.hypot(p2[0] - p1[0], p2[1] - p1[1]) * 0.25)
      return [{ row, d: `M${p1[0]},${p1[1]} Q${mx},${my} ${p2[0]},${p2[1]}`, rank: i, p1, p2 }]
    })
  }, [snapshot, countries, projection])

  if (!world) {
    return (
      <div className="map-wrap">
        <Skeleton lines={1} height={H / 2} />
      </div>
    )
  }

  const hovered = hover && snapshot ? snapshot.countries[hover] : undefined
  const graticule = geoGraticule10()

  return (
    <div className="map-wrap" style={{ opacity: loading ? 0.7 : 1, transition: 'opacity 0.2s' }}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="World map of escalation risk">
        <defs>
          <filter id="glow">
            <feGaussianBlur stdDeviation="2.5" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        <path d={path({ type: 'Sphere' }) ?? ''} fill="#0d1320" stroke="#1f2a40" />
        <path d={path(graticule) ?? ''} fill="none" stroke="#162035" strokeWidth={0.5} />
        {world.features.map((f, i) => {
          const iso3 = numToIso3[String(f.id).padStart(3, '0')]
          const c = iso3 && snapshot ? snapshot.countries[iso3] : undefined
          const isSel = iso3 && selected.split('_').includes(iso3)
          return (
            <path
              key={i}
              d={path(f) ?? ''}
              fill={c ? heat(c.pct) : '#1b2436'}
              stroke={isSel ? '#ffd166' : '#0b0f17'}
              strokeWidth={isSel ? 1.5 : 0.5}
              style={{ cursor: c ? 'pointer' : 'default', transition: 'fill 0.4s' }}
              onMouseEnter={() => setHover(iso3 ?? null)}
              onMouseLeave={() => setHover(null)}
              onClick={() => c && onSelect(c.dyad)}
            >
              <title>{f.properties?.name}</title>
            </path>
          )
        })}
        {arcs.map(({ row, d, rank, p1, p2 }) => {
          const isSel = row.dyad === selected
          return (
            <g key={row.dyad} style={{ cursor: 'pointer' }} onClick={() => onSelect(row.dyad)}>
              <path
                d={d}
                fill="none"
                stroke={isSel ? '#ffd166' : '#ff5a3c'}
                strokeOpacity={isSel ? 1 : Math.max(0.25, 1 - rank * 0.045)}
                strokeWidth={isSel ? 2.4 : Math.max(0.8, 2.2 - rank * 0.08)}
                filter={isSel ? 'url(#glow)' : undefined}
              >
                <title>
                  {row.label}: {pct(row.p_cal, 2)}
                </title>
              </path>
              <circle cx={p1[0]} cy={p1[1]} r={isSel ? 3 : 1.8} fill={isSel ? '#ffd166' : '#ff5a3c'} />
              <circle cx={p2[0]} cy={p2[1]} r={isSel ? 3 : 1.8} fill={isSel ? '#ffd166' : '#ff5a3c'} />
            </g>
          )
        })}
        {hover && hovered && countries[hover] && (
          <g transform={`translate(${W - 10}, 18)`} textAnchor="end" fontSize={12}>
            <text fill="#e6ebf5" fontWeight={600}>
              {countries[hover].name}
            </text>
            <text y={16} fill="#8b97ad" fontFamily="IBM Plex Mono, monospace">
              riskiest dyad {hovered.dyad.replace('_', '–')} · {pct(hovered.p_cal, 2)} · top {(100 * (1 - hovered.pct)).toFixed(0)}%
            </text>
          </g>
        )}
      </svg>
      <div className="map-legend">
        <span>calm</span>
        <div className="grad" />
        <span>escalation-risk percentile</span>
      </div>
    </div>
  )
}
