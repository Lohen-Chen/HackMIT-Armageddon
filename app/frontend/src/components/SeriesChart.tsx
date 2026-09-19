import {
  ComposedChart,
  Area,
  Line,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  ReferenceArea,
  ResponsiveContainer,
} from 'recharts'
import type { Series } from '../api'
import { pct } from '../util'
import { Skeleton, Empty, ErrorBox } from './States'

type Props = { series: Series | undefined; loading: boolean; error?: string; date: string; onScrub: (t: string) => void }

export default function SeriesChart({ series, loading, error, date, onScrub }: Props) {
  const data = (series?.points ?? []).map((p) => ({
    ...p,
    band: [p.p_lo, p.p_hi] as [number, number],
    onset: p.y === 1 ? 1 : 0,
  }))
  const maxP = Math.max(0.01, ...data.map((d) => d.p_hi))
  return (
    <div className="card">
      <h2>
        Replay
        <span className="right small">calibrated probability · band · GDELT events</span>
      </h2>
      {error ? (
        <ErrorBox title="Couldn’t load series" detail={error} />
      ) : !series && loading ? (
        <Skeleton lines={1} height={200} />
      ) : !series || data.length === 0 ? (
        <Empty>No forecasts in this window — the pair was below the activity threshold.</Empty>
      ) : (
        <div style={{ opacity: loading ? 0.7 : 1, transition: 'opacity 0.2s' }}>
          <ResponsiveContainer width="100%" height={230}>
            <ComposedChart
              data={data}
              margin={{ top: 8, right: 12, left: 0, bottom: 0 }}
              onClick={(e) => {
                const l = (e as { activeLabel?: string | number } | null)?.activeLabel
                if (typeof l === 'string') onScrub(l)
              }}
            >
              <XAxis dataKey="t" tick={{ fill: '#8b97ad', fontSize: 10 }} tickLine={false} minTickGap={40} />
              <YAxis
                yAxisId="p"
                domain={[0, Math.min(1, maxP * 1.15)]}
                tickFormatter={(v: number) => pct(v, v < 0.01 ? 1 : 0)}
                tick={{ fill: '#8b97ad', fontSize: 10 }}
                width={46}
                tickLine={false}
                axisLine={false}
              />
              <YAxis yAxisId="ev" orientation="right" hide />
              <Tooltip
                contentStyle={{ background: '#151c2b', border: '1px solid #263248', borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: '#e6ebf5' }}
                formatter={(v: unknown, name: unknown) => {
                  if (name === 'band' && Array.isArray(v)) return [`${pct(v[0], 2)} – ${pct(v[1], 2)}`, 'band']
                  if (name === 'p_cal') return [pct(v as number, 2), 'P(onset ≤30d)']
                  if (name === 'p_oos') return [pct(v as number, 2), 'walk-forward OOS']
                  if (name === 'n_events') return [(v as number).toLocaleString(), 'events / wk']
                  return [String(v), String(name)]
                }}
              />
              {series.onsets.map((o) => (
                <ReferenceArea
                  key={o.crisno}
                  yAxisId="p"
                  x1={clampX(o.onset_date, data)}
                  x2={clampX(o.end_date, data)}
                  fill="#ff5a3c"
                  fillOpacity={0.08}
                  stroke="#ff5a3c"
                  strokeOpacity={0.5}
                  label={{ value: o.name, position: 'insideTopLeft', fill: '#ffb3a6', fontSize: 10 }}
                />
              ))}
              <Bar yAxisId="ev" dataKey="n_events" fill="#26324a" radius={2} isAnimationActive={false} />
              <Area
                yAxisId="p"
                dataKey="band"
                stroke="none"
                fill="#ff5a3c"
                fillOpacity={0.18}
                isAnimationActive={false}
                activeDot={false}
              />
              <Line yAxisId="p" dataKey="p_cal" stroke="#ff5a3c" strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line
                yAxisId="p"
                dataKey="p_oos"
                stroke="#ffb03c"
                strokeWidth={1}
                strokeDasharray="3 3"
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
              />
              <ReferenceLine yAxisId="p" x={nearest(date, data)} stroke="#ffd166" strokeDasharray="4 2" />
            </ComposedChart>
          </ResponsiveContainer>
          <div className="small muted" style={{ marginTop: 6 }}>
            Solid: final model (calibrated). Dashed amber: walk-forward out-of-sample forecast where available. Shaded: ICB crisis
            span. Click the chart to jump the replay cursor.
          </div>
        </div>
      )}
    </div>
  )
}

function nearest(date: string, data: { t: string }[]): string | undefined {
  if (!data.length) return undefined
  let best = data[0].t
  for (const d of data) if (d.t <= date) best = d.t
  return best
}

function clampX(date: string, data: { t: string }[]): string | undefined {
  if (!data.length) return undefined
  if (date < data[0].t) return data[0].t
  if (date > data[data.length - 1].t) return data[data.length - 1].t
  return nearest(date, data)
}
