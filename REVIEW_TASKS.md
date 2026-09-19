# Implementation tasks from code review

Repo: `Lohen-Chen/HackMIT-Armageddon` (branch `main`). Python 3.11 backend (FastAPI + DuckDB +
LightGBM), React/Vite frontend in `app/frontend`, data pipeline in `pipeline/`, `labels/`, `models/`,
`retrieval/`, `markets/`. Tests: `python -m pytest -q tests`. Lint: `python -m pyflakes ...` (see
`Makefile` target `lint`) and `cd app/frontend && npm run typecheck`.

Work through the tasks in order. Each task is independent unless noted. Keep changes minimal and
in the style of the surrounding code (short functions, no new frameworks). Run `make test lint`
after every task. The API tests in `tests/test_api.py` run against the git-tracked demo pack under
`data/artifacts/demo/` and must keep passing; do **not** regenerate or commit anything under
`data/artifacts/demo/`.

Open one PR per section (A, B, C, D) unless a task says otherwise.

---

## A. Security (do first)

### A1. Parametrize the dyad in the run-up SQL and validate dyads at the API boundary

**Problem.** `retrieval/vectors.py` `weekly_frame()` builds SQL with an f-string:

```python
FROM weeks w LEFT JOIN dw d ON d.t = w.t AND d.dyad = '{dyad}' ORDER BY w.t
```

`app/api/main.py` route `GET /api/dyad/{dyad}/analogs` passes the raw path segment (only
`.upper()`-ed) into `Store.analogs()` which calls `runup_vector()` -> `weekly_frame()`. A crafted
dyad is a SQL injection into DuckDB, which can read arbitrary local files (`read_text`,
`read_csv`, ...). Also, any dyad without an underscore raises `ValueError` in
`Store.live_schema` / `Store.dyad_label` (`a, b = dyad.split("_")`) and returns a 500.

**Do.**
1. In `retrieval/vectors.py` `weekly_frame()`, pass `dyad` and the two dates as bound parameters
   (`con.execute(sql, [first, last, dyad])`) instead of interpolating. `first`/`last` are
   `pd.Timestamp`; pass `.date()` objects. Keep the output identical.
2. In `app/api/main.py`, add a helper:
   ```python
   DYAD_RE = re.compile(r"^[A-Z]{3}_[A-Z]{3}$")
   def _dyad(s: str) -> str:
       s = s.upper()
       if not DYAD_RE.fullmatch(s):
           raise HTTPException(400, f"bad dyad {s!r}; use AAA_BBB with ISO3 codes")
       return s
   ```
   and use it in the `series`, `forecast`, and `analogs` routes in place of `dyad.upper()`.
3. Add tests to `tests/test_api.py::test_bad_inputs`:
   - `GET /api/dyad/ISR/analogs?date=2006-07-05` -> 400
   - `GET /api/dyad/ISR_LBN'%20OR%20'1'='1/analogs?date=2006-07-05` -> 400
   - `GET /api/dyad/isr_lbn/forecast?date=2006-07-09` -> 200 (lower-case still accepted)

**Accept.** `grep -n "'{dyad}'" retrieval/vectors.py` returns nothing; new tests pass;
`test_analogs_respect_query_date` still passes with identical analog lists.

### A2. Stop path traversal in the SPA fallback route

**Problem.** `app/api/main.py` bottom:

```python
@app.get("/{path:path}")
def spa(path: str):
    f = os.path.join(DIST, path)
    if path and os.path.isfile(f):
        return FileResponse(f)
    return FileResponse(os.path.join(DIST, "index.html"))
```

`path` can contain `..` segments (uvicorn does not normalize them), so
`GET /../../config.yaml` serves a file outside `app/frontend/dist`.

**Do.** Replace the body with a realpath check:

```python
root = os.path.realpath(DIST)
f = os.path.realpath(os.path.join(root, path))
if path and f.startswith(root + os.sep) and os.path.isfile(f):
    return FileResponse(f)
return FileResponse(os.path.join(root, "index.html"))
```

