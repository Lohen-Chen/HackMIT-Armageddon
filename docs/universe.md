# Dyad universe

Built by `pipeline/features.py`.

| | |
|---|---|
| Distinct undirected country dyads ever seen in GDELT (after pseudo-code filter) | 18,917 |
| Dyads in the panel (>= 200 events in trailing 365d at some week, or ever an ICB dyad) | 4,879 |
| ... of which ever an ICB crisis dyad | 250 |
| Panel rows (dyad x week) | 3,029,505 |
| Rows kept by the activity rule | 2,774,189 |
| Rows kept only because the dyad is an ICB dyad | 255,316 |
| Date range of forecast dates | 1979-01-07 00:00:00 .. 2026-09-20 00:00:00 |
| Calendar weeks with no GDELT files at all (zero-filled, windows stay 7k days) | 2 |
| Columns | 133 |

The rule uses only trailing information (events in the 52 weeks up to and including the forecast
date), so it introduces no look-ahead.  The ICB clause guarantees historical crisis dyads with
thin coverage (e.g. small African states in the 1980s backfile) are not silently excluded.
