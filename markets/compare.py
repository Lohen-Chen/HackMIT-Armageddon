"""Model vs prediction-market comparison at matched pre-resolution times.

Reads data/processed/markets/markets.parquet (from markets/collect.py) and the final-model forecasts
(data/artifacts/models/y_icb/forecasts.parquet), joins each market to the model forecast for the same
dyad in the week of the market snapshot (default: 30 days before resolution), and writes

  data/processed/markets/market_model_joined.parquet   one row per market
  data/processed/markets/market_compare.json           summary shown by the app

Semantics (see docs/ASSUMPTIONS.md):
* Markets are oriented so that YES == escalation.  Ceasefire / "war ends" questions are flipped
  (p -> 1-p, outcome -> 1-outcome).
* The model's number is P(ICB-coded crisis onset within 30 days) - a *different* event from the market
  question.  We therefore report (a) the raw calibrated probability's Brier as-is (mostly a sanity check),
  and (b) leave-one-out logistic stacks: market-only vs market + model percentile, which is the fair test
  of whether the GDELT signal adds information to the market price.
"""
from __future__ import annotations

import json
import os
import re
import sys

import duckdb
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

MK = os.path.join(ROOT, "data", "processed", "markets")
FC = os.path.join(ROOT, "data", "artifacts", "models", "y_icb", "forecasts.parquet")

ESCALATION_KW = re.compile(
    r"strike|attack|invade|invasion|ceasefire|cease-fire|\bwar\b|military|missile|troops|nuclear|bomb|escalat|"
    r"offensive|incursion|airstrike|ground operation|capture|occup|engagement|declare war",
    re.I,
)
DEESCALATION_KW = re.compile(
    r"ceasefire|cease-fire|truce|peace (?:deal|agreement|talks)|ends? (?:the )?(?:\w+ )?war|end of military operations|"
    r"withdraw|agrees? to .*ceasefire",
    re.I,
)
# dated one-day markets ("... on February 27 (ET)?") are not 30-day-horizon questions
DAILY_KW = re.compile(r"\bon (?:january|february|march|april|may|june|july|august|september|october|november|december) \d", re.I)

SNAP_DAYS = 30
MAX_PER_EVENT = 1
MAX_PER_DYAD = 5
MIN_VOLUME = 250_000


def select_markets(m: pd.DataFrame) -> pd.DataFrame:
    col = f"price_d{SNAP_DAYS}"
    u = m[m.dyad.notna() & m[col].notna() & (m.volume >= MIN_VOLUME)].copy()
    u = u[u.question.str.contains(ESCALATION_KW, regex=True) & ~u.question.str.contains(DAILY_KW, regex=True)]
    u["direction"] = np.where(u.question.str.contains(DEESCALATION_KW), -1, 1)
    u["p_market"] = np.where(u.direction == 1, u[col], 1 - u[col]).astype(float)
    u["outcome_esc"] = np.where(u.direction == 1, u.outcome, 1 - u.outcome).astype(int)
    u = u.sort_values("volume", ascending=False)
    u = u.groupby("event", group_keys=False).head(MAX_PER_EVENT)
    u = u.groupby("dyad", group_keys=False).head(MAX_PER_DYAD)
    u["snapshot_date"] = (pd.to_datetime(u.resolution_time, utc=True) - pd.Timedelta(days=SNAP_DAYS)).dt.tz_localize(None).dt.normalize()
    return u.reset_index(drop=True)


def join_model(u: pd.DataFrame) -> pd.DataFrame:
    con = duckdb.connect()
    con.register("mk", u[["source", "market_id", "dyad", "snapshot_date"]])
    j = con.execute(f"""
        WITH fc AS (
            SELECT dyad, t, p_raw, p_cal, percent_rank() OVER (PARTITION BY t ORDER BY p_raw) AS pct
            FROM read_parquet('{FC}')
        ),
        pick AS (
            SELECT mk.source, mk.market_id, f.t AS model_t, f.p_raw AS p_model_raw, f.p_cal AS p_model, f.pct AS model_pct,
                   row_number() OVER (PARTITION BY mk.source, mk.market_id ORDER BY f.t DESC) AS rn
            FROM mk JOIN fc f ON f.dyad = mk.dyad AND f.t <= mk.snapshot_date AND f.t >= mk.snapshot_date - INTERVAL 13 DAY
        )
        SELECT * EXCLUDE (rn) FROM pick WHERE rn = 1
    """).df()
    out = u.merge(j, on=["source", "market_id"], how="inner")
    return out