Also make the fallback not swallow unknown API routes: if `path.startswith("api/")` raise
`HTTPException(404)`.

**Do (test).** In `tests/test_api.py` add a test that creates a temporary `dist/` (or monkeypatches
`DIST`) and asserts `GET /../../config.yaml` and `GET /..%2F..%2Fconfig.yaml` do not return YAML
(status 200 with `index.html` body, or 404, both acceptable) and `GET /api/nope` is 404. If
wiring a temp dist is awkward because the route is registered at import time, restructure the
mount into a small `mount_frontend(app, dist_dir)` function called at import with the default
path, so the test can call it on a fresh `FastAPI()` with a `tmp_path`.

**Accept.** Traversal test passes; `make serve` still serves the built frontend at `/`.

---

## B. Correctness and configuration drift

### B1. Derive the final-model training boundary from a training artifact, not a constant

**Problem.** `app/api/store.py`:

```python
FINAL_TRAIN_END = date(2018, 11, 25)      # trees trained on t < this (85% time quantile, see models/train.py)
ICB_COMPLETE_END = date(2021, 12, 31)
```

`models/train.py` computes `t_cut = df["t"].quantile(0.85)` and trains the final model on
`t < t_cut - gap`. If anyone retrains, the constant is stale and the UI's
`trees_out_of_sample` flag and the footer text become wrong. `ICB_COMPLETE_END` duplicates
`config.yaml` `labels.icb_last_complete_date`.

**Do.**
1. In `models/train.py` `run()`, after computing `t_cut`, write a JSON file
   `os.path.join(outdir, "train_meta.json")` with
   `{"final_train_end": str((t_cut - gap).date()), "final_calibration_start": str(t_cut.date()), "gap_days": ..., "seed": ...}`.
   Also add the same keys under a `"final"` key in `metrics.json`.
2. In `app/api/store.py`:
   - Replace the module constant with an instance attribute set in `_load_model()` (or
     `_load_forecasts()`): read `train_meta.json` from `data/artifacts/models/<label>/`; if the
     file is missing fall back to `date(2018, 11, 25)` and append a note to `self.notes` saying
     the boundary is a fallback. Use the `y_icb` value for the flags (both labels are trained on
     the same panel/time split; assert they agree if both exist).
   - Replace `ICB_COMPLETE_END` with `date.fromisoformat(self.cfg["labels"]["icb_last_complete_date"])`.
   - Update `_sample_flags`, `_horizon_coded`, `meta()`, `series()` to use the attributes.
3. Commit a hand-written `data/artifacts/models/y_icb/train_meta.json` and
   `data/artifacts/models/y_thresh/train_meta.json` with `final_train_end: "2018-11-25"` so the
   demo pack keeps working without retraining (the existing `final_model.txt` was trained with
   that boundary). Do not retrain.

**Accept.** `grep -n "FINAL_TRAIN_END\|ICB_COMPLETE_END" app/api/store.py` returns nothing;
`test_forecast_flags_and_realised_label` passes unchanged.

### B2. Make `config.yaml` actually the source of truth (or trim it)

**Problem.** README says `config.yaml` is the single source of truth, but:
- `model.interval: bootstrap` and `model.n_bootstrap` are never read (the band is a Wilson
  interval per isotonic step in `models/score.py`).
- `markets.snapshot_days_before_resolution` and `markets.min_markets` are ignored;
  `markets/compare.py` hardcodes `SNAP_DAYS = 30`, `MAX_PER_EVENT`, `MAX_PER_DYAD`, `MIN_VOLUME`
  and `main()` uses `if len(j) < 10`.
- `retrieval.k` and `retrieval.vector_dim` are unused; `retrieval/vectors.py` hardcodes
  `N_WEEKS = 13` and `FEATS`.

**Do.**
1. Delete `model.interval` and `model.n_bootstrap` from `config.yaml`; add a comment on the
   `calibration` line: `# band = Wilson 80% interval per isotonic step (models/score.py)`.
