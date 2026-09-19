import type { MapSnapshot } from '../api'
import { pct } from '../util'
import { Skeleton } from './States'

type Props = { snapshot: MapSnapshot | undefined; loading: boolean; selected: string; onSelect: (d: string) => void }

export default function TopDyads({ snapshot, loading, selected, onSelect }: Props) {
  if (!snapshot && loading) return <Skeleton lines={8} />
  if (!snapshot) return null
  const max = snapshot.top[0]?.p_raw || 1
  return (
    <div className="top-list">
      {snapshot.top.map((r, i) => (
        <div key={r.dyad} className={`top-row ${r.dyad === selected ? 'active' : ''}`} onClick={() => onSelect(r.dyad)}>
          <span className="mono muted small">{i + 1}</span>
          <span>
            {r.label}
            {r.in_crisis && <span className="tag">in crisis</span>}
          </span>
          <span className="mono small">{pct(r.p_cal, 2)}</span>
          <div className="spark">
            <i style={{ width: `${(100 * r.p_raw) / max}%` }} />
          </div>
        </div>
      ))}
    </div>
  )
}
