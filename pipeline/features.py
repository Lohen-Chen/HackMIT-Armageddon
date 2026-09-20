"""Build the undirected dyad x week feature panel from the dyad-day aggregates.

Inputs  : <gdelt_out>/dyad_day/*.parquet, <gdelt_out>/daily_totals/*.parquet,
          data/processed/icb/dyads.parquet (for the "ever an ICB dyad" universe rule)
Outputs : <out>/dyad_week.parquet   (weekly sums per undirected dyad, dense grid)
          <out>/panel.parquet       (rolling features, one row per dyad x forecast date)
          <out>/universe.md         (how many dyads / rows, and why)

Conventions
* Weeks are Monday..Sunday.  A panel row's forecast date `t` is the Sunday; every feature is a
  function of GDELT rows with information-arrival day <= t.  Labels (labels/build_labels.py)
  use (t, t+30d].
* Undirected dyad key = 'AAA_BBB' with AAA < BBB.  Direction is kept only through q4_ab / q4_ba
  (material-conflict counts in each direction) to get an asymmetry feature.
* Universe rule (all pre-t information): a dyad-week is kept if
    trailing-365d deduplicated events >= min_trailing_events_365d   OR   the dyad ever appears
    in ICB.  Regional pseudo-codes (AFR, EUR, MEA, ...) are excluded.
* Windows: 1, 4, 13, 52 weeks (7 / 28 / 91 / 364 days).  The 30- and 90-day windows in the
  spec are approximated by 4 and 13 whole weeks so every row uses identical, gap-free windows.
  The week grid is a dense calendar (every Sunday from the first to the last week of data): weeks
  with no GDELT files at all (e.g. the 2025-06-15..2025-07-01 archive outage) are zero-filled, so a
  k-week window always spans exactly 7k calendar days.
"""
import argparse
import os

import duckdb
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# GDELT/CAMEO non-state / regional pseudo country codes to exclude from the dyad universe
PSEUDO = ["AFR", "ASA", "BLK", "CAU", "CFR", "CRB", "CAS", "EEU", "EUR", "LAM", "MEA", "MDT", "NAF",
          "NMR", "PGS", "SAM", "SAS", "SCN", "SEA", "SLV", "WAF", "WLF", "WST", "SAF_", "AFR",
          "EAF", "CEU", "NEU", "SEU", "WEU", "IGO", "NGO", "MNC", "UIS", "ARB", "OCE", "GOV"]