2. In `markets/compare.py`, load `config.yaml` in `main()` and read
   `SNAP_DAYS = cfg["markets"]["snapshot_days_before_resolution"][0]` and
   `min_markets = cfg["markets"]["min_markets"]` (replace the hardcoded `10`). Add
   `max_per_event: 1`, `max_per_dyad: 5`, `min_volume_usd: 250000` under `markets:` in
   `config.yaml` and read them. Keep module-level defaults so `select_markets()` remains callable
   from `tests/test_markets.py` without config (accept the values as keyword args with the current
   defaults).
3. In `app/api/main.py` `analogs` route, default `k` to `cfg["retrieval"]["k"]` (expose it via
   `Store.cfg`), keep the clamp to `[1, 10]`.
4. In `retrieval/vectors.py`, add `assert DIM == cfg["retrieval"]["vector_dim"]` inside
   `fit_scaler()` (load config there), so a mismatch fails loudly at build time.
5. Update the README sentence about `config.yaml` if anything remains intentionally hardcoded.

**Accept.** Every top-level key and sub-key in `config.yaml` is referenced by at least one
`cfg[...]` access (`grep -rn 'cfg\[' --include=*.py .`), or has been removed.

### B3. GDELT ingest resume: do not skip files with partial output

**Problem.** `pipeline/gdelt_ingest.py` `process_file()` returns `"skip"` when
`<outdir>/dyad_day/<stem>.parquet` exists, but `dyad_day` is written **first** of three outputs
(`dyad_day`, `daily_totals`, `country_day`). A crash between writes leaves `dyad_day` present and
`daily_totals` missing; on resume the file is skipped forever and `pipeline/features.py`
`week_tot` silently lacks that day, corrupting every `rate_*` / `q4_rate_*` feature for that week.

**Do.** Check all three outputs before skipping:

```python
outs = {sub: os.path.join(outdir, sub, f"{stem}.parquet") for sub in ("dyad_day", "daily_totals", "country_day")}
if all(os.path.exists(p) for p in outs.values()):
    return stem, "skip", 0
```

and write `dyad_day` last (reorder the tuple in the `for sub, sql in (...)` loop). Add a
unit test in `tests/test_ingest.py` that calls `process_file` with a monkeypatched `_download`
(copy a local fixture zip) into `tmp_path`, deletes `daily_totals/<stem>.parquet`, calls again and
asserts the result is not `"skip"` and the file is regenerated.

**Accept.** New test passes; existing ingest tests unchanged.

### B4. Run-up vector padding when the query date is after the last week of data

**Problem.** `retrieval/vectors.py` `weekly_frame()` pads missing weeks by **prepending** zeros
(`pd.concat([pad, df])`). That is right when the dyad's data starts late, but if `end_date` is
after the last week in `wt`, the missing weeks are at the end, and prepending shifts the whole
13-week vector.

**Do.** Build the full 13-Sunday calendar in Python (`pd.date_range(first, last_sunday, freq="7D")`),
left-join the query result onto it, and fill zeros. This pads at both ends correctly and
removes the special-case branch. Add a unit test in a new `tests/test_vectors.py` that builds a
tiny in-memory DuckDB with `dw`/`wt` views (`con.register` two small DataFrames) and asserts
(a) a dyad with data in all 13 weeks round-trips, (b) an `end_date` two weeks past the last `wt`
row yields zeros in the last two rows, not the first two.

**Accept.** New tests pass; `test_analogs_respect_query_date` returns the same analogs (the
demo-pack dates are all inside the data range).

### B5. Game: label the stacked "model" number honestly

**Problem.** `Store.game_episodes()` uses `p_model = r.p_stack_model` for market episodes (the
leave-one-out logistic re-fit of the model percentile on the other markets), while ICB episodes
use the raw out-of-sample calibrated probability. `app/frontend/src/components/Game.tsx` shows
both as "Model". The README explicitly says the stack result is "indicative, not significant".

**Do.** Add a field `model_kind: "stacked_percentile" | "calibrated_oos"` to each episode in
`game_episodes()`, add it to the `Episode` type in `app/frontend/src/api.ts`, and in `Game.tsx`
render the model player label as `Model (re-fit on other markets)` for stacked episodes with a
`title` tooltip explaining it. No numeric change.

