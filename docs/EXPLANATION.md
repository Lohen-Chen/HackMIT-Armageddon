# What this thing actually measures

A plain-language guide to every number, flag and acronym in the Signal in the Noise demo.
Where a value comes from a setting, the `config.yaml` key is given so you can check it.

---

## 1. The one-sentence version

For every pair of countries that has been in the news together recently, and for every
week since 1979, we estimate **the probability that a new international crisis between
those two countries begins within the next 30 days**, using only news-event counts up to
that week. "Crisis" is not our judgement call: it means an event that the academic
**ICB** project has hand-coded as an international crisis.

Everything else in the app (percentiles, ranks, bands, analogs, market scores, the game) is
built on top of that number.

---

## 2. The two datasets

| Acronym | Full name | What it gives us | Role |
|---|---|---|---|
| **GDELT** (1.0) | Global Database of Events, Language, and Tone | Machine-coded news events, 1979 → today: who did what to whom, where, when, with a tone score. Noisy, but daily and global. | **Inputs** (features). |
| **ICB** (v16) | International Crisis Behavior project (Brecher & Wilkenfeld) | ~500 human-coded international crises since 1918 with onset/end dates, actors, triggers, severity and outcome. | **Ground truth** (labels) and the library of historical analogs. |

Other names you will see:

| Term | Meaning |
|---|---|
| **CAMEO** | The event taxonomy GDELT uses (Conflict and Mediation Event Observations). Every event has a 3–4 digit CAMEO code such as `190` = "use conventional military force". |
| **QuadClass** | CAMEO's coarse 4-way grouping: 1 = verbal cooperation, 2 = material cooperation, 3 = verbal conflict, **4 = material conflict** (fights, assaults, shows of force). In the code these are `q1`–`q4`. |
| **Goldstein score** | A −10 … +10 scale attached to every CAMEO code, from most hostile (−10, military attack) to most cooperative (+10). "Mean Goldstein" in the app is the average over a dyad's events; more negative = more hostile news. |
| **Tone** | GDELT's sentiment score of the articles behind an event (negative = negative coverage). |
| **Mentions** | How many articles mentioned an event; a rough proxy for prominence. |
| **Dyad** | A pair of countries, written as two ISO-3 codes sorted alphabetically: `ISR_LBN`, `IND_PAK`, `RUS_UKR`. Dyads are **undirected**: we do not distinguish who acted on whom for the forecast. |
| **ISO-3** | Three-letter country codes (ISR, LBN, USA…). |
| **Polymarket / Kalshi** | Prediction markets: people trade YES/NO contracts on real-world questions, so the price is a crowd probability. Used only for comparison, never as an input to the model. |

---

## 3. The forecast target (the "label")

There are two switchable targets; the dropdown in *Explore & replay* picks one.

### `y_icb` — primary: "ICB-coded international crisis begins within 30 days"

For a dyad and a forecast week ending on Sunday **t**, `y_icb = 1` if ICB records a crisis
between those two countries whose **onset date falls in (t, t + 30 days]**, else 0.

Rules that matter for reading the app:

* **Weeks already inside an ongoing ICB crisis for that dyad are not labelled** (they are
  neither a new onset nor a clean "nothing happened"). The forecast card shows
  *"Ongoing ICB crisis … Onset labels are 0 while a crisis is already under way"* and the
  chart shades those spans.
* **ICB coverage ends 2021-12-31** (`labels.icb_last_complete_date`; last coded onset is
  2021-09-20). A week is only labelled if its *whole* 30-day horizon is inside coverage, i.e.
  t ≤ 2021-12-01. Later weeks show *"Outcome not coded"* — the model still forecasts, but we
  cannot say whether it was right.
* It is **very rare**: about 0.045 % of dyad-weeks are positives (1,113 positive rows from
  158 distinct crises over 47 years). This is why calibrated probabilities are tiny — a
  "high" reading is a few percent.

### `y_thresh` — secondary: "material-conflict event surge (≥3× trailing rate) within 30 days"

A purely GDELT-defined target that exists because ICB stops in 2021.
`y_thresh = 1` if the dyad's count of QuadClass-4 (material conflict) events in the next 30 days
is **≥ 3× its trailing 52-week average 4-week count AND ≥ 20 events**
(`labels.threshold_ratio`, `labels.threshold_min_events`). About 2.5 % of rows are positive.
It runs to the present, so it is the target to use when replaying 2022 +.

