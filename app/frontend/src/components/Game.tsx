import { useEffect, useState } from 'react'
import { api, type Episode } from '../api'
import { brier, fmt, pct } from '../util'
import { Skeleton, ErrorBox, Empty } from './States'

type Tally = { you: number; model: number; market: number; n: number; nMarket: number; wins: number; streak: number; best: number }

const zero: Tally = { you: 0, model: 0, market: 0, n: 0, nMarket: 0, wins: 0, streak: 0, best: 0 }

type Props = { onOpen: (dyad: string, date: string) => void; hasMarkets: boolean }

export default function Game({ onOpen, hasMarkets }: Props) {
  const [eps, setEps] = useState<Episode[] | null>(null)
  const [err, setErr] = useState<string | undefined>()
  const [i, setI] = useState(0)
  const [guess, setGuess] = useState(20)
  const [revealed, setRevealed] = useState(false)
  const [tally, setTally] = useState<Tally>(zero)
  const [seed, setSeed] = useState(() => Math.floor(Math.random() * 1e6))

  useEffect(() => {
    let alive = true
    api.episodes(8, seed).then(
      (e) => alive && setEps(e),
      (e: Error) => alive && setErr(e.message),
    )
    return () => {
      alive = false
    }
  }, [seed])

  if (err) return <ErrorBox title="Couldn’t load game episodes" detail={err} />
  if (!eps)
    return (
      <div className="card">
        <Skeleton lines={5} height={28} />
      </div>
    )
  if (eps.length === 0) return <Empty>No episodes available.</Empty>

  const ep = eps[i]
  const p = guess / 100
  const done = i >= eps.length - 1 && revealed

  const reveal = () => {
    if (revealed) return
    setRevealed(true)
    const you = brier(p, ep.outcome)
    const model = brier(ep.p_model, ep.outcome)
    const market = ep.p_market === null ? null : brier(ep.p_market, ep.outcome)
    const beatModel = you < model
    setTally((t) => ({
      you: t.you + you,
      model: t.model + model,
      market: t.market + (market ?? 0),
      n: t.n + 1,
      nMarket: t.nMarket + (market === null ? 0 : 1),
      wins: t.wins + (beatModel ? 1 : 0),
      streak: beatModel ? t.streak + 1 : 0,
      best: Math.max(t.best, beatModel ? t.streak + 1 : 0),
    }))
  }
  const next = () => {
    if (i < eps.length - 1) {
      setI(i + 1)
      setRevealed(false)
      setGuess(20)
    }
  }
  const restart = () => {
    setEps(null)
    setErr(undefined)
    setI(0)
    setRevealed(false)
    setTally(zero)
    setSeed(Math.floor(Math.random() * 1e6))
  }

  const scores = [
    { who: 'You', v: tally.you / Math.max(1, tally.n), n: tally.n },
    { who: 'Model', v: tally.model / Math.max(1, tally.n), n: tally.n },
    ...(tally.nMarket ? [{ who: 'Market', v: tally.market / tally.nMarket, n: tally.nMarket }] : []),
  ]
  const lead = tally.n ? scores.slice(0, 2).sort((a, b) => a.v - b.v)[0].who : null

  return (
    <div className="game">
      <div className="card">
        <h2>
          You vs Model vs Market
          <span className="right small">
            episode {i + 1} / {eps.length} · {ep.kind === 'market' ? 'prediction-market question' : 'ICB history'}
          </span>
        </h2>
        <div className="small muted">
          Situation as of <span className="mono">{ep.date}</span> · {ep.dyad_label}{' '}
          <button className="ghost small" style={{ padding: '2px 8px' }} onClick={() => onOpen(ep.dyad, ep.date)}>
            open in explorer ↗
          </button>
        </div>
        <div className="question">{ep.question}</div>

        <div className="guess">
          <input type="range" min={1} max={99} value={guess} disabled={revealed} onChange={(e) => setGuess(Number(e.target.value))} />
          <div className="val">{guess}%</div>
        </div>
        <div className="small muted" style={{ marginTop: 4 }}>
          Slide to your probability. Everyone is scored with the Brier score (squared error; lower is better).
        </div>

        {!revealed ? (
          <div className="row" style={{ marginTop: 14 }}>
            <button className="primary" onClick={reveal}>
              Lock in {guess}%
            </button>
          </div>
        ) : (
          <>
            <div className={`outcome ${ep.outcome ? 'yes' : 'no'}`}>
              {ep.outcome ? 'It happened.' : 'It did not happen.'}
              {ep.kind === 'icb' && ep.crisis && (
                <span className="muted" style={{ fontWeight: 400 }}>
                  {' '}
                  — ICB: {ep.crisis}
                </span>
              )}
              {ep.kind === 'market' && ep.url && (
                <span className="muted" style={{ fontWeight: 400 }}>
                  {' '}
                  —{' '}
                  <a href={ep.url} target="_blank" rel="noreferrer">
                    market resolved {ep.resolution_time}
                  </a>
                </span>
              )}
            </div>
            <div className="reveal">
              <Player who="You" p={p} y={ep.outcome} win={brier(p, ep.outcome) <= brier(ep.p_model, ep.outcome)} />
              <Player
                who={ep.model_kind === 'stacked_percentile' ? 'Model (re-fit on other markets)' : 'Model'}
                title={
                  ep.model_kind === 'stacked_percentile'
                    ? 'Not the raw 30-day crisis-onset forecast: the dyad\'s GDELT risk percentile that week, mapped to this question type by a logistic fit on the other markets (this one held out).'
                    : 'The calibrated 30-day forecast the model made at the time, from a walk-forward fold that never saw this week.'
                }
                p={ep.p_model}
                y={ep.outcome}
                win={brier(ep.p_model, ep.outcome) < brier(p, ep.outcome)}
                note={
                  ep.model_kind === 'calibrated_oos'
                    ? 'walk-forward out-of-sample'
                    : `GDELT risk percentile ${((ep.model_pct ?? 0) * 100).toFixed(0)} mapped to this question type (leave-one-out)`
                }
              />
              {ep.p_market !== null ? (
                <Player who="Market" p={ep.p_market} y={ep.outcome} win={false} note="price 30 days before resolution" />
              ) : (
                <div className="player" style={{ opacity: 0.6 }}>
                  <div className="who">Market</div>
                  <div className="small muted" style={{ marginTop: 6 }}>
                    No prediction market existed for this historical episode.
                  </div>
                </div>
              )}
            </div>
            <div className="row" style={{ marginTop: 14 }}>
              {!done ? (
                <button className="primary" onClick={next}>
                  Next episode →
                </button>
              ) : (
                <button className="primary" onClick={restart}>
                  Play again with new episodes
                </button>
              )}
            </div>
          </>
        )}
      </div>

      <div className="stack">
        <div className="card">
          <h2>Scoreboard</h2>
          {tally.n === 0 ? (
            <Empty>Lock in a forecast to start scoring.</Empty>
          ) : (
            <div className="scoreboard">
              <div className="line small muted" style={{ background: 'none' }}>
                <span>player</span>
                <span>mean Brier</span>
                <span>n</span>
              </div>
              {scores.map((s) => (
                <div key={s.who} className={`line ${s.who === lead ? 'lead' : ''}`}>
                  <span>{s.who}</span>
                  <span>{fmt(s.v, 3)}</span>
                  <span className="muted">{s.n}</span>
                </div>
              ))}
              <div className="streak">
                beat the model {tally.wins}/{tally.n} · streak {tally.streak} · best {tally.best}
              </div>
            </div>
          )}
        </div>
        <div className="card">
          <h2>How episodes are chosen</h2>
          <div className="small muted">
            ICB episodes are drawn from walk-forward out-of-sample weeks (1997+): half are weeks 30 days before a coded crisis onset,
            half are high-risk weeks where nothing was coded. The model's number is the forecast it made <em>at the time</em>, never
            refit on the answer.
            {hasMarkets
              ? ' Market episodes use a Polymarket/Kalshi price 30 days before resolution; the model\'s number there is its GDELT risk percentile for that week re-fit to the question type on the other markets (leave-one-out), not the raw crisis-onset forecast.'
              : ' Market episodes appear once market artifacts are built.'}
          </div>
        </div>
      </div>
    </div>
  )
}

function Player({ who, p, y, win, note, title }: { who: string; p: number; y: number; win: boolean; note?: string; title?: string }) {
  return (
    <div className={`player ${win ? 'win' : ''}`} title={title}>
      <div className="who">{who}</div>
      <div className="p">{pct(p, p < 0.01 ? 2 : 1)}</div>
      <div className="brier">Brier {fmt(brier(p, y), 3)}</div>
      {note && <div className="small muted">{note}</div>}
    </div>
  )
}
