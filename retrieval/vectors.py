"""The 90-day (13-week) GDELT run-up vector, shared by case indexing and live queries.

vector = z-scored [log1p(n_events), q4_share, q3_share, goldstein_mean, tone_mean, log1p(1e6*rate)]
         for each of the 13 weeks ending at the last Sunday <= end_date  -> 78 dims.
Only weeks with t <= end_date are used.  The z-score constants are fit on panel rows with
t < scaler_fit_end (default 2010-01-01) and frozen in data/artifacts/vector_scaler.json.
"""
import json
import os

import duckdb
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANEL_DIR = os.path.join(ROOT, "data", "processed", "panel")
SCALER_PATH = os.path.join(ROOT, "data", "artifacts", "vector_scaler.json")
N_WEEKS = 13
FEATS = ["log_events", "q4_share", "q3_share", "goldstein_mean", "tone_mean", "log_rate"]
DIM = N_WEEKS * len(FEATS)


def _con(panel_dir=PANEL_DIR):
    con = duckdb.connect()
    con.execute(f"CREATE VIEW dw AS SELECT * FROM read_parquet('{panel_dir}/dyad_week.parquet')")
    con.execute(f"CREATE VIEW wt AS SELECT * FROM read_parquet('{panel_dir}/week_tot.parquet')")
    return con


def weekly_frame(con, dyad, end_date, n_weeks=N_WEEKS):
    """Dense n_weeks x FEATS frame for `dyad` ending at the last Sunday <= end_date."""
    end_date = pd.Timestamp(end_date)
    last_sunday = end_date - pd.Timedelta(days=(end_date.weekday() + 1) % 7)
    first = last_sunday - pd.Timedelta(weeks=n_weeks - 1)
    df = con.execute("""
        WITH weeks AS (SELECT t, tot_events FROM wt WHERE t BETWEEN ? AND ?)
        SELECT w.t, coalesce(d.n_events,0) AS n_events, coalesce(d.q4,0) AS q4, coalesce(d.q3,0) AS q3,
               coalesce(d.goldstein_sum,0) AS goldstein_sum, coalesce(d.tone_sum,0) AS tone_sum, w.tot_events
        FROM weeks w LEFT JOIN dw d ON d.t = w.t AND d.dyad = ? ORDER BY w.t""",
                     [first.date(), last_sunday.date(), dyad]).df()
    # pad missing weeks (before data starts) with zeros
    if len(df) < n_weeks:
        pad = pd.DataFrame({"t": pd.date_range(first, periods=n_weeks - len(df), freq="7D")})
        df = pd.concat([pad, df], ignore_index=True).fillna(0)
    out = pd.DataFrame({"t": df.t})
    out["log_events"] = np.log1p(df.n_events)
    out["q4_share"] = df.q4 / df.n_events.replace(0, np.nan)
    out["q3_share"] = df.q3 / df.n_events.replace(0, np.nan)
    out["goldstein_mean"] = df.goldstein_sum / df.n_events.replace(0, np.nan)
    out["tone_mean"] = df.tone_sum / df.n_events.replace(0, np.nan)
    out["log_rate"] = np.log1p(1e6 * df.n_events / df.tot_events.replace(0, np.nan))
    return out.fillna(0.0)


def fit_scaler(panel_dir=PANEL_DIR, fit_end="2010-01-01", path=SCALER_PATH):
    con = _con(panel_dir)
    stats = con.execute(f"""
      WITH x AS (
        SELECT ln(1+d.n_events) AS log_events, d.q4/d.n_events AS q4_share, d.q3/d.n_events AS q3_share,
               d.goldstein_sum/d.n_events AS goldstein_mean, d.tone_sum/d.n_events AS tone_mean,
               ln(1+1e6*d.n_events/w.tot_events) AS log_rate
        FROM dw d JOIN wt w USING (t) WHERE d.t < DATE '{fit_end}' AND d.n_events > 0)
      SELECT {", ".join(f"avg({f}) AS {f}_mean, stddev_samp({f}) AS {f}_std" for f in FEATS)} FROM x""").df().iloc[0]
    scaler = {f: {"mean": float(stats[f + "_mean"]), "std": float(stats[f + "_std"]) or 1.0} for f in FEATS}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"fit_end": fit_end, "n_weeks": N_WEEKS, "feats": FEATS, "scaler": scaler}, f, indent=1)
    return scaler


def load_scaler(path=SCALER_PATH):
    with open(path) as f:
        return json.load(f)["scaler"]


def runup_vector(con, dyad, end_date, scaler):
    fr = weekly_frame(con, dyad, end_date)
    z = np.stack([(fr[f].values - scaler[f]["mean"]) / scaler[f]["std"] for f in FEATS], axis=1)  # 13 x 6
    return z.astype(np.float32).reshape(-1), fr


def runup_summary(fr):
    return {"peak_log_events": float(fr.log_events.max()), "mean_q4_share": float(fr.q4_share.mean()),
            "last_goldstein": float(fr.goldstein_mean.iloc[-1]), "min_goldstein": float(fr.goldstein_mean.min()),
            "events_trend": float(fr.log_events.iloc[-4:].mean() - fr.log_events.iloc[:4].mean())}


if __name__ == "__main__":
    s = fit_scaler()
    print(json.dumps(s, indent=1))