Because it is defined from the same news feed as the inputs, it partly measures
*"will the news get louder"*, not *"will a crisis happen"*. Treat it as a secondary
sanity check, not the headline.

---

## 4. What the numbers on *Explore & replay* mean

### The big percentage on the Forecast card — `p_cal`

**Calibrated probability that the selected target happens for this dyad in the next 30 days**,
as of the week ending on the selected date. "Calibrated" means that, historically, among all
weeks the model gave ≈2 %, about 2 % actually had an onset. The model's raw score is
squeezed through an **isotonic regression** (a monotone step function fitted on held-out
data) to achieve this, which is why many dyads share the exact same calibrated value: there
are only a handful of steps. For `y_icb` the largest calibrated value in the whole history is
≈3.2 %.

### "band a – b"

An **80 % Wilson interval** for the calibrated probability. Each isotonic step is a bucket of
held-out weeks with some number of positives out of *n*; the band is the Wilson score interval
for that bucket's hit rate. Wide band = the step was estimated from few examples. It is a
statement about calibration uncertainty, not a prediction interval on the world.

### "raw score" — `p_raw`

The LightGBM model's own output before calibration. It has finer resolution than `p_cal`, so it
is used for **ranking** (map colours, top-30 list, rank). It is *not* a well-calibrated
probability on its own — use it to compare dyads, not to read off odds.

### "rank this week #r / n"

Position of this dyad among all **n active dyads** that week when sorted by raw score. Active
means the pair had ≥ 200 deduplicated GDELT events in the trailing 365 days
(`panel.min_trailing_events_365d`) or has ever appeared in an ICB crisis; typically 1–2k dyads.
If a pair is not active you see *"No forecast … this week"*.

### The map colours and "top X %" — `pct`

The map is coloured by **escalation-risk percentile within that week**, not by absolute
probability: `pct` is the fraction of active dyads with a lower raw score. Hovering a country
shows its riskiest dyad and "top X %" = 100 × (1 − pct). A country is coloured by the highest
percentile of any dyad it belongs to. Percentiles are used because absolute probabilities are
all small and would make the map a uniform dark blue; the colour therefore answers
*"how unusual is this pair this week, compared with everyone else?"*.

### Status / realised label / "What actually happened"

* **status** — whether the dyad is inside an ICB crisis at the forecast date.
* **realised label** — `onset ✓` / `no onset` / `not yet coded` (the actual `y_icb`). This is
  the answer key; it is never used to make the forecast.
* **What actually happened** — the crisis name and onset date if one began in the horizon.

### The three flags

They tell you how honest the number you are looking at is.

| Flag | Meaning |
|---|---|
| **trees in-sample / out-of-sample** | Was this week's data used to fit the final model's trees? The final `y_icb` model was trained on weeks before 2018-10-26 (`y_thresh`: 2022-09-30). Dates after that are genuine out-of-sample forecasts. |
| **calibration in-sample / out-of-sample** | Was this week inside the slice used to fit the isotonic calibrator (the last 15 % of labelled time)? Both boundaries come from each model's `train_meta.json`. |
| **ICB labels available / end 2021-12-31** | Can the outcome be checked at all? Off when any part of the 30-day horizon is after ICB coverage. |

The footer repeats the boundaries for the selected model.

### The time-series chart

* **Solid line** — `p_cal` from the final model over the window (the same model everywhere, so
  early years are in-sample — see flags).
* **Dashed amber** — *walk-forward out-of-sample* forecast (`p_oos`): what a model trained
  **only on data before that fold** predicted. This is the fair backtest line; it exists for
  1997 → 2021 in blocks (see §6).
