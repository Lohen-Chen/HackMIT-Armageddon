"""Score every panel row with the final model + isotonic calibrator and attach a calibration-aware band.

Band: the isotonic calibrator is a step function fit on the final validation slice.  For a raw score
we find the validation rows that fall in the same calibrated step and report the Wilson 80% interval of
the empirical event rate in that step (n small -> wide band).  Rows after the training window are
genuinely out-of-sample (the final model only sees labelled rows, i.e. t <= icb_last_complete_date).

Output: data/artifacts/models/<label>/forecasts.parquet  (dyad, t, p_raw, p_cal, p_lo, p_hi, in_crisis, y)
"""
import argparse
import json
import os
import pickle

import lightgbm as lgb
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def wilson(pos, n, z=1.2816):
    if n == 0:
        return 0.0, 1.0
    p = pos / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centre - half), min(1.0, centre + half)


def build_bands(cal, valid_preds):
    """Map each isotonic step (unique calibrated value) -> (n, pos, lo, hi)."""
    p_cal = cal.predict(valid_preds["p_raw"].values)
    df = pd.DataFrame({"p_cal": p_cal, "y": valid_preds["y"].values})
    g = df.groupby("p_cal").agg(n=("y", "size"), pos=("y", "sum")).reset_index()
    rows = []
    for r in g.itertuples():
        lo, hi = wilson(r.pos, r.n)
        rows.append({"p_cal": float(r.p_cal), "n": int(r.n), "pos": int(r.pos), "lo": lo, "hi": hi})
    return rows


def main(label, panel_path, modeldir, chunk=400_000):
    feats = json.load(open(os.path.join(modeldir, "features.json")))
    m = lgb.Booster(model_file=os.path.join(modeldir, "final_model.txt"))
    cal = pickle.load(open(os.path.join(modeldir, "final_calibrator.pkl"), "rb"))
    bands = build_bands(cal, pd.read_parquet(os.path.join(modeldir, "final_valid_preds.parquet")))
    json.dump(bands, open(os.path.join(modeldir, "calibration_bands.json"), "w"), indent=1)
    band_df = pd.DataFrame(bands).set_index("p_cal")

    cols = ["dyad", "t", "in_crisis", label] + feats
    df = pd.read_parquet(panel_path, columns=cols)
    out = []
    for i in range(0, len(df), chunk):
        part = df.iloc[i:i + chunk]
        p_raw = m.predict(part[feats].astype(float))
        p_cal = cal.predict(p_raw)
        lo = np.interp(p_cal, band_df.index.values, band_df["lo"].values)
        hi = np.interp(p_cal, band_df.index.values, band_df["hi"].values)
        out.append(pd.DataFrame({"dyad": part["dyad"].values, "t": part["t"].values, "p_raw": p_raw, "p_cal": p_cal,
                                 "p_lo": np.minimum(lo, p_cal), "p_hi": np.maximum(hi, p_cal),
                                 "in_crisis": part["in_crisis"].values, "y": part[label].values}))
        print(f"scored {min(i + chunk, len(df)):,}/{len(df):,}")
    F = pd.concat(out, ignore_index=True)
    F.to_parquet(os.path.join(modeldir, "forecasts.parquet"), index=False)
    print(F.describe().T[["mean", "50%", "max"]])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="y_icb")
    ap.add_argument("--panel", default=os.path.join(ROOT, "data", "processed", "panel", "panel_labelled.parquet"))
    ap.add_argument("--modeldir", default=None)
    a = ap.parse_args()
    main(a.label, a.panel, a.modeldir or os.path.join(ROOT, "data", "artifacts", "models", a.label))
