# STATUS

Updated continuously; newest at the top.

## Now
- Full-history GDELT 1.0 ingest running on the compute instance (5,011 files, ~8 min wall).
- Next: dyad-week feature panel + labels (`pipeline/features.py`, `labels/build_labels.py`).

## Done
- Repo scaffold, `config.yaml`, `.gitignore`.
- ICB v16 downloaded (system/actor/dyad + codebooks), coverage report `docs/icb_coverage.md`,
  actor mapping 146/148 codes, variable tiers `docs/icb_variable_tiers.md`.
- Elasticsearch: `signal_*` create/write/kNN-with-date-filter/delete verified with the API key.
- GDELT 1.0 ingest (`pipeline/gdelt_ingest.py`): DuckDB, dedup, stale-event filter, dyad-day /
  country-day / daily-totals parquet.  Validated on 1990, 201001, 20180101 files.

## Blocked / risks
- None currently.  SSH to the instance works with the updated password.

## Milestone log
- M1 (scaffold, ICB, ES check, GDELT sample) - done.