* **Shaded** — ICB crisis spans; **ticks** on the slider are onset dates.
* **Bars** — total GDELT events for the dyad per week, so you can see the news volume the
  model is reacting to (material-conflict counts are in the Drivers panel's "last 4 weeks" line).

### Drivers panel

Per-feature **SHAP-style contributions** (`pred_contrib` from LightGBM) for this dyad-week, in
log-odds. Orange pushes risk up, blue down; *base log-odds* is the model's starting point
before any feature. Feature names are translated, e.g.:

| Shown as | Code name | Meaning |
|---|---|---|
| event volume | `n_events_w4` | events in the last 4 weeks (`_w1/_w4/_w13/_w52` = 1/4/13/52-week windows) |
| material conflict | `q4_*` | QuadClass-4 event counts |
| conflict surge (1 wk vs 13 wk) | `q4_ratio_1_13` | last week's material conflict ÷ 13-week average |
| avg Goldstein (hostility) | `goldstein_mean_*` | mean Goldstein score (more negative = more hostile) |
| Goldstein shift | `goldstein_delta_*` | recent mean minus longer-window mean |
| share of global GDELT volume | `rate_*` | this dyad's events ÷ all GDELT events (controls for GDELT growing over time) |
| conflict asymmetry | `q4_asym_w4` | \|A→B − B→A\| ÷ (A→B + B→A) material-conflict events over 4 weeks; 1 = entirely one-sided |
| prior ICB crises / days since last ICB onset | `icb_prior_crises`, `days_since_icb_onset` | the dyad's own crisis history *before* t |
| GDELT daily-file era | `regime_daily` | 1 from 2013-04-01, when GDELT switched to daily files and volume jumped |

If the full panel is not loaded (demo pack), the panel falls back to *global* feature
importance (gain) instead.

---

## 5. Historical analogs

Given the selected dyad and date, we retrieve the **5 most similar past ICB crises**, using only
information that existed at the forecast date. Only crises that had **ended before the forecast
date** are eligible, so nothing from the future can leak in.

Three columns:

| Column | How similarity is measured |
|---|---|
| **Similar run-up (vector)** | k-nearest-neighbours on a 78-dim vector = the dyad's last 13 weeks × 6 z-scored GDELT features (event volume, material conflict, hostility, etc.). "Looks like this on the news-volume charts." |
| **Similar structure (schema)** | Weighted match on ICB's *pre-onset* structural attributes of the pair: region, power discrepancy, great-power involvement, nuclear status, regime types, protracted-conflict membership, ethnic dimension… (`retrieval.schema_weights`). "Is the same kind of pair." |
| **Hybrid — reciprocal-rank fusion (RRF)** | Merge of the two lists: each case gets Σ 1 / (60 + rank) over the lists it appears in (`retrieval.rrf_k`). |

Retrieval runs on **Elasticsearch** (kNN + BM25 boosts) when reachable, otherwise on a local
**FAISS** index and an equivalent in-process scorer; the header pill says which.

"How these analogs turned out" shows the analogs' **ex-post** ICB fields (severity of violence,
outcome) for context only. ICB variables are split into tiers — `pre_onset` (allowed for
matching), `at_onset` (trigger type; allowed only for describing an already-started crisis) and
`ex_post` (never used for matching or forecasting) — see `docs/icb_variable_tiers.md`; a test
enforces the split.

---

## 6. How we know the model is not cheating (evaluation)

* **Walk-forward folds** (`model.folds`): six blocks. For each, train on everything before
  `train_end`, fit the calibrator on `[train_end, valid_end)`, score on `[valid_end, test_end)`.
  A **30-day gap** (`model.gap_days`) is left before each boundary so no training label window
  overlaps the validation period and none of validation overlaps test. Pooled out-of-sample
  results (test blocks 1997–2021, 1.36 M dyad-weeks):

  | target | AUC | Brier (model) | Brier (base rate) |
  |---|---|---|---|
  | `y_icb` | 0.90 | 3.00 × 10⁻⁴ | 3.01 × 10⁻⁴ |
  | `y_thresh` | 0.77 | 0.0240 | 0.0254 |

* **AUC** — probability that a randomly chosen positive week scores higher than a randomly
  chosen negative one (0.5 = coin flip, 1 = perfect ranking). Good for a rare target.
* **Brier score** — mean squared error between forecast probability and the 0/1 outcome; lower
  is better. With a 0.045 % base rate the *base-rate forecast* already scores ≈3 × 10⁻⁴, so the
  Brier improvement for `y_icb` is necessarily tiny; AUC and AP are the informative numbers.
* **AP** — average precision (area under precision–recall). Also reported in `metrics.json`.
* **Baselines** in `metrics.json`: constant base rate, persistence (recent conflict / time since
  last crisis), and logistic regression on the same features.
* **Leakage tests** (`tests/test_leakage.py`) assert that every feature uses only data ≤ t, every
  label uses only (t, t+30], and every analog ended before the query date.

---

## 7. *Model vs markets* tab

We take resolved Polymarket/Kalshi questions about military escalation between two countries,
orient them so **YES = escalation happened** (ceasefire / "war ends" questions are flipped;
"will *no* strike occur" questions are flipped too), and compare, **30 days before resolution**
(`markets.snapshot_days_before_resolution`):

