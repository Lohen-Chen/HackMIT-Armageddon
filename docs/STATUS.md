# STATUS

Updated continuously; newest at the top.

## Now
- Prediction-market collection (Polymarket/Kalshi) running; then `markets/compare.py`.
- Demo app (FastAPI + React) next.

## Done
- **M4 retrieval**: `retrieval/` — 13-week run-up vector (78-d, z-scored on pre-2010 stats), 771 case docs
  (512 crises, 268 with vectors) indexed into `signal_icb_cases`; Faiss/ES vector, ES/local schema,
  RRF hybrid retrievers; head-to-head in `docs/retrieval_eval.md` (hybrid best: violence-outcome
  agreement 0.49 vs 0.17 majority baseline; ES kNN date filter inside `knn.filter`).
- **M3 models**: `models/train.py` walk-forward LightGBM (6 folds, 30-day gap, isotonic on validation only),
  base-rate / persistence / logistic baselines, SHAP, final model + `models/score.py` scoring all 3.03M
  dyad-weeks (1979-2026) with Wilson band per isotonic step.  y_icb pooled AUC 0.90 (AP 0.009 vs base
  0.0003); y_thresh pooled AUC 0.77, Brier 0.0240 vs base 0.0253.  Full numbers in
  `data/artifacts/models/*/metrics.json`.
- **M2 panel + labels**: full-history GDELT 1.0 (5,009/5,011 files; two daily files 404 on GDELT's server)
  -> 18,917 dyads seen, 4,881 in panel, 3.03M dyad-weeks; labels 159/160 ICB crisis-dyads (onset >= 1979)
  reachable (`docs`: `data/processed/panel/labels_report.md`, `universe.md`).
- Tests: `tests/test_ingest.py` (dedup, stale filter, Taiwan, same-country), `tests/test_leakage.py`
  (feature selector, saved feature list vs ex-post tiers, rolling-window recomputation, label timing).
- M1: scaffold, ICB v16 load + mapping (146/148 codes), variable tiers, ES write test, GDELT ingest.

## Blocked / risks
- Isotonic calibration on the rare ICB label has few distinct steps (max calibrated p = 5.6%): shown
  honestly in the app with the band + percentile rank.
- Market questions are not the ICB-onset label; comparison is a *signal* comparison (see ASSUMPTIONS).

## Milestone log
- M1 (scaffold, ICB, ES check, GDELT sample) - done.
- M2 (full GDELT panel, labels) - done.
- M3 (walk-forward model, calibration, baselines, SHAP, leakage tests) - done.
- M4 (retrieval, ES index, head-to-head) - done.
