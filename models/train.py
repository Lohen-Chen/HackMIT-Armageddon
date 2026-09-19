"""Walk-forward LightGBM forecaster with isotonic calibration, baselines and SHAP.

Usage: python models/train.py [--label y_icb|y_thresh] [--panel path]

For each fold in config.model.folds:
  train : t <  train_end - gap          (rows whose full 30-day label window ends before train_end)
  valid : train_end <= t < valid_end - gap    (calibration + early stopping ONLY)
  test  : valid_end <= t < test_end
Rows with in_crisis=1 or NULL label are excluded everywhere.

Outputs data/artifacts/models/<label>/
  metrics.json          per-fold + pooled metrics for model and baselines
  predictions.parquet   dyad, t, y, p_raw, p_cal, p_base, p_persist, p_logit, fold
  calibration.json      reliability-curve bins (pooled test)
  pr_curve.json         precision/recall operating points (pooled test)
  feature_importance.csv, shap_summary.csv
  final_model.txt / final_calibrator.pkl   trained on everything (for the live demo)
  features.json         the exact feature list (checked by tests/test_leakage.py)
"""
import argparse
import json
import os
import pickle
import warnings

import lightgbm as lgb
import numpy as np
import pandas as pd
import yaml
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, brier_score_loss, log_loss,
                             precision_recall_curve, roc_auc_score)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ID_COLS = {"dyad", "cc_a", "cc_b", "t"}
LABEL_COLS = {"y_icb", "y_thresh", "in_crisis", "next_crisno", "next_crisname", "next_onset",
              "cur_crisno", "cur_crisname"}
# columns that contain post-t information or are look-ahead selection flags
FORBIDDEN = {"q4_next4w", "n_events_next4w", "ever_icb", "active_365", "year"}
# feature names that must never appear (ICB ex-post or forward-looking patterns)
FORBIDDEN_PATTERNS = ("next", "_fwd", "outcom", "outesr", "sevvio", "crismg", "term", "viol")


def feature_columns(df):
    cols = []
    for c in df.columns:
        if c in ID_COLS or c in LABEL_COLS or c in FORBIDDEN:
            continue
        if any(p in c for p in FORBIDDEN_PATTERNS):
            continue
        if not pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c]):
            continue
        cols.append(c)
    return cols


def metrics(y, p):
    y = np.asarray(y); p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    out = {"n": int(len(y)), "pos": int(y.sum()), "brier": float(brier_score_loss(y, p)),
           "logloss": float(log_loss(y, p))}
    out["auc"] = float(roc_auc_score(y, p)) if 0 < y.sum() < len(y) else None
    out["ap"] = float(average_precision_score(y, p)) if y.sum() > 0 else None
    return out


def reliability(y, p, bins=10):
    edges = np.quantile(p, np.linspace(0, 1, bins + 1))
    edges[0], edges[-1] = 0.0, 1.0
    idx = np.clip(np.searchsorted(edges, p, side="right") - 1, 0, bins - 1)
    rows = []
    for b in range(bins):
        m = idx == b
        if m.sum() == 0:
            continue
        rows.append({"bin": b, "n": int(m.sum()), "p_mean": float(p[m].mean()), "y_rate": float(y[m].mean())})
    return rows


