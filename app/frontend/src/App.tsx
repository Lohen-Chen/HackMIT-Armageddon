import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, type Hero, type Meta } from './api'
import { addDays, toWeek, useAsync } from './util'
import Controls from './components/Controls'
import WorldMap from './components/WorldMap'
import TopDyads from './components/TopDyads'
import ForecastCard from './components/ForecastCard'
import DriversPanel from './components/DriversPanel'
import SeriesChart from './components/SeriesChart'
import AnalogsPanel from './components/AnalogsPanel'
import MarketsView from './components/MarketsView'
import Game from './components/Game'
import { ErrorBox } from './components/States'

type Tab = 'explore' | 'markets' | 'game'

function readHash() {
  const h = new URLSearchParams(window.location.hash.replace(/^#/, ''))
  return {
    tab: (h.get('tab') as Tab) || 'explore',
    dyad: h.get('dyad') || '',
    date: h.get('date') || '',
    label: h.get('label') || 'y_icb',
  }
}

export default function App() {
  const init = useMemo(readHash, [])
  const [tab, setTab] = useState<Tab>(init.tab)
  const [dyad, setDyad] = useState(init.dyad)
  const [date, setDate] = useState(init.date)
  const [label, setLabel] = useState(init.label)
  const [win, setWin] = useState<{ start: string; end: string } | null>(null)
  const [hero, setHero] = useState<string | null>(null)
  const [meta, setMeta] = useState<Meta | null>(null)
  const [metaErr, setMetaErr] = useState<string | null>(null)

  useEffect(() => {
    api.meta().then(
      (m) => {
        setMeta(m)
        const h = m.heroes[0]
        if (!dyad && h) {
          applyHero(h)
        } else if (!date) {
          setDate(toWeek(m.t_max))
          setWin({ start: addDays(m.t_max, -365), end: m.t_max })
        } else if (!win) {
          setWin({ start: addDays(date, -270), end: addDays(date, 95) > m.t_max ? m.t_max : addDays(date, 95) })
        }
      },
      (e: Error) => setMetaErr(e.message),
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const h = new URLSearchParams({ tab, dyad, date, label })
    window.history.replaceState(null, '', '#' + h.toString())
  }, [tab, dyad, date, label])

  useEffect(() => {
    const onHash = () => {
      const h = readHash()
      setTab(h.tab)
      if (h.dyad) setDyad(h.dyad)
      if (h.date) {
        setDate(toWeek(h.date))
        setWin((w) => (w && h.date >= w.start && h.date <= w.end ? w : { start: addDays(h.date, -270), end: addDays(h.date, 95) }))
      }
      setLabel(h.label)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const applyHero = useCallback((h: Hero) => {
    setDyad(h.dyad)
    setWin({ start: h.start, end: h.end })
    // start the cursor ~5 weeks before the window's midpoint so the run-up is visible
    const mid = addDays(h.start, Math.floor(((new Date(h.end).getTime() - new Date(h.start).getTime()) / 86400000) * 0.4))
    setDate(toWeek(mid))
    setHero(h.dyad + h.start)
    setTab('explore')
  }, [])

  const openIn = useCallback((d: string, t: string) => {
    setDyad(d)
    setDate(toWeek(t))
    setWin({ start: addDays(t, -270), end: addDays(t, 95) })
    setHero(null)
    setTab('explore')
  }, [])

  const ready = !!meta && !!dyad && !!date && !!win
  const mapQ = useAsync(ready ? () => api.map(date, label, 30) : null, [ready, date, label], 120)
  const fcQ = useAsync(ready ? () => api.forecast(dyad, date, label) : null, [ready, dyad, date, label], 120)
  const serQ = useAsync(ready ? () => api.series(dyad, win!.start, win!.end, label) : null, [ready, dyad, win, label])
  const anQ = useAsync(ready ? () => api.analogs(dyad, date, 5) : null, [ready, dyad, date], 250)
  const mkQ = useAsync(meta && tab === 'markets' ? () => api.markets() : null, [meta, tab])

  if (metaErr)
    return (
      <div className="splash">
        <div className="logo">Signal in the Noise</div>
        <ErrorBox title="The forecast service is not reachable" detail={`${metaErr} — start the API with make serve.`} />
      </div>
    )
  if (!meta || !ready)
    return (
      <div className="splash">
        <div className="logo">Signal in the Noise</div>
        <div className="row">
          <span className="pulse" /> loading 47 years of GDELT × ICB…
        </div>
      </div>
    )

  const esOk = meta.retrieval_mode === 'elasticsearch'
  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <h1>Signal in the Noise</h1>
          <span>GDELT → calibrated 30-day escalation risk, grounded in ICB history</span>
        </div>
        <nav className="tabs">
          {(['explore', 'markets', 'game'] as Tab[]).map((t) => (
            <button key={t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>
              {t === 'explore' ? 'Explore & replay' : t === 'markets' ? 'Model vs markets' : 'Play the game'}
            </button>
          ))}
        </nav>
        <div className="spacer" />
        <span className={`pill ${esOk ? 'ok' : 'warn'}`} title={meta.notes.join('\n')}>
          <span className="dot" /> retrieval: {esOk ? 'Elasticsearch' : 'local FAISS fallback'}
        </span>
        {meta.notes.some((n) => n.includes('demo pack')) && (
          <span className="pill warn" title={meta.notes.join('\n')}>
            <span className="dot" /> demo pack
          </span>
        )}
        <span className="pill" title="walk-forward out-of-sample, pooled">
          OOS AUC {meta.metrics[label]?.model_raw?.auc.toFixed(2) ?? '—'} · Brier{' '}
          {meta.metrics[label]?.model_cal?.brier.toExponential(2) ?? '—'} (base {meta.metrics[label]?.base_rate?.brier.toExponential(2) ?? '—'})
        </span>
      </header>

      <main className="main">
        {tab === 'explore' && (
          <>
            <Controls
              meta={meta}
              dyad={dyad}
              date={date}
              window={win!}
              label={label}
              onsets={serQ.data?.onsets ?? []}
              onDyad={(d) => {
                setDyad(d)
                setHero(null)
              }}
              onDate={setDate}
              onWindow={setWin}
              onLabel={setLabel}
              onHero={applyHero}
              activeHero={hero}
            />
            <div className="grid-explore">
              <div className="stack">
                <div className="card">
                  <h2>
                    Risk map · week ending {mapQ.data?.t ?? date}
                    <span className="right small">{mapQ.data ? `${mapQ.data.n_dyads} active pairs` : ''}</span>
                  </h2>
                  {mapQ.status === 'error' ? (
                    <ErrorBox title="Couldn’t load map" detail={mapQ.error} />
                  ) : (
                    <>
                      <WorldMap
                        snapshot={mapQ.data}
                        loading={mapQ.status === 'loading'}
                        countries={meta.countries}
                        selected={dyad}
                        onSelect={(d) => {
                          setDyad(d)
                          setHero(null)
                        }}
                      />
                      <TopDyads
                        snapshot={mapQ.data}
                        loading={mapQ.status === 'loading'}
                        selected={dyad}
                        onSelect={(d) => {
                          setDyad(d)
                          setHero(null)
                        }}
                      />
                    </>
                  )}
                </div>
                <SeriesChart series={serQ.data} loading={serQ.status === 'loading'} error={serQ.error} date={date} onScrub={setDate} />
              </div>
              <div className="stack">
                <ForecastCard fc={fcQ.data} loading={fcQ.status === 'loading'} error={fcQ.error} meta={meta} label={label} />
                <DriversPanel fc={fcQ.data} loading={fcQ.status === 'loading'} />
                <AnalogsPanel an={anQ.data} loading={anQ.status === 'loading'} error={anQ.error} />
              </div>
            </div>
          </>
        )}
        {tab === 'markets' && <MarketsView mk={mkQ.data} loading={mkQ.status === 'loading'} error={mkQ.error} onOpen={openIn} />}
        {tab === 'game' && <Game onOpen={openIn} hasMarkets={meta.has_markets} />}
      </main>
      <div className="footer-note">
        Data: GDELT 1.0 events (1979–present, noisy machine-coded news) · ICB v16 crisis dataset (human-coded, complete through{' '}
        {meta.sample_boundaries.icb_complete_end}) · Polymarket & Kalshi resolved markets. Final model trees trained through{' '}
        {meta.sample_boundaries.trees_train_end}; later dates are out-of-sample for the trees. Retrieval never returns a crisis that
        had not ended by the forecast date.
      </div>
    </div>
  )
}
