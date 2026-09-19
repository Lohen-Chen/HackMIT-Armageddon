"""Build the compact, git-tracked demo pack under data/artifacts/demo/.

The full pipeline outputs (data/processed/**, ~1.6 GB) are not committed.  The API (app/api/store.py)
looks for each artifact in its full-pipeline location first and falls back to this pack, so a fresh clone
can run the demo with `make serve` and no data rebuild.

    python3 scripts/pack_demo.py [--top-dyads 150]
"""
import argparse
import json
import os
import shutil

import duckdb
import pandas as pd
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = lambda *a: os.path.join(ROOT, *a)  # noqa: E731
DEMO = P("data", "artifacts", "demo")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-dyads", type=int, default=60, help="panel rows (SHAP drivers) kept for this many dyads")
    ap.add_argument("--week-dyads", type=int, default=400, help="weekly event rows (retrieval vectors, replay chart) kept for this many dyads")
    a = ap.parse_args()
    cfg = yaml.safe_load(open(P("config.yaml")))
    con = duckdb.connect()
    for sub in ("panel", "models/y_icb", "models/y_thresh", "icb", "markets"):
        os.makedirs(os.path.join(DEMO, sub), exist_ok=True)

    fc = P("data/artifacts/models/y_icb/forecasts.parquet")
    dyads = con.execute(f"SELECT dyad, max(p_raw) mx FROM read_parquet('{fc}') GROUP BY dyad ORDER BY mx DESC").df()
    active = set(dyads.dyad)
    keep = set(dyads.dyad.head(a.top_dyads))
    for h in cfg["demo"]["hero_dyads"]:
        keep.add("_".join(sorted([h["a"], h["b"]])))
    mj = P("data/processed/markets/market_model_joined.parquet")
    if os.path.exists(mj):
        keep |= set(pd.read_parquet(mj).dyad)
    weekly = set(dyads.dyad.head(a.week_dyads)) | keep
    print(f"active dyads={len(active)} weekly dyads kept={len(weekly)} panel dyads kept={len(keep)}")

    # forecasts + slim OOS predictions for both labels
    for label in ("y_icb", "y_thresh"):
        d = P("data/artifacts/models", label)
        con.execute(f"COPY (SELECT * FROM read_parquet('{d}/forecasts.parquet')) TO '{DEMO}/models/{label}/forecasts.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)")
        con.execute(f"COPY (SELECT dyad, CAST(t AS DATE) AS t, p_cal, p_persist, p_base, fold FROM read_parquet('{d}/predictions.parquet')) "
                    f"TO '{DEMO}/models/{label}/predictions.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)")

    # weekly dyad events for the pickable universe (retrieval vectors + replay chart)
    con.register("act", pd.DataFrame({"dyad": sorted(weekly)}))
    pan = P("data/processed/panel")
    con.execute(f"COPY (SELECT d.* FROM read_parquet('{pan}/dyad_week.parquet') d JOIN act USING (dyad)) "
                f"TO '{DEMO}/panel/dyad_week.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.execute(f"COPY (SELECT * FROM read_parquet('{pan}/week_tot.parquet')) TO '{DEMO}/panel/week_tot.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)")

    # labelled panel restricted to top dyads and model features (for local SHAP drivers)
    feats = set()
    for label in ("y_icb", "y_thresh"):
        feats |= set(json.load(open(P("data/artifacts/models", label, "features.json"))))
    cols = ", ".join(f'"{c}"' for c in ["dyad", "t", "y_icb", "y_thresh", "in_crisis"] + sorted(feats))
    con.register("keep", pd.DataFrame({"dyad": sorted(keep)}))
    con.execute(f"COPY (SELECT {cols} FROM read_parquet('{pan}/panel_labelled.parquet') p JOIN keep USING (dyad)) "
                f"TO '{DEMO}/panel/panel_labelled.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)")

    for f in ("actors.parquet", "crises.parquet", "dyads.parquet"):
        shutil.copy(P("data/processed/icb", f), os.path.join(DEMO, "icb", f))
    for f in ("market_model_joined.parquet", "market_compare.json", "markets.parquet"):
        src = P("data/processed/markets", f)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(DEMO, "markets", f))

    total = 0
    for dp, _, fs in os.walk(DEMO):
        for f in fs:
            sz = os.path.getsize(os.path.join(dp, f))
            total += sz
            print(f"{sz / 1e6:8.1f} MB  {os.path.relpath(os.path.join(dp, f), ROOT)}")
    print(f"total {total / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
