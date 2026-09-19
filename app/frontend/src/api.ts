// Typed client for the FastAPI backend. The browser never talks to Elasticsearch directly.

export type Country = {
  iso3: string
  name: string
  iso_num: string
  region: string | null
  subregion: string | null
  lat: number | null
  lon: number | null
}

export type Hero = {
  dyad: string
  label: string
  start: string
  end: string
  crisis: string
  macro_region: string | null
}

export type ImportanceItem = { feature: string; label: string; gain: number }

export type Meta = {
  t_min: string
  t_max: string
  labels: string[]
  heroes: Hero[]
  retrieval_mode: 'elasticsearch' | 'local'
  notes: string[]
  dyads: { dyad: string; label: string }[]
  countries: Record<string, Country>
  metrics: Record<string, Record<string, { n: number; pos: number; brier: number; logloss: number; auc: number; ap: number }>>
  importance: Record<string, ImportanceItem[]>
  sample_boundaries: { trees_train_end: string; icb_complete_end: string }
  has_markets: boolean
}

export type MapRow = {
  dyad: string
  label: string
  p_raw: number
  p_cal: number
  p_lo: number
  p_hi: number
  pct: number
  in_crisis: boolean
}

export type MapSnapshot = {
  t: string
  n_dyads: number
  top: MapRow[]
  countries: Record<string, { p_raw: number; p_cal: number; dyad: string; pct: number }>
}

export type SeriesPoint = {
  t: string
  p_raw: number
  p_cal: number
  p_lo: number
  p_hi: number
  in_crisis: boolean
  y: number | null
  p_oos: number | null
  n_events: number
  q4: number
  goldstein_mean: number | null
}

export type Onset = {
  crisno: number
  name: string
  onset_date: string
  end_date: string
  viol_label: string | null
}

export type Series = {
  dyad: string
  label?: string
  points: SeriesPoint[]
  onsets: Onset[]
  error?: string
  sample_boundaries?: { trees_train_end: string; icb_complete_end: string }
}

export type Driver = { feature: string; label: string; contribution: number; value: number | null }

export type Drivers =
  | { mode: 'global'; items: ImportanceItem[] }
  | {
      mode: 'local'
      bias_logodds: number
      items: Driver[]
      recent: { n_events_4w: number; q4_4w: number; goldstein_mean_4w: number | null }
    }

export type Flags = {
  trees_out_of_sample: boolean
  calibration_out_of_sample: boolean
  icb_label_available: boolean
}

export type Forecast =
  | { dyad: string; t: string; available: false; reason: string }
  | {
      dyad: string
      label: string
      t: string
      available: true
      p_raw: number
      p_cal: number
      p_lo: number
      p_hi: number
      in_crisis: boolean
      y: number | null
      rank: number
      n_dyads: number
      flags: Flags
      drivers: Drivers
      current_crisis: { crisno: number; name: string; onset_date: string; end_date: string } | null
      onset_within_30d: null | false | { crisno: number; name: string; onset_date: string }
    }

export type Analog = {
  case_id: string
  crisno: number
  name: string
  region: string | null
  macro_region: string | null
  actors: string[]
  actor_names: string[]
  dyad: string | null
  onset_date: string
  end_date: string
  score: number
  source: string
  pre_onset: Record<string, unknown>
  at_onset: Record<string, unknown>
  ex_post: Record<string, unknown>
  runup_summary: Record<string, number>
}

export type OutcomeDist = Record<string, Record<string, number>>

export type Analogs = {
  dyad: string
  t: string
  source: 'elasticsearch' | 'local'
  query: {
    vector_available: boolean
    schema: Record<string, unknown>
    macro_region: string | null
    excluded_crisno: number | null
    runup_summary: Record<string, number> & {
      weeks?: { t: string; log_events: number; q4_share: number; goldstein_mean: number }[]
    }
  }
  vector: Analog[]
  schema: Analog[]
  hybrid: Analog[]
  vector_outcomes: OutcomeDist
  schema_outcomes: OutcomeDist
  hybrid_outcomes: OutcomeDist
}

export type MarketRow = {
  source: string
  market_id: string
  question: string
  dyad: string
  dyad_label: string
  outcome: number
  resolution_time: string
  snapshot_date: string
  p_market: number
  p_model: number
  p_model_raw: number
  model_pct: number
  p_stack_both: number
  p_stack_model: number
  direction: number
  url: string
  volume: number
}

export type MarketSummary = {
  n_markets: number
  n_dyads: number
  snapshot_days_before: number
  brier: Record<string, number>
  logloss: Record<string, number>
  loo: Record<string, number>
  base_rate: number
  by_source: Record<string, { n: number; brier_market: number; brier_model: number }>
  caveats: string[]
}

export type Markets = { available: false; reason: string } | { available: true; summary: MarketSummary; rows: MarketRow[] }

export type Episode = {
  kind: 'market' | 'icb'
  dyad: string
  dyad_label: string
  date: string
  question: string
  p_model: number
  p_model_raw: number
  model_pct?: number
  p_market: number | null
  outcome: number
  resolution_time?: string
  url?: string
  crisis?: string | null
}

export class ApiError extends Error {
  status: number
  constructor(status: number, msg: string) {
    super(msg)
    this.status = status
  }
}

async function get<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const qs = params
    ? '?' +
      Object.entries(params)
        .filter(([, v]) => v !== undefined && v !== '')
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
        .join('&')
    : ''
  const r = await fetch(`/api${path}${qs}`)
  if (!r.ok) {
    let detail = r.statusText
    try {
      const j = await r.json()
      detail = j.detail ?? detail
    } catch {
      /* ignore */
    }
    throw new ApiError(r.status, detail)
  }
  return (await r.json()) as T
}

export const api = {
  meta: () => get<Meta>('/meta'),
  map: (date: string, label: string, top = 30) => get<MapSnapshot>('/map', { date, label, top }),
  series: (dyad: string, start: string, end: string, label: string) =>
    get<Series>(`/dyad/${dyad}/series`, { start, end, label }),
  forecast: (dyad: string, date: string, label: string) => get<Forecast>(`/dyad/${dyad}/forecast`, { date, label }),
  analogs: (dyad: string, date: string, k = 5) => get<Analogs>(`/dyad/${dyad}/analogs`, { date, k }),
  markets: () => get<Markets>('/markets'),
  episodes: (n: number, seed?: number) => get<{ episodes: Episode[] }>('/game/episodes', { n, seed }).then((r) => r.episodes),
}