* the **market price** at that time, and
* the **model's risk percentile** (`model_pct`) for that dyad in that week.

Important: the model forecasts *ICB-coded crisis onset*, not the market's exact question
("Will Israel strike Iran by June 30?"). So the raw probability is not comparable; instead we
fit a one-parameter **leave-one-out (LOO) logistic** mapping from the model's percentile to the
question outcomes on all *other* markets, and score the held-out one. The scoreboard shows
Brier / log-loss for **market only**, **model only** and **market + model** stacks. With a few
dozen markets, differences of a few thousandths are noise — the caveats on the page say so.

---

## 8. *Play the game* tab

Eight episodes. You slide a probability; you, the model and (where relevant) the market are all
scored with the **Brier score** — (forecast − outcome)², averaged; guessing 50 % every time
scores exactly 0.250.

* **ICB episodes** are drawn from *walk-forward out-of-sample* weeks from 1997 on: half are
  weeks 30 days before a coded onset, half are weeks in the top 3 % of raw risk where nothing
  was coded. The model's number is what it forecast *at the time*.
* **Market episodes** use the market price 30 days out; the model's number is its risk
  percentile mapped to the question type leave-one-out (label: *Model (re-fit on other
  markets)*). It is not the raw crisis-onset probability.
* Episode selection is seeded (the seed is chosen when the tab opens and sent to the API), so
  a run is reproducible for a given seed; *Restart* draws a fresh seed.

---

## 9. Things the numbers do **not** mean

* A 2 % reading is **not** "unlikely, ignore it": the base rate is 0.045 %, so 2 % is ~40× the
  average dyad-week and near the top of the historical range.
* Percentile ("top 3 %") is **relative to other dyads that week**; it says nothing about the
  absolute level of danger in the world that week.
* The model only sees **news event counts and tone**. It does not read text, know about troop
  movements, or use any information dated after the forecast Sunday.
* "Crisis" is ICB's definition (a threat to basic values, finite time for response, heightened
  probability of military hostilities, between *states*). Civil wars, terrorism without a state
  counterpart, and post-2021 events are outside the label.
* Pre-2013 GDELT is much sparser than post-2013 (`regime_daily` flag); features are expressed as
  ratios and shares to reduce, not eliminate, that drift.

---

## 10. Glossary (alphabetical)

| Term | Meaning |
|---|---|
| **AP** | Average precision; area under the precision–recall curve. |
| **AUC** | Area under the ROC curve; ranking quality, 0.5 = random. |
| **Brier score** | Mean squared error of probability forecasts; lower is better. |
| **Calibration** | Whether forecast probabilities match observed frequencies. We use isotonic regression fitted on held-out data. |
| **CAMEO** | Event coding scheme used by GDELT. |
| **DuckDB** | Embedded analytics database used for all the SQL over parquet files. |
| **Dyad** | Unordered pair of countries (`AAA_BBB`). |
| **ES** | Elasticsearch; hosts the analog index `signal_icb_cases`. |
| **FAISS** | Facebook AI Similarity Search; local vector index used when ES is unavailable. |
| **GDELT** | Global Database of Events, Language, and Tone. |
| **Goldstein** | −10…+10 conflict–cooperation scale per CAMEO code. |
| **ICB** | International Crisis Behavior project; human-coded crisis dataset (v16). |
| **In-sample / out-of-sample (OOS)** | Whether the data point was available when the model was fitted. Only OOS results are evidence of skill. |
| **Isotonic regression** | Monotone step-function fit used for calibration. |
| **kNN** | k-nearest-neighbours search (vector retrieval). |
| **LightGBM** | Gradient-boosted decision trees; the forecasting model. |
| **LOO** | Leave-one-out: fit on all other items, score the held-out one. |
| **`p_raw` / `p_cal` / `p_lo` / `p_hi`** | Raw model score / calibrated probability / lower and upper 80 % Wilson band. |
| **`pct`** | Within-week percentile of `p_raw` among active dyads. |
| **QuadClass** | CAMEO's 4-way event class; 4 = material conflict. |
| **RRF** | Reciprocal-rank fusion of ranked lists. |
| **SHAP / `pred_contrib`** | Per-feature contribution to a single prediction, in log-odds. |
| **Walk-forward** | Time-ordered cross-validation: always train on the past, test on the future. |
| **Wilson interval** | Binomial confidence interval used for the probability band. |
| **`y_icb` / `y_thresh`** | Primary (ICB onset) / secondary (event surge) targets. |
