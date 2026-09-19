import { useState } from 'react'
import type { Analog, Analogs, OutcomeDist } from '../api'
import { fmt, pct } from '../util'
import { Skeleton, Empty, ErrorBox } from './States'

type Props = { an: Analogs | undefined; loading: boolean; error?: string }

const OUTCOME_LABEL: Record<string, string> = {
  sevviosy_label: 'Violence severity',
  outesr_label: 'Outcome (ICB)',
  crismg_label: 'Crisis management',
  viol_label: 'Violence',
}

const SCHEMA_LABEL: Record<string, string> = {
  geog: 'region',
  protrac: 'protracted conflict',
  pcid: 'conflict id',
  nuclear_max: 'nuclear',
  powsta_max: 'power status',
  regime_pair: 'regimes',
  gravcr: 'gravity',
  gpinv: 'great-power involvement',
}

export default function AnalogsPanel({ an, loading, error }: Props) {
  const [view, setView] = useState<'side' | 'hybrid'>('side')
  return (
    <div className="card">
      <h2>
        Historical analogs
        {an && (
          <span className={`pill ${an.source === 'elasticsearch' ? 'ok' : 'warn'}`} style={{ marginLeft: 4 }}>
            <span className="dot" /> {an.source === 'elasticsearch' ? 'Elasticsearch' : 'local FAISS fallback'}
          </span>
        )}
        <span className="right">
          <span className="analog-tabs" style={{ margin: 0 }}>
            <button className={`chip ${view === 'side' ? 'active' : ''}`} onClick={() => setView('side')}>
              vector vs schema
            </button>
            <button className={`chip ${view === 'hybrid' ? 'active' : ''}`} onClick={() => setView('hybrid')}>
              hybrid (RRF)
            </button>
          </span>
        </span>
      </h2>
      {error ? (
        <ErrorBox title="Retrieval failed" detail={error} />
      ) : !an && loading ? (
        <Skeleton lines={5} height={40} />
      ) : !an ? (
        <Empty>Select a country pair.</Empty>
      ) : (
        <div style={{ opacity: loading ? 0.7 : 1, transition: 'opacity 0.2s' }}>
          <div className="small muted" style={{ marginBottom: 10 }}>
            Only ICB crises that <em>ended before {an.t}</em> are eligible. Vector = 13-week GDELT run-up shape (kNN, date filter
            inside the kNN clause). Schema = structural pre-onset attributes
            {Object.keys(an.query.schema).length > 0 && (
              <>
                {' '}
                (
                {Object.entries(an.query.schema)
                  .map(([k, v]) => `${SCHEMA_LABEL[k] ?? k}=${String(v)}`)
                  .join(', ')}
                )
              </>
            )}
            . Outcome fields are display-only, never used to retrieve.
          </div>
          {view === 'side' ? (
            <div className="analog-grid">
              <Column
                title="Similar run-up (vector)"
                items={an.vector}
                dist={an.vector_outcomes}
                empty={
                  an.query.vector_available
                    ? 'No historical run-up matches.'
                    : 'No GDELT activity in the trailing 13 weeks — no run-up vector to search with.'
                }
              />
              <Column title="Similar structure (schema)" items={an.schema} dist={an.schema_outcomes} empty="No schema matches." />
            </div>
          ) : (
            <Column
              title="Hybrid — reciprocal-rank fusion of both lists"
              items={an.hybrid}
              dist={an.hybrid_outcomes}
              empty="No hybrid matches."
            />
          )}
        </div>
      )}
    </div>
  )
}

function Column({ title, items, dist, empty }: { title: string; items: Analog[]; dist: OutcomeDist; empty: string }) {
  return (
    <div className="analog-col">
      <h3>{title}</h3>
      {items.length === 0 ? (
        <Empty>{empty}</Empty>
      ) : (
        <>
          {items.map((a) => (
            <AnalogCard key={a.case_id} a={a} />
          ))}
          <Outcomes dist={dist} n={items.length} />
        </>
      )}
    </div>
  )
}

function AnalogCard({ a }: { a: Analog }) {
  const viol = a.ex_post.viol_label as string | undefined
  const sev = a.ex_post.sevviosy_label as string | undefined
  const out = a.ex_post.outesr_label as string | undefined
  const grav = a.at_onset.gravcr_label as string | undefined
  return (
    <div className="analog">
      <div className="name">{a.name}</div>
      <div className="meta">
        {a.onset_date} → {a.end_date} · {a.actor_names.join(', ')} · {a.source} score {fmt(a.score, 3)}
      </div>
      <div className="tags">
        {grav && <span>gravity: {grav}</span>}
        {viol && <span className="viol">violence: {viol}</span>}
        {sev && <span className="viol">severity: {sev}</span>}
        {out && <span>outcome: {out}</span>}
        {a.runup_summary?.peak_log_events !== undefined && (
          <span>
            peak {Math.round(Math.expm1(a.runup_summary.peak_log_events)).toLocaleString()} events/wk · mean Goldstein{' '}
            {fmt(a.runup_summary.last_goldstein, 1)}
          </span>
        )}
      </div>
    </div>
  )
}

function Outcomes({ dist, n }: { dist: OutcomeDist; n: number }) {
  const keys = Object.keys(dist)
  if (!keys.length) return null
  return (
    <div style={{ marginTop: 8 }}>
      <div className="small muted">How these {n} analogs turned out (ex-post, display only)</div>
      {keys.slice(0, 2).map((k) => (
        <div className="dist" key={k}>
          <div className="small" style={{ marginTop: 4, fontWeight: 600 }}>
            {OUTCOME_LABEL[k] ?? k}
          </div>
          {Object.entries(dist[k]).map(([label, share]) => (
            <div className="dist-row" key={label}>
              <span className="muted">{label}</span>
              <div className="bar">
                <i style={{ width: `${100 * share}%` }} />
              </div>
              <span className="mono">{pct(share, 0)}</span>
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}