def brier(p, y):
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def logloss(p, y):
    p = np.clip(np.asarray(p, dtype=float), 1e-4, 1 - 1e-4)
    y = np.asarray(y)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-3, 1 - 1e-3)
    return np.log(p / (1 - p))


def _fit_logreg(X, y, l2=1.0, iters=500, lr=0.1):
    """Tiny ridge-regularised logistic regression (avoids a sklearn dependency here)."""
    X = np.column_stack([np.ones(len(X)), X])
    w = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-X @ w))
        g = X.T @ (p - y) / len(y) + l2 * np.r_[0, w[1:]] / len(y)
        w -= lr * g
    return w


def loo_stack(df: pd.DataFrame, cols):
    X = np.column_stack([df[c].to_numpy(dtype=float) for c in cols])
    y = df.outcome_esc.to_numpy(dtype=float)
    preds = np.zeros(len(y))
    for i in range(len(y)):
        mask = np.arange(len(y)) != i
        w = _fit_logreg(X[mask], y[mask])
        preds[i] = 1 / (1 + np.exp(-(w[0] + X[i] @ w[1:])))
    return preds


def main():
    m = pd.read_parquet(os.path.join(MK, "markets.parquet"))
    u = select_markets(m)
    j = join_model(u)
    j["logit_market"] = logit(j.p_market)
    j["model_pct"] = j.model_pct.astype(float)
    j["logit_model"] = logit(j.p_model)
    print(f"markets after selection: {len(u)}; with model forecast in snapshot week: {len(j)}")
    if len(j) < 10:
        raise SystemExit("too few joined markets")

    y = j.outcome_esc.to_numpy()
    base = float(y.mean())
    j["p_stack_market"] = loo_stack(j, ["logit_market"])
    j["p_stack_both"] = loo_stack(j, ["logit_market", "model_pct"])
    j["p_stack_model"] = loo_stack(j, ["model_pct"])

    summary = {
        "n_markets": int(len(j)),
        "n_dyads": int(j.dyad.nunique()),
        "snapshot_days_before": SNAP_DAYS,
        "base_rate": base,
        "brier": {
            "market": brier(j.p_market, y),
            "base_rate": brier(np.full(len(y), base), y),
            "model_raw_icb": brier(j.p_model, y),
        },
        "logloss": {
            "market": logloss(j.p_market, y),
            "base_rate": logloss(np.full(len(y), base), y),
            "model_raw_icb": logloss(j.p_model, y),
        },
        "loo": {
            "market_only": brier(j.p_stack_market, y),
            "model_only": brier(j.p_stack_model, y),
            "market_plus_model": brier(j.p_stack_both, y),
        },
        "by_source": {
            s: {"n": int(len(g)), "brier_market": brier(g.p_market, g.outcome_esc), "brier_model": brier(g.p_model, g.outcome_esc)}
            for s, g in j.groupby("source")
        },
        "caveats": [
            "Market questions (e.g. 'US strikes Iran by <date>') are not the ICB onset event the model was trained on; "
            "the raw model Brier is reported for transparency, not as a like-for-like score.",
            "Ceasefire / 'war ends' markets are flipped so YES always means escalation.",
            "Markets are all from 2023-11 onward, i.e. after the ICB label window (through 2021-12-31): the model's trees and "
            "calibration are fully out-of-sample here.",
            f"Selection: escalation keyword filter, volume >= ${MIN_VOLUME:,}, a price {SNAP_DAYS} days before resolution, "
            f"at most {MAX_PER_EVENT} markets per event and {MAX_PER_DYAD} per country pair.",
            "Leave-one-out stacks refit a 1-2 parameter logistic on the other markets; with n this small the market-only vs "
            "market+model gap is indicative, not significant.",
        ],
    }
    j.to_parquet(os.path.join(MK, "market_model_joined.parquet"), index=False)
    with open(os.path.join(MK, "market_compare.json"), "w") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps({k: v for k, v in summary.items() if k != "caveats"}, indent=1))
    print(j.groupby("dyad").size().sort_values(ascending=False).to_string())


if __name__ == "__main__":
    main()