**Accept.** `npm run typecheck` passes; `test_markets_and_game` passes.

---

## C. Repo hygiene and performance

### C1. Faster API: materialize forecast views and cache the game quantile

**Problem.** `Store._load_forecasts()` creates DuckDB **views** over parquet, so every slider
tick re-scans 3M rows. `Store.forecast()` runs two correlated subqueries per call;
`Store.game_episodes()` recomputes `quantile_cont(p_raw, 0.97)` over the whole table per call.

**Do.**
1. In `_load_forecasts()`, `CREATE TABLE fc_<label> AS SELECT * FROM read_parquet(...)` and the
   same for `oos_<label>`. Memory is ~150 MB for both labels; acceptable.
2. Precompute per-week counts once: `CREATE TABLE fc_<label>_week AS SELECT t, count(*) n_week FROM fc_<label> GROUP BY t`
   and join it in `forecast()` instead of the `n_week` subquery. Keep the `n_above` subquery
   (it depends on the row).
3. Compute `self._q97 = quantile_cont(p_raw, 0.97)` once in `_load_forecasts()` and bind it as a
   parameter in `game_episodes()`.
4. Replace the per-call `duckdb_views()` lookup in `series()` with a `self.has_oos: set[str]`
   filled at load time.

**Accept.** All API tests pass; startup log still prints the store summary; a manual
`time curl localhost:8000/api/dyad/ISR_LBN/forecast?date=2006-07-09` is not slower than before.

### C2. FastAPI lifespan instead of deprecated `on_event`

**Do.** Replace `@app.on_event("startup")` in `app/api/main.py` with an
`@asynccontextmanager async def lifespan(app)` that builds the `Store` and yields, and pass
`lifespan=lifespan` to `FastAPI(...)`. Keep the module-level `store` global and `_store()` helper
so nothing else changes. `TestClient(app)` as a context manager (already used in tests) triggers
lifespan.

**Accept.** No `DeprecationWarning` about `on_event` when running pytest with `-W error::DeprecationWarning -k health`.

### C3. Pin Python dependencies

**Do.** Add `requirements.in` (rename current `requirements.txt` content) and generate a fully
pinned `requirements.txt` with `pip-compile` (pip-tools) on Python 3.11 / Linux. CI already
installs from `requirements.txt`. Add a `make lock` target. Mention in README under
"Reproduce" that `requirements.txt` is a lock file generated from `requirements.in`.

**Accept.** CI green with the pinned file; `tests/test_api.py` passes (the pickled isotonic
calibrator and LightGBM model load under the pinned versions).

### C4. Run the frontend linter in CI

**Problem.** `app/frontend/.oxlintrc.json` exists but `package.json` has no `lint` script and
`oxlint` is not a devDependency; CI only runs `typecheck` and `build`.

**Do.** `npm i -D oxlint` in `app/frontend`, add `"lint": "oxlint src"` to `scripts`, fix any
findings (expect the `react-hooks/exhaustive-deps` suppressions in `App.tsx` / `util.ts` to
stay as explicit disables), add `npm run lint` to the `frontend` job in
`.github/workflows/ci.yml` and to the `Makefile` `lint` target.

**Accept.** `npm run lint` exits 0; CI green.

### C5. Move the demo pack out of git history (Git LFS)

**Problem.** `data/artifacts/demo/` is ~140 MB and has been committed twice; `.git` is already
275 MB. Every `make pack` adds another copy.

**Do (this PR only, do not rewrite history).**
1. `git lfs install`; add `.gitattributes` with
   `data/artifacts/demo/**/*.parquet filter=lfs diff=lfs merge=lfs -text` and the same for
   `data/artifacts/cases.jsonl` and `data/artifacts/models/*/final_model.txt`.
2. `git lfs migrate import --no-rewrite --include="data/artifacts/demo/**/*.parquet,data/artifacts/cases.jsonl,data/artifacts/models/*/final_model.txt"`
   so the current tips become LFS pointers without rewriting old commits.
