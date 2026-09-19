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
    test window starts (label horizon gap).  Calibration (isotonic) fit on the last 20% of each
    training window only.

## Retrieval
12. Only `pre_onset` and `at_onset` ICB variables may enter schema retrieval; `ex_post` is
    display-only.  See `docs/icb_variable_tiers.md`.
13. Vector = standardised 90-day pre-onset GDELT feature run-up (fixed weekly grid), same
    function for historical cases and live queries.

## Infra
14. Analytical source of truth is parquet under `data/processed/`; Elasticsearch holds only the
    `signal_icb_cases` and `signal_dyad_forecasts` serving indices and can be rebuilt from parquet.
15. The compute instance has an 8 GB root disk and no sudo; large work happens in `/dev/shm`
    (186 GB tmpfs) and results are copied back to this repo / the dev box after each stage so
    nothing depends on the instance surviving.
