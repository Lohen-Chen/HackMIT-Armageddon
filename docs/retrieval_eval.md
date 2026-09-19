# Retrieval head-to-head

Held-out queries: crises with onset >= 1995-01-01 that have a GDELT run-up vector (n=96), each queried with pre-onset info only, k=5, candidates restricted to cases with `end_date < query_date`.

| retriever | n_queries | empty | violence_acc | violence_mae | outcome_acc | region_hit@5 | latency_ms_p50 |
|---|---|---|---|---|---|---|---|
| majority_prior_baseline | 96 | 0 | 0.167 |  | 0.448 |  |  |
| faiss_vector | 96 | 0 | 0.365 | 0.958 | 0.49 | 0.369 | 0.3 |
| local_schema | 96 | 0 | 0.406 | 0.887 | 0.469 | 0.917 | 3.6 |
| local_hybrid | 96 | 0 | 0.469 | 0.875 | 0.448 | 0.613 | 4.3 |
| es_vector | 96 | 0 | 0.333 | 0.983 | 0.479 | 0.362 | 60.6 |
| es_schema | 96 | 0 | 0.396 | 0.951 | 0.521 | 0.824 | 60.3 |
| es_hybrid | 96 | 0 | 0.49 | 0.942 | 0.542 | 0.579 | 122.1 |

`violence_acc`/`outcome_acc`: majority vote of the analogs' *ex-post* ICB outcome (severity of violence; form of outcome) vs the held-out truth.  `majority_prior_baseline` predicts the modal outcome of all earlier crises.

Invariants checked at run time: every returned analog has `end_date < query_date`; the case itself is excluded; no ex-post field name appears in any query body.