3. Update `.github/workflows/ci.yml` checkout steps with `lfs: true`.
4. README "One-command demo": note that Git LFS is required (`git lfs install` before clone) and
   that `git clone` without LFS gets pointer files, in which case `git lfs pull` fetches them.
5. Leave a note in `docs/STATUS.md` that a history rewrite (`git lfs migrate import` without
   `--no-rewrite`) would shrink `.git` from 275 MB but must be coordinated with all clones.

**Accept.** Fresh `git clone` + `git lfs pull` + `make test` passes; CI green.

### C6. Small cleanups (one PR)

- `pipeline/gdelt_ingest.py` writes a `country_day` aggregate that nothing reads
  (`grep -rn country_day` outside the ingest file returns nothing). Either delete it or add a
  one-line comment in the module docstring saying it is kept for future per-country features.
  Prefer delete (also remove it from task B3's output list).
- `Makefile` `setup`: print a warning if `VIRTUAL_ENV` is unset and `CONDA_PREFIX` is unset
  (`@test -n "$$VIRTUAL_ENV$$CONDA_PREFIX" || echo "warning: installing into the global interpreter; consider python3 -m venv .venv"`).
- `app/api/store.py` `Store.drivers()` is public but unlocked; mark it `_drivers` (it is only
  called from the locked `forecast()`), or wrap it with `@_locked` (RLock is re-entrant).

---

## D. Test coverage

### D1. Synthetic-panel fixture so the leakage tests run in CI

**Problem.** `tests/test_leakage.py::test_features_only_use_data_up_to_t` and
`test_labels_are_strictly_after_t` skip in CI because they need
`data/processed/panel/*.parquet` (not tracked). The README advertises these tests as leakage
controls.

**Do.** Add `tests/conftest.py` with a fixture `synthetic_gdelt(tmp_path)` that writes ~3 dyads x
~120 days of `dyad_day/*.parquet` and `daily_totals/*.parquet` in the exact schema produced by
`pipeline/gdelt_ingest.py` `build_sql()` (easiest: generate raw GDELT-format TSV rows with the
`_row()` helper from `tests/test_ingest.py`, run `build_sql` through DuckDB, and `COPY` the three
aggregates), plus a tiny `data/processed/icb/dyads.parquet`-shaped file with one crisis. Then run
`pipeline.features.build(...)` and `labels.build_labels.build(...)` into `tmp_path`, and
parametrize the two skipped tests to use the fixture output when the real panel is absent.
Use `threads=2, mem="1GB"` for the synthetic run.

**Accept.** In CI (no real panel) the two tests run and pass instead of skipping; with the real
panel present they still run against it.

### D2. Unit tests for retrieval helpers and the Wilson band

Add `tests/test_retrieval.py` covering:
- `retrieval.base.rrf_fuse`: two rankings sharing one crisno -> that crisno ranks first; output
  length <= k; `source == "hybrid"`.
- `retrieval.base.dedupe_by_crisno`: duplicates collapsed, order preserved, truncated to k.
- `retrieval.retrievers.LocalSchemaRetriever` vs `EsSchemaRetriever.build_query`: for the same
  `CaseQuery`, the set of `(field, weight)` terms in the ES `should` clause equals the set of
  fields that contributed to the local score (guards the two implementations drifting).
- `models.score.wilson`: `wilson(0, 0) == (0.0, 1.0)`; `wilson(5, 10)` brackets 0.5 and is
  narrower than `wilson(1, 2)`.
- `app.api.labels.feature_label`: `"r19_share_w4"` -> `"share of fighting (events), last 4 wks"`,
  `"m13_w13"` -> `"threats (mentions), last 13 wks"`, unknown -> underscores replaced by spaces.

**Accept.** New tests pass; no changes to production code needed (if one is, keep it minimal
and note it in the PR).

---

## Out of scope for these tasks

- Retraining models or regenerating the demo pack.
- GDELT 2.0, directed dyads, learned encoders (already listed in README "Out of scope").
- Rewriting git history (C5 note only).
