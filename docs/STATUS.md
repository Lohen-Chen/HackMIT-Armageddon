# STATUS

Updated continuously; newest at the top.

## Now
- Delivered: README (setup, architecture, results, caveats, demo script), demo pack, CI, PR.

## Done
- **Dense calendar grid fix**: GDELT published no files for 2025-06-15..2025-07-01; the panel previously
  skipped those weeks so 4/13/52-week ROWS windows spanned extra calendar days there (test_leakage caught
  it).  `pipeline/features.py` now zero-fills missing weeks; panel, labels, both models and all scores were
  rebuilt (numbers in README / `metrics.json`).
- **M7 demo pack + tests**: `scripts/pack_demo.py` writes `data/artifacts/demo/` (~140 MB, git-tracked):
  all forecasts for both labels, weekly features for the 400 most active dyads, SHAP-ready panel rows for
  the top 60 + hero + market dyads, ICB + market artifacts.  `app/api/store.py` falls back to it when the
  full pipeline output is absent (`SIGNAL_DEMO_ONLY=1` forces it).  `tests/test_api.py` runs the API against
  the pack (ranking, Sunday snapping, OOS flags, realised-onset lookup, analog `end_date < query_date`,
  deterministic game seeds, bad-input 400s).  GitHub Actions CI: pyflakes + pytest + tsc/vite build.
- **M6 demo app**: FastAPI (`app/api`, DuckDB over parquet, ES server-side, RLock around DuckDB) +
  React/Vite (`app/frontend`): world map with dyad arcs, replay slider 1979-2026, forecast card with band /
  rank / OOS flags, SHAP drivers, vector | schema | hybrid analogs with outcome histogram, markets table,
  You-vs-Model-vs-Market game.  Screenshots in `docs/screenshots/` (`scripts/screenshots.py`).
- **M5 markets**: `markets/collect.py` (Polymarket Gamma + CLOB history, Kalshi; 2,438 Polymarket rows) and
  `markets/compare.py` (60 resolved escalation/ceasefire questions, 20 dyads, 30-day-before snapshot,
  ceasefire questions inverted so YES = escalation, market/base-rate/model Brier + leave-one-out logistic
  stack market-only vs market+model).  Result: market 0.250, base 0.248, LOO stack 0.222 vs 0.222 - GDELT
  adds ~nothing on top of markets for these questions; reported as such.
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
  -> 18,917 dyads seen, 4,879 in panel, 3.03M dyad-weeks; labels 158/159 ICB crisis-dyads (onset >= 1979)
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
- M5 (prediction markets) - done.
- M6 (demo app) - done.
- M7 (README, demo pack, tests, CI) - done.
