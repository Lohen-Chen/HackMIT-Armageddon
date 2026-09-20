import type { Forecast, Meta } from '../api'
import { pct, fmt } from '../util'
import { Skeleton, ErrorBox, Empty } from './States'

type Props = { fc: Forecast | undefined; loading: boolean; error?: string; meta: Meta; label: string }

const LABEL_TEXT: Record<string, string> = {
  y_icb: 'ICB-coded international crisis begins within 30 days',
  y_thresh: 'material-conflict event surge (≥3× trailing rate) within 30 days',
}

export default function ForecastCard({ fc, loading, error, meta, label }: Props) {
  return (
    <div className="card">
      <h2>
        Forecast
        <span className="right small">{LABEL_TEXT[label] ?? label}</span>
      </h2>
      {error ? (
        <ErrorBox title="Couldn’t load forecast" detail={error} />
      ) : !fc && loading ? (
        <Skeleton lines={4} height={22} />
      ) : !fc ? (
        <Empty>Select a country pair.</Empty>
      ) : !fc.available ? (
        <Empty>
          <div style={{ fontWeight: 600, color: 'var(--text)' }}>No forecast for {fc.dyad.replace('_', '–')} this week</div>
          <div className="small" style={{ marginTop: 4 }}>
            {fc.reason}
          </div>
        </Empty>
      ) : (
        <div style={{ opacity: loading ? 0.6 : 1, transition: 'opacity 0.2s' }}>
          <div className="bigp">
            <div className="num" style={{ color: fc.p_cal >= 0.05 ? 'var(--accent)' : 'var(--text)' }}>
              {pct(fc.p_cal, fc.p_cal < 0.01 ? 2 : 1)}
            </div>
            <div className="band">
              band {pct(fc.p_lo, 2)} – {pct(fc.p_hi, 2)}
              <div className="small muted">calibrated · raw score {fmt(fc.p_raw, 3)}</div>
            </div>
          </div>
          <div className="kv">
            <div>
              <div className="k">rank this week</div>
              <div className="v">
                #{fc.rank} / {fc.n_dyads}
              </div>
            </div>
            <div>
              <div className="k">week ending</div>
              <div className="v">{fc.t}</div>
            </div>
            <div>
              <div className="k">status</div>
              <div className="v">{fc.in_crisis ? 'in ICB crisis' : 'no active crisis'}</div>
            </div>
            <div>
              <div className="k">realised label</div>
              <div className="v">{fc.y === null ? 'not yet coded' : fc.y === 1 ? 'onset ✓' : 'no onset'}</div>
            </div>
          </div>
          <div style={{ marginTop: 10 }}>
            <span className={`flag ${fc.flags.trees_out_of_sample ? 'on' : 'off'}`}>
              trees {fc.flags.trees_out_of_sample ? 'out-of-sample' : 'in-sample'}
            </span>
            <span className={`flag ${fc.flags.calibration_out_of_sample ? 'on' : 'off'}`}>
              calibration {fc.flags.calibration_out_of_sample ? 'out-of-sample' : 'in-sample'}
            </span>
            <span className={`flag ${fc.flags.icb_label_available ? 'on' : ''}`}>
              ICB labels {fc.flags.icb_label_available ? 'available' : `end ${meta.sample_boundaries.icb_complete_end}`}
            </span>
          </div>
          {fc.current_crisis && (
            <div className="callout cool">
              Ongoing ICB crisis: <strong>{fc.current_crisis.name}</strong> ({fc.current_crisis.onset_date} → {fc.current_crisis.end_date}
              ). Onset labels are 0 while a crisis is already under way.
            </div>
          )}
          {fc.onset_within_30d && typeof fc.onset_within_30d === 'object' && (
            <div className="callout">
              What actually happened: <strong>{fc.onset_within_30d.name}</strong> began on {fc.onset_within_30d.onset_date} — within the
              30-day horizon.
            </div>
          )}
          {fc.onset_within_30d === false && !fc.current_crisis && (
            <div className="callout quiet">What actually happened: no ICB-coded crisis began in the following 30 days.</div>
          )}
          {fc.onset_within_30d === null && (
            <div className="callout quiet">
              Outcome not coded: ICB v16 coverage ends {meta.sample_boundaries.icb_complete_end}, so part or all of this 30-day
              horizon has no human-coded label.
            </div>
          )}
        </div>
      )}
    </div>
  )
}
