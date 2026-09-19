# Retrieval head-to-head

Held-out queries: crises with onset >= 1995-01-01 that have a GDELT run-up vector (n=97), each queried with pre-onset info only, k=5, candidates restricted to cases with `end_date < query_date`.

| retriever | n_queries | empty | violence_acc | violence_mae | outcome_acc | region_hit@5 | latency_ms_p50 |
|---|---|---|---|---|---|---|---|
| majority_prior_baseline | 97 | 0 | 0.167 |  | 0.448 |  |  |
| faiss_vector | 97 | 0 | 0.365 | 0.956 | 0.49 | 0.363 | 0.2 |
| local_schema | 96 | 1 | 0.406 | 0.887 | 0.469 | 0.917 | 3.6 |
| local_hybrid | 97 | 0 | 0.458 | 0.875 | 0.448 | 0.606 | 4.2 |
| es_vector | 97 | 0 | 0.344 | 0.981 | 0.479 | 0.363 | 61.9 |
| es_schema | 96 | 1 | 0.396 | 0.951 | 0.521 | 0.824 | 61.2 |
| es_hybrid | 97 | 0 | 0.49 | 0.942 | 0.542 | 0.569 | 123.7 |

`violence_acc`/`outcome_acc`: majority vote of the analogs' *ex-post* ICB outcome (severity of violence; form of outcome) vs the held-out truth.  `majority_prior_baseline` predicts the modal outcome of all earlier crises.

Invariants checked at run time: every returned analog has `end_date < query_date`; the case itself is excluded; no ex-post field name appears in any query body.
