import type { Forecast, ImportanceItem } from '../api'
import { fmt, fmtVal } from '../util'
import { Skeleton, Empty } from './States'

export default function DriversPanel({ fc, loading }: { fc: Forecast | undefined; loading: boolean }) {
  return (
    <div className="card">
      <h2>
        Why this number
        <span className="right small">SHAP contributions (log-odds)</span>
      </h2>
      {!fc && loading ? (
        <Skeleton lines={6} />
      ) : !fc || !fc.available ? (
        <Empty>No drivers to show.</Empty>
      ) : fc.drivers.mode === 'global' ? (
        <>
          <div className="small muted" style={{ marginBottom: 8 }}>
            Local explanation unavailable for this week; showing global feature importance (gain).
          </div>
          <GlobalBars items={fc.drivers.items} />
        </>
      ) : (
        <>
          {(() => {
            const max = Math.max(1e-6, ...fc.drivers.items.map((d) => Math.abs(d.contribution)))
            return (
              <div className="drivers">
                {fc.drivers.items.map((d) => (
                  <div className="driver" key={d.feature} title={`${d.feature} = ${fmtVal(d.value)}`}>
                    <span>
                      {d.label}
                      {d.value !== null && <span className="muted small mono"> · {fmtVal(d.value)}</span>}
                    </span>
                    <div className="bar">
                      <i
                        className={d.contribution >= 0 ? 'pos' : 'neg'}
                        style={{ width: `${(50 * Math.abs(d.contribution)) / max}%` }}
                      />
                    </div>
                    <span className="mono small" style={{ color: d.contribution >= 0 ? 'var(--accent)' : 'var(--cool)' }}>
                      {d.contribution >= 0 ? '+' : ''}
                      {fmt(d.contribution, 2)}
                    </span>
                  </div>
                ))}
              </div>
            )
          })()}
          <div className="small muted" style={{ marginTop: 10 }}>
            Last 4 weeks: {fc.drivers.recent.n_events_4w.toLocaleString()} events · {fc.drivers.recent.q4_4w.toLocaleString()} material-conflict ·
            mean Goldstein {fmt(fc.drivers.recent.goldstein_mean_4w, 2)}. Orange pushes risk up, blue pushes it down; base log-odds{' '}
            {fmt(fc.drivers.bias_logodds, 2)}.
          </div>
        </>
      )}
    </div>
  )
}

function GlobalBars({ items }: { items: ImportanceItem[] }) {
  const top = items[0]?.gain || 1
  return (
    <div className="drivers">
      {items.map((it) => (
        <div className="driver" key={it.feature}>
          <span>{it.label}</span>
          <div className="bar">
            <i className="pos" style={{ width: `${Math.min(50, (50 * it.gain) / top)}%` }} />
          </div>
          <span className="mono small muted">{fmt(it.gain, 0)}</span>
        </div>
      ))}
    </div>
  )
}
