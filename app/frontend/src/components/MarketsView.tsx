import type { Markets } from '../api'
import { fmt, pct, brier } from '../util'
import { Skeleton, Empty, ErrorBox } from './States'

type Props = { mk: Markets | undefined; loading: boolean; error?: string; onOpen: (dyad: string, date: string) => void }

export default function MarketsView({ mk, loading, error, onOpen }: Props) {
  if (error) return <ErrorBox title="Couldn’t load markets" detail={error} />
  if (!mk && loading)
    return (
      <div className="card">
        <Skeleton lines={6} height={24} />
      </div>
    )
  if (!mk) return null
  if (!mk.available)
    return (
      <div className="card">
        <h2>Model vs prediction markets</h2>
        <Empty>
          Market comparison artifacts are not built yet.
          <div className="small" style={{ marginTop: 4 }}>
            {mk.reason}
          </div>
        </Empty>
      </div>
    )
  const s = mk.summary
  const best = Object.entries(s.brier).sort((a, b) => a[1] - b[1])[0]?.[0]
  return (
    <div className="stack">
      <div className="card">
        <h2>
          Model vs prediction markets
          <span className="right small">
            {s.n_markets} resolved markets · {s.n_dyads} country pairs · both scored {s.snapshot_days_before} days before resolution
          </span>
        </h2>
        <div className="score-grid">
          {Object.entries(s.brier).map(([k, v]) => (
            <div className="score" key={k} style={k === best ? { borderColor: 'var(--good)' } : undefined}>
              <div className="k">Brier · {k.replace('_', ' ')}</div>
              <div className="v">{fmt(v, 4)}</div>
              {s.logloss[k] !== undefined && <div className="small muted mono">log loss {fmt(s.logloss[k], 3)}</div>}
            </div>
          ))}
          {Object.entries(s.loo).map(([k, v]) => (
            <div className="score" key={k}>
              <div className="k">LOO stack · {k.replace(/_/g, ' ')}</div>
              <div className="v">{fmt(v, 4)}</div>
              <div className="small muted">leave-one-out logistic</div>
            </div>
          ))}
        </div>
        <div className="callout quiet" style={{ marginTop: 12 }}>
          <strong>Read this carefully.</strong> Lower Brier is better. The model forecasts <em>ICB-coded crisis onset</em>, not the
          market’s exact question, so this is a test of whether GDELT-derived risk carries information about market outcomes — not a
          claim that either side “beats” the other. With n = {s.n_markets} and outcome base rate {pct(s.base_rate, 0)}, differences of
          a few thousandths are noise.
          <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
            {s.caveats.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </div>
        {Object.keys(s.by_source).length > 1 && (
          <div className="row small muted" style={{ marginTop: 8 }}>
            {Object.entries(s.by_source).map(([src, v]) => (
              <span key={src} className="pill">
                {src}: n={v.n} · market {fmt(v.brier_market, 3)} · model {fmt(v.brier_model, 3)}
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <h2>Resolved markets</h2>
        <div style={{ overflowX: 'auto' }}>
          <table className="tbl">
            <thead>
              <tr>
                <th>Market</th>
                <th>Pair</th>
                <th>Snapshot</th>
                <th>Resolved</th>
                <th className="num">Market</th>
                <th className="num">Model → question</th>
                <th className="num">GDELT pct</th>
                <th>Outcome</th>
                <th className="num">Brier mkt</th>
                <th className="num">Brier model</th>
              </tr>
            </thead>
            <tbody>
              {mk.rows.map((r) => (
                <tr key={r.source + r.market_id}>
                  <td style={{ maxWidth: 380 }}>
                    <a href={r.url} target="_blank" rel="noreferrer">
                      {r.question}
                    </a>
                    {r.direction === -1 && <span className="tag">inverted: YES = escalation</span>}
                    <div className="small muted">
                      {r.source} · ${Math.round(r.volume).toLocaleString()} volume
                    </div>
                  </td>
                  <td>
                    <button className="ghost small" onClick={() => onOpen(r.dyad, r.snapshot_date)}>
                      {r.dyad_label}
                    </button>
                  </td>
                  <td className="mono small">{r.snapshot_date}</td>
                  <td className="mono small">{r.resolution_time}</td>
                  <td className="num">{pct(r.p_market, 0)}</td>
                  <td className="num" title={`raw ICB-onset probability ${pct(r.p_model, 2)}`}>
                    {pct(r.p_stack_model, 0)}
                  </td>
                  <td className="num">{(100 * r.model_pct).toFixed(0)}</td>
                  <td>{r.outcome ? <span style={{ color: 'var(--accent)' }}>YES</span> : <span className="muted">no</span>}</td>
                  <td className="num">{fmt(brier(r.p_market, r.outcome), 3)}</td>
                  <td className="num">{fmt(brier(r.p_stack_model, r.outcome), 3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