def pr_points(y, p):
    prec, rec, thr = precision_recall_curve(y, p)
    pts = []
    for target in (0.1, 0.2, 0.3, 0.5, 0.7):
        ok = np.where(rec[:-1] >= target)[0]
        if len(ok):
            i = ok[np.argmax(prec[:-1][ok])]
            pts.append({"recall_target": target, "precision": float(prec[i]), "recall": float(rec[i]),
                        "threshold": float(thr[i])})
    step = max(1, len(prec) // 200)
    return {"operating_points": pts,
            "curve": [{"precision": float(a), "recall": float(b)} for a, b in zip(prec[::step], rec[::step])]}


def run(panel_path, label, cfg, outdir, max_rows=None):
    os.makedirs(outdir, exist_ok=True)
    seed = cfg["seed"]
    assert cfg["model"]["calibration"] == "isotonic", "only isotonic calibration is implemented"
    gap = pd.Timedelta(days=cfg["model"]["gap_days"])
    params = dict(cfg["model"]["lightgbm"])
    n_rounds = params.pop("num_boost_round")
    es_rounds = params.pop("early_stopping_rounds")
    params["seed"] = seed

    df = pd.read_parquet(panel_path)
    df["t"] = pd.to_datetime(df["t"])
    df = df[(df["in_crisis"] == 0) & df[label].notna()].copy()
    if max_rows:
        df = df.sample(min(max_rows, len(df)), random_state=seed)
    df = df.sort_values(["t", "dyad"]).reset_index(drop=True)
    feats = feature_columns(df)
    with open(os.path.join(outdir, "features.json"), "w") as f:
        json.dump(feats, f, indent=1)
    X_all = df[feats].astype(float)
    y_all = df[label].astype(int).values
    print(f"label={label} rows={len(df):,} pos={y_all.sum():,} ({y_all.mean():.4%}) features={len(feats)}")
    # final-model split (used after the folds): last 15% of time is the calibration slice
    t_cut = df["t"].quantile(0.85)
    final_meta = {"final_train_end": str((t_cut - gap).date()), "final_calibration_start": str(t_cut.date()),
                  "gap_days": int(cfg["model"]["gap_days"]), "seed": int(seed)}
    with open(os.path.join(outdir, "train_meta.json"), "w") as f:
        json.dump(final_meta, f, indent=1)

    # persistence baseline: for y_thresh use "did it happen in the last 4 weeks", for y_icb
    # use a hazard proxy: 1/(1+days since last ICB onset)  (both are pre-t information)
    if label == "y_thresh":
        persist_raw = (df["q4_w4"].values >= np.maximum(cfg["labels"]["threshold_min_events"],
                                                       cfg["labels"]["threshold_ratio"] * df["q4_base_4w"].values)).astype(float)
    else:
        d = df["days_since_icb_onset"].astype(float).fillna(1e5).values
        persist_raw = 1.0 / (1.0 + d / 365.0)

    preds, fold_metrics, importances = [], [], []
    for k, fold in enumerate(cfg["model"]["folds"]):
        tr_end, va_end, te_end = (pd.Timestamp(fold[x]) for x in ("train_end", "valid_end", "test_end"))
        tr = df["t"] < tr_end - gap
        va = (df["t"] >= tr_end) & (df["t"] < va_end - gap)
        te = (df["t"] >= va_end) & (df["t"] < te_end)
        if y_all[tr].sum() < 5 or y_all[te].sum() == 0 or y_all[va].sum() == 0:
            print(f"fold {k}: skipped (train pos={y_all[tr].sum()}, valid pos={y_all[va].sum()}, test pos={y_all[te].sum()})")
            continue
        dtr = lgb.Dataset(X_all[tr], y_all[tr])
        dva = lgb.Dataset(X_all[va], y_all[va])
        m = lgb.train(params, dtr, n_rounds, valid_sets=[dva], callbacks=[lgb.early_stopping(es_rounds, verbose=False)])
        p_va = m.predict(X_all[va], num_iteration=m.best_iteration)
        p_te = m.predict(X_all[te], num_iteration=m.best_iteration)
        cal = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(p_va, y_all[va])
        p_cal = cal.predict(p_te)
        # baselines
        p_base = np.full(te.sum(), y_all[tr].mean())
        # persistence: calibrate the raw persistence score on train (isotonic) so it's a probability
        pers_cal = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(persist_raw[tr], y_all[tr])
        p_persist = pers_cal.predict(persist_raw[te])
        logit = make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=500, class_weight=None))
        logit.fit(X_all[tr].fillna(0), y_all[tr])
        p_logit = logit.predict_proba(X_all[te].fillna(0))[:, 1]
        fm = {"fold": k, "train_end": str(tr_end.date()), "valid_end": str(va_end.date()), "test_end": str(te_end.date()),
              "n_train": int(tr.sum()), "pos_train": int(y_all[tr].sum()), "best_iter": int(m.best_iteration),
              "model_raw": metrics(y_all[te], p_te), "model_cal": metrics(y_all[te], p_cal),
              "base_rate": metrics(y_all[te], p_base), "persistence": metrics(y_all[te], p_persist),
              "logistic": metrics(y_all[te], p_logit)}
        fold_metrics.append(fm)
        print(f"fold {k} test {va_end.date()}..{te_end.date()}: n={te.sum():,} pos={y_all[te].sum()} "
              f"AUC={fm['model_cal']['auc']:.3f} Brier={fm['model_cal']['brier']:.5f} (base {fm['base_rate']['brier']:.5f}, "
              f"logit {fm['logistic']['brier']:.5f}) AP={fm['model_cal']['ap']:.3f}")
        preds.append(pd.DataFrame({"dyad": df.loc[te, "dyad"].values, "t": df.loc[te, "t"].values, "y": y_all[te],
                                   "p_raw": p_te, "p_cal": p_cal, "p_base": p_base, "p_persist": p_persist,
                                   "p_logit": p_logit, "fold": k}))
        importances.append(pd.Series(m.feature_importance("gain"), index=feats, name=f"fold{k}"))

    P = pd.concat(preds, ignore_index=True)
    P.to_parquet(os.path.join(outdir, "predictions.parquet"), index=False)
    pooled = {name: metrics(P["y"], P[col]) for name, col in
              [("model_raw", "p_raw"), ("model_cal", "p_cal"), ("base_rate", "p_base"),
               ("persistence", "p_persist"), ("logistic", "p_logit")]}
    with open(os.path.join(outdir, "metrics.json"), "w") as f:
        json.dump({"label": label, "n_features": len(feats), "folds": fold_metrics, "pooled": pooled,
                   "final": final_meta}, f, indent=1)
    with open(os.path.join(outdir, "calibration.json"), "w") as f:
        json.dump({"model_cal": reliability(P["y"].values, P["p_cal"].values),
                   "model_raw": reliability(P["y"].values, P["p_raw"].values),
                   "logistic": reliability(P["y"].values, P["p_logit"].values)}, f, indent=1)
    with open(os.path.join(outdir, "pr_curve.json"), "w") as f:
        json.dump(pr_points(P["y"].values, P["p_cal"].values), f)
    imp = pd.concat(importances, axis=1)
    imp["mean_gain"] = imp.mean(axis=1)
    imp.sort_values("mean_gain", ascending=False).to_csv(os.path.join(outdir, "feature_importance.csv"))
    print("pooled:", json.dumps(pooled, indent=None))

    # ---- final model on all labelled data (last 15% of time as calibration slice)
    tr = df["t"] < t_cut - gap
    va = df["t"] >= t_cut
    m = lgb.train(params, lgb.Dataset(X_all[tr], y_all[tr]), n_rounds, valid_sets=[lgb.Dataset(X_all[va], y_all[va])],
                  callbacks=[lgb.early_stopping(es_rounds, verbose=False)])
    p_va_final = m.predict(X_all[va], num_iteration=m.best_iteration)
    cal = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(p_va_final, y_all[va])
    pd.DataFrame({"p_raw": p_va_final, "y": y_all[va]}).to_parquet(os.path.join(outdir, "final_valid_preds.parquet"), index=False)
    m.save_model(os.path.join(outdir, "final_model.txt"), num_iteration=m.best_iteration)
    with open(os.path.join(outdir, "final_calibrator.pkl"), "wb") as f:
        pickle.dump(cal, f)

    # ---- SHAP on a sample of recent rows
    try:
        import shap
        samp = X_all[va].sample(min(4000, int(va.sum())), random_state=seed)
        sv = shap.TreeExplainer(m).shap_values(samp)
        if isinstance(sv, list):
            sv = sv[1]
        s = pd.DataFrame({"feature": feats, "mean_abs_shap": np.abs(sv).mean(axis=0)}).sort_values("mean_abs_shap", ascending=False)
        s.to_csv(os.path.join(outdir, "shap_summary.csv"), index=False)
        print("top SHAP:", s.head(10).to_dict("records"))
    except Exception as e:  # noqa: BLE001
        print("SHAP skipped:", e)
    return pooled


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", default=os.path.join(ROOT, "data", "processed", "panel", "panel_labelled.parquet"))
    ap.add_argument("--label", default="y_icb", choices=["y_icb", "y_thresh"])
    ap.add_argument("--out", default=None)
    ap.add_argument("--max-rows", type=int, default=None)
    args = ap.parse_args()
    with open(os.path.join(ROOT, "config.yaml")) as f:
        cfg = yaml.safe_load(f)
    out = args.out or os.path.join(ROOT, "data", "artifacts", "models", args.label)
    run(args.panel, args.label, cfg, out, args.max_rows)
