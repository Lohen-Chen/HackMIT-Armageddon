# ASSUMPTIONS

Decisions taken without asking, with the reason.  Newest at the bottom.

## Data sources
1. **GDELT 1.0 event archive (`data.gdeltproject.org/events/`) is used for the whole 1979-present
   history**, not the curated S3 `gdelt-open-data` bucket.  Reason: the challenge README says the
   S3 bucket stops updating around 2019; the public 1.0 archive is continuous from 1979 to today
   and is what the challenge fetch tool ultimately points at.  GDELT 2.0 (15-minute, 2015+) is
   not ingested: 1.0 daily files already cover the same events at daily resolution and using one
   coding pipeline avoids a second regime break.
2. **GDELT regime break.**  Files are yearly (1979-2005), monthly (2006-2013/03) and daily
   (2013/04+).  Daily files have an extra SOURCEURL column and, critically, contain *all events
   that entered GDELT that day*, including references to old events.  We therefore:
   * define the information-arrival `day` as the file date for daily files and SQLDATE for the
     backfile;
   * drop daily-file rows whose SQLDATE is more than 7 days before the file date (stale
     references), and add a `regime` feature (0 = backfile, 1 = daily) to the model.
3. **Deduplication** = collapse rows with identical (SQLDATE, Actor1Code, Actor2Code, EventCode,
   ActionGeo lat/long) keeping the max NumMentions.  GDELT does not carry a stable duplicate key,
   so this is a heuristic; counts are reported both raw and deduped in the sample check.
4. **Actor country.**  `ActorCountryCode` is used.  Taiwan (`TWN`) has no CAMEO country code and
   is recovered from the actor-code prefix.  East Germany (`GME`, 1979-1990) and Kosovo have no
   country code in GDELT and are unmatched (6 of 1,131 ICB crisis-actor rows) - logged in
   `data/processed/icb/unmatched_actors.csv`, not dropped silently.  Regional pseudo-codes
   (AFR, EUR, MEA, WST, ...) are excluded from the dyad universe.
5. **Historical entities** in ICB are mapped to the ISO-3 code GDELT itself uses for their
   successor: USSR->RUS, Yugoslavia/Serbia-Montenegro->SRB, Czechoslovakia->CZE,
   North/South Vietnam->VNM, South Yemen->YEM, Zaire->COD, Hejaz/Najd->SAU.
6. **ICB ends in 2021** (v16, last onset 2021-09-20; "Russian Invasion of Ukraine" is a
   placeholder row with no dates and is excluded).  Everything after 2021-12-31 has GDELT
   features but no ICB label; the model is evaluated only where labels exist and the 2022+
   window is used purely for the live-replay demo and the prediction-market comparison.
7. **ICB actor mapping is one-directional.**  GDELT dyads are unordered (`min_max` of ISO-3
   codes); ICB dyads are mapped the same way, so "who triggered whom" is not part of the label.

## Dyad universe
8. A dyad enters the panel in a week if it had >= 200 deduplicated GDELT events in the trailing
   365 days *or* it appears in any ICB dyad ever.  This keeps ~1-2k dyads instead of 40k+ and is
   entirely pre-forecast-date information.  Documented in `pipeline/features.py`.

## Labels
9. Primary label = ICB crisis onset for the dyad in (t, t+30d].  Weeks inside an ongoing ICB
   crisis for that dyad are dropped from training/eval (not a new onset, not a clean negative).
10. Secondary label = material-conflict events (QuadClass 4) in the next 30 days >= 3x the
    trailing-365d mean 30-day rate AND >= 20 events.  Thresholds in `config.yaml`.

## Modelling
11. Walk-forward folds by year boundaries in `config.yaml`; training rows end 30 days before the
    validation window starts (label horizon gap).  Calibration (isotonic) is fit on the validation
    slice only and applied to the later test slice.  The "final" model for the live demo is trained
    on the first 85% of labelled time and calibrated on the last 15%, so every forecast after
    2021-12-31 (end of complete ICB coverage) is strictly out-of-sample.
11b. Isotonic calibration on a 0.05% base rate yields a step function with few levels (max
    calibrated p about 5.6%).  The app shows the calibrated probability, a Wilson 80% band derived
    from the validation rows in the same isotonic step, and the raw score's percentile rank among
    all dyads that week.  We do not smooth or inflate the probabilities.
11c. `days_since_icb_onset` / `icb_prior_crises` (history of *earlier* ICB crises for the dyad, as
    of t) are legitimate pre-t features and are used; nothing about the crisis being forecast is.

## Retrieval
12. Only `pre_onset` and `at_onset` ICB variables may enter schema retrieval; `ex_post` is
    display-only.  See `docs/icb_variable_tiers.md`.
13. Vector = 13 weeks x 6 z-scored GDELT features (log events, QuadClass-3/4 shares, mean
    Goldstein, mean tone, log volume-normalised rate) ending at the last Sunday <= query date; 78
    dims, no PCA (config originally said 32-d PCA; a fixed linear map fit on all cases would leak
    future cases into the basis).  z-score constants are fit on dyad-weeks before 2010-01-01 and frozen.
13b. Case documents are one per crisis-dyad (771 docs for 512 crises).  Retrievers de-duplicate by
    crisis id client-side.  Pre-1979 crises have no vector and are only reachable via schema search.
13c. `regime_pair`, `nuclear_max`, `powsta_max` are aggregated from ICB actor-level rows and are
    pre-onset attributes of the actors, not outcomes.

## Prediction markets
16. Markets are collected from Polymarket (Gamma + CLOB price history) and Kalshi public APIs,
    filtered to resolved binary Yes/No questions with escalation keywords and >= 2 detectable
    countries (keyword aliases, `markets/collect.py`); mapping is written to
    `data/processed/markets/market_dyad_map.csv` for inspection.
17. Market questions ("Will X strike Y by <date>?") are not the ICB-onset label.  The comparison
    treats the market's resolution as the outcome and the model's calibrated escalation probability
    for the dyad at the snapshot date as its forecast.  It is a *signal* comparison, reported with
    n and without claiming either side "wins" beyond what the Brier scores show.

## Infra
14. Analytical source of truth is parquet under `data/processed/`; Elasticsearch holds only the
    `signal_icb_cases` and `signal_dyad_forecasts` serving indices and can be rebuilt from parquet.
15. The compute instance has an 8 GB root disk and no sudo; large work happens in `/dev/shm`
    (186 GB tmpfs) and results are copied back to this repo / the dev box after each stage so
    nothing depends on the instance surviving.