ROOT_KEEP = ["10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "20"]  # verbal+material conflict

SUM_COLS = ["n_events", "n_mentions", "n_articles", "n_root", "goldstein_sum", "goldstein_wsum",
            "tone_sum", "tone_wsum", "q1", "q2", "q3", "q4", "q1_m", "q2_m", "q3_m", "q4_m"] + \
           [f"r{c}" for c in ROOT_KEEP] + [f"m{c}" for c in ROOT_KEEP]


def build(gdelt_out, out, cfg, threads=8, mem="24GB", icb_dyads=None):
    os.makedirs(out, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={threads}")
    con.execute(f"PRAGMA memory_limit='{mem}'")
    con.execute(f"PRAGMA temp_directory='{os.path.join(out, 'duck_tmp')}'")
    min_ev = cfg["panel"]["min_trailing_events_365d"]
    pseudo = ",".join(f"'{p}'" for p in sorted(set(PSEUDO)))
    icb_dyads = icb_dyads or os.path.join(ROOT, "data", "processed", "icb", "dyads.parquet")

    sums = ",\n".join(f"sum({c}) AS {c}" for c in SUM_COLS)
    print("1/6 undirected dyad-week sums")
    con.execute(f"""
    CREATE TABLE dyad_week AS
    WITH dd AS (
      SELECT date_trunc('week', day) + INTERVAL 6 DAY AS t,     -- Sunday
             least(actor1_cc, actor2_cc) AS cc_a, greatest(actor1_cc, actor2_cc) AS cc_b,
             CASE WHEN actor1_cc < actor2_cc THEN q4 ELSE 0 END AS q4_ab,
             CASE WHEN actor1_cc < actor2_cc THEN 0 ELSE q4 END AS q4_ba,
             * EXCLUDE (day, actor1_cc, actor2_cc)
      FROM read_parquet('{gdelt_out}/dyad_day/*.parquet')
      WHERE length(actor1_cc)=3 AND length(actor2_cc)=3
        AND actor1_cc NOT IN ({pseudo}) AND actor2_cc NOT IN ({pseudo})
        AND actor1_cc = upper(actor1_cc) AND actor2_cc = upper(actor2_cc)
    )
    SELECT CAST(t AS DATE) AS t, cc_a, cc_b, cc_a || '_' || cc_b AS dyad,
           {sums}, sum(q4_ab) AS q4_ab, sum(q4_ba) AS q4_ba
    FROM dd GROUP BY ALL
    """)

    print("2/6 global weekly totals")
    con.execute(f"""
    CREATE TABLE week_tot AS
    WITH raw AS (
      SELECT CAST(date_trunc('week', day) + INTERVAL 6 DAY AS DATE) AS t,
             sum(n_events) AS tot_events, sum(n_mentions) AS tot_mentions, sum(q4) AS tot_q4
      FROM read_parquet('{gdelt_out}/daily_totals/*.parquet') GROUP BY ALL
    ),
    cal AS (
      SELECT CAST(unnest(generate_series((SELECT min(t) FROM raw), (SELECT max(t) FROM raw), INTERVAL 7 DAY)) AS DATE) AS t
    )
    SELECT cal.t, coalesce(r.tot_events, 0) AS tot_events, coalesce(r.tot_mentions, 0) AS tot_mentions,
           coalesce(r.tot_q4, 0) AS tot_q4
    FROM cal LEFT JOIN raw r USING (t)
    """)
    gap_weeks = con.execute("SELECT count(*) FROM week_tot WHERE tot_events = 0").fetchone()[0]
    print(f"   weeks with no GDELT data (zero-filled): {gap_weeks}")

    print("3/6 dense grid + rolling windows")
    # dense grid per dyad from its first active week to the last week in the data
    # (dyads that never reach min_ev events in total can never pass the trailing-365d rule)
    con.execute(f"""
    CREATE TABLE grid AS
    WITH span AS (SELECT dyad, cc_a, cc_b, min(t) AS t0 FROM dyad_week GROUP BY ALL
                  HAVING sum(n_events) >= {min_ev}
                      OR dyad IN (SELECT dyad FROM read_parquet('{icb_dyads}') WHERE dyad IS NOT NULL)),
         weeks AS (SELECT DISTINCT t FROM week_tot)
    SELECT s.dyad, s.cc_a, s.cc_b, w.t FROM span s JOIN weeks w ON w.t >= s.t0
    """)
    zero = ",\n".join(f"coalesce(d.{c},0) AS {c}" for c in SUM_COLS + ["q4_ab", "q4_ba"])
    con.execute(f"""
    CREATE TABLE dense AS
    SELECT g.dyad, g.cc_a, g.cc_b, g.t, {zero}
    FROM grid g LEFT JOIN dyad_week d USING (dyad, t)
    """)
    con.execute("DROP TABLE grid")

    win = {1: "w1", 4: "w4", 13: "w13", 52: "w52"}
    roll_cols = ["n_events", "n_mentions", "q1", "q2", "q3", "q4", "q4_m", "goldstein_sum", "goldstein_wsum",
                 "tone_sum", "tone_wsum", "n_root", "q4_ab", "q4_ba"] + [f"r{c}" for c in ROOT_KEEP]
    roll = []
    for k, name in win.items():
        for c in roll_cols:
            if k == 52 and c not in ("n_events", "n_mentions", "q4", "q3", "goldstein_sum", "tone_sum"):
                continue
            roll.append(f"sum({c}) OVER w{k} AS {c}_{name}")
    frames = "\n".join(f"w{k} AS (PARTITION BY dyad ORDER BY t ROWS BETWEEN {k-1} PRECEDING AND CURRENT ROW)"
                       + ("," if i < len(win) - 1 else "") for i, k in enumerate(win))
    con.execute(f"""
    CREATE TABLE rolled AS
    SELECT dyad, cc_a, cc_b, t,
           {", ".join(roll)},
           -- forward-looking sums used ONLY by labels/build_labels.py (never as features)
           sum(q4) OVER fwd4 AS q4_next4w,
           sum(n_events) OVER fwd4 AS n_events_next4w
    FROM dense
    WINDOW {frames},
           fwd4 AS (PARTITION BY dyad ORDER BY t ROWS BETWEEN 1 FOLLOWING AND 4 FOLLOWING)
    """)
    con.execute("DROP TABLE dense")

    print("4/6 global totals rolling")
    con.execute("""
    CREATE TABLE tot_rolled AS
    SELECT t,
           sum(tot_events) OVER w4 AS tot_events_w4, sum(tot_events) OVER w13 AS tot_events_w13,
           sum(tot_q4) OVER w4 AS tot_q4_w4, sum(tot_q4) OVER w13 AS tot_q4_w13,
           sum(tot_events) OVER w1 AS tot_events_w1
    FROM week_tot
    WINDOW w1 AS (ORDER BY t ROWS BETWEEN 0 PRECEDING AND CURRENT ROW),
           w4 AS (ORDER BY t ROWS BETWEEN 3 PRECEDING AND CURRENT ROW),
           w13 AS (ORDER BY t ROWS BETWEEN 12 PRECEDING AND CURRENT ROW)
    """)

    print("5/6 ICB history + universe filter + derived features")
    con.execute(f"""
    CREATE TABLE icb_d AS
    SELECT dyad, onset_date, end_date, crisno FROM read_parquet('{icb_dyads}')
    WHERE dyad IS NOT NULL AND onset_date IS NOT NULL
    """)
    con.execute("""
    CREATE TABLE icb_hist AS
    SELECT r.dyad, r.t,
           count(i.crisno) AS icb_prior_crises,
           min(date_diff('day', i.onset_date, r.t))::INTEGER AS days_since_icb_onset
    FROM (SELECT DISTINCT dyad, t FROM rolled) r
    LEFT JOIN icb_d i ON i.dyad = r.dyad AND i.onset_date <= r.t
    GROUP BY ALL
    """)
    con.execute(f"""
    CREATE TABLE panel AS
    SELECT r.*,
           -- shares / means
           r.q4_w1 / nullif(r.n_events_w1,0) AS q4_share_w1,
           r.q4_w4 / nullif(r.n_events_w4,0) AS q4_share_w4,
           r.q4_w13 / nullif(r.n_events_w13,0) AS q4_share_w13,
           r.q3_w4 / nullif(r.n_events_w4,0) AS q3_share_w4,
           r.q1_w4 / nullif(r.n_events_w4,0) AS q1_share_w4,
           (r.q3_w4 + r.q4_w4) / nullif(r.n_events_w4,0) AS conflict_share_w4,
           r.q4_m_w4 / nullif(r.n_mentions_w4,0) AS q4_mention_share_w4,
           r.goldstein_sum_w1 / nullif(r.n_events_w1,0) AS goldstein_mean_w1,
           r.goldstein_sum_w4 / nullif(r.n_events_w4,0) AS goldstein_mean_w4,
           r.goldstein_sum_w13 / nullif(r.n_events_w13,0) AS goldstein_mean_w13,
           r.goldstein_wsum_w4 / nullif(r.n_mentions_w4,0) AS goldstein_wmean_w4,
           r.tone_sum_w4 / nullif(r.n_events_w4,0) AS tone_mean_w4,
           r.tone_sum_w13 / nullif(r.n_events_w13,0) AS tone_mean_w13,
           r.tone_wsum_w4 / nullif(r.n_mentions_w4,0) AS tone_wmean_w4,
           r.n_root_w4 / nullif(r.n_events_w4,0) AS root_share_w4,
           -- root-code shares (4w)
           {", ".join(f"r.r{c}_w4 / nullif(r.n_events_w4,0) AS r{c}_share_w4" for c in ROOT_KEEP)},
           -- volume-normalised rates
           r.n_events_w1 / nullif(tt.tot_events_w1,0) AS rate_w1,
           r.n_events_w4 / nullif(tt.tot_events_w4,0) AS rate_w4,
           r.n_events_w13 / nullif(tt.tot_events_w13,0) AS rate_w13,
           r.q4_w4 / nullif(tt.tot_q4_w4,0) AS q4_rate_w4,
           r.q4_w13 / nullif(tt.tot_q4_w13,0) AS q4_rate_w13,
           -- escalation ratios vs own baseline
           r.n_events_w1 / nullif(r.n_events_w13/13.0,0) AS ev_ratio_1_13,
           r.n_events_w4 / nullif(r.n_events_w52/13.0,0) AS ev_ratio_4_52,
           r.q4_w1 / nullif(r.q4_w13/13.0,0) AS q4_ratio_1_13,
           r.q4_w4 / nullif(r.q4_w52/13.0,0) AS q4_ratio_4_52,
           (r.goldstein_sum_w1 / nullif(r.n_events_w1,0)) - (r.goldstein_sum_w13 / nullif(r.n_events_w13,0)) AS goldstein_delta_1_13,
           (r.goldstein_sum_w4 / nullif(r.n_events_w4,0)) - (r.goldstein_sum_w52 / nullif(r.n_events_w52,0)) AS goldstein_delta_4_52,
           (r.tone_sum_w4 / nullif(r.n_events_w4,0)) - (r.tone_sum_w52 / nullif(r.n_events_w52,0)) AS tone_delta_4_52,
           -- direction asymmetry
           abs(r.q4_ab_w4 - r.q4_ba_w4) / nullif(r.q4_ab_w4 + r.q4_ba_w4,0) AS q4_asym_w4,
           -- baselines for the secondary label (trailing 52w -> per-4w rate)
           r.q4_w52 / 13.0 AS q4_base_4w,
           -- ICB history (pre-t only)
           h.icb_prior_crises, h.days_since_icb_onset,
           -- regime + calendar
           CASE WHEN r.t >= DATE '2013-04-01' THEN 1 ELSE 0 END AS regime_daily,
           year(r.t) AS year,
           -- universe flags
           (r.n_events_w52 >= {min_ev}) AS active_365,
           (r.dyad IN (SELECT dyad FROM icb_d)) AS ever_icb
    FROM rolled r
    JOIN tot_rolled tt USING (t)
    LEFT JOIN icb_hist h USING (dyad, t)
    WHERE r.n_events_w52 >= {min_ev} OR r.dyad IN (SELECT dyad FROM icb_d)
    """)
    con.execute("DROP TABLE rolled")

    print("6/6 write")
    con.execute(f"COPY dyad_week TO '{out}/dyad_week.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.execute(f"COPY week_tot TO '{out}/week_tot.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.execute(f"COPY panel TO '{out}/panel.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)")
    stats = con.execute("""
    SELECT count(*) AS rows, count(DISTINCT dyad) AS dyads, min(t) AS t_min, max(t) AS t_max,
           sum(active_365::INT) AS rows_active, sum((ever_icb AND NOT active_365)::INT) AS rows_icb_only,
           count(DISTINCT dyad) FILTER (ever_icb) AS dyads_icb
    FROM panel""").df().iloc[0]
    all_dyads = con.execute("SELECT count(DISTINCT dyad) FROM dyad_week").fetchone()[0]
    ncols = len(con.execute("DESCRIBE panel").fetchall())
    md = f"""# Dyad universe

Built by `pipeline/features.py`.

| | |
|---|---|
| Distinct undirected country dyads ever seen in GDELT (after pseudo-code filter) | {all_dyads:,} |
| Dyads in the panel (>= {min_ev} events in trailing 365d at some week, or ever an ICB dyad) | {stats.dyads:,} |
| ... of which ever an ICB crisis dyad | {stats.dyads_icb:,} |
| Panel rows (dyad x week) | {int(stats.rows):,} |
| Rows kept by the activity rule | {int(stats.rows_active):,} |
| Rows kept only because the dyad is an ICB dyad | {int(stats.rows_icb_only):,} |
| Date range of forecast dates | {stats.t_min} .. {stats.t_max} |
| Calendar weeks with no GDELT files at all (zero-filled, windows stay 7k days) | {gap_weeks} |
| Columns | {ncols} |

The rule uses only trailing information (events in the 52 weeks up to and including the forecast
date), so it introduces no look-ahead.  The ICB clause guarantees historical crisis dyads with
thin coverage (e.g. small African states in the 1980s backfile) are not silently excluded.
"""
    with open(os.path.join(out, "universe.md"), "w") as f:
        f.write(md)
    print(md)
    con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gdelt-out", required=True, help="dir containing dyad_day/ and daily_totals/")
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "processed", "panel"))
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--mem", default="24GB")
    args = ap.parse_args()
    with open(os.path.join(ROOT, "config.yaml")) as f:
        cfg = yaml.safe_load(f)
    build(args.gdelt_out, args.out, cfg, args.threads, args.mem)
