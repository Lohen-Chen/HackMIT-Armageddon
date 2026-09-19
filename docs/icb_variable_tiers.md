# ICB variable tiers

Every ICB variable used anywhere in this project is assigned to exactly one tier.  The tier
determines where it is allowed to be used.  The machine-readable version of this table lives in
`pipeline/icb_prepare.py` (`TIER_SYSTEM`, `TIER_ACTOR`) and is enforced by
`tests/test_leakage.py::test_no_ex_post_in_schema_features`.

| Tier | Known when? | Allowed in features / similarity scoring? | Allowed in analog display? |
|---|---|---|---|
| **pre_onset** | Before the crisis trigger (structural attributes of the actors/system) | yes | yes |
| **at_onset** | On the trigger date (what kind of event started the crisis) | only for *retrieving* analogs of an already-started crisis; **never** for the forecasting model | yes |
| **ex_post** | Only after the crisis is over (how it was managed, how it ended) | **never** | yes, labelled "outcome" |

## System level (`icb1v16.csv`)

| Variable | Tier | Meaning |
|---|---|---|
| `geog` | pre_onset | UN region of the crisis |
| `period` | pre_onset | System period (interwar / WWII / bipolar / polycentric / unipolar) |
| `protrac`, `pcid` | pre_onset | Part of a protracted conflict, and which one |
| `powdissy` | pre_onset | Power discrepancy between principal adversaries |
| `ethnic` | pre_onset | Ethnic conflict involvement |
| `syslevsy` | pre_onset | Dominant vs subsystem crisis |
| `noactr` | pre_onset* | Number of crisis actors (*known at onset in practice; treated as structural for retrieval only) |
| `gpinv`, `powinv` | pre_onset* | Great-power / superpower involvement (structural alliance pattern; same caveat) |
| `break` (`trigent`) | at_onset | Type of trigger act and triggering entity |
| `gravcr` | at_onset | Gravity of value threatened |
| `issues` | at_onset | Number of issues |
| `crismg`, `cenviosy`, `sevviosy`, `viol`, `timvio`, `iwcmb` | ex_post | Crisis-management technique, centrality and severity of violence |
| `outesr`, `forout`, `subout`, `exsat` | ex_post | Outcome: escalation vs reduction, form, substance, satisfaction |
| `usinv`, `suinv`, `chinv`, `globorg`, `globefct`, `regorg`, `roefct`, `mediate` | ex_post | Third-party involvement and its effectiveness |
| `yrterm`, `moterm`, `daterm` | ex_post | Termination date |

## Actor level (`icb2v16.csv`)

| Variable | Tier | Meaning |
|---|---|---|
| `regime`, `durreg` | pre_onset | Regime type and duration |
| `powsta`, `nuclear`, `allycap`, `globmemb` | pre_onset | Power status, nuclear capability, alliance capability, IGO membership |
| `territ`, `age`, `col` | pre_onset | Size, age of state, colonial history |
| `econdt`, `regrep`, `socunr`, `massvl`, `gvinst`, `pethin` | pre_onset | Domestic conditions before the crisis |
| `triggr`, `trigent`, `trigloc`, `gravty`, `issue`, `chissu` | at_onset | Trigger type/entity/location, gravity, issue |
| `majres`, `trgresra`, `crismg`, `cenvio`, `sevvio` | ex_post | Major response, response time, management, violence |
| `outcom`, `outfor`, `outevl`, `outesr` | ex_post | Outcome for the actor, its form, evaluation, escalation |
| `yrterm`, `moterm`, `daterm` | ex_post | Termination |
| `usinv`, `suinv`, `globorg`, `regorg` | ex_post | Third-party involvement |

## Consequences

* The forecasting model (`models/`) uses **no ICB variables at all** as features; ICB only
  supplies the label (onset within 30 days) and the demo's ground truth.
* The schema retriever (`retrieval/es_schema.py`) filters/boosts on `region`,
  `pre_onset.*` and `at_onset.*` only.
* The vector retriever embeds the 90-day GDELT run-up only (no ICB fields).
* `ex_post.*` fields are stored in `signal_icb_cases` for display (analog outcome distribution)
  and are excluded from `_source` filtering in score-relevant paths; `retrieval/eval.py` asserts
  that no `ex_post` key appears in any query body.
