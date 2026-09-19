"""Head-to-head retrieval evaluation: vector vs schema vs hybrid (ES) and FAISS fallback.

For every case with onset >= eval_start we query with only pre-onset information available the day
before onset (its run-up vector + pre_onset/at_onset schema fields), restricted to cases that ended
before that date, excluding the case itself.  We measure whether the retrieved analogs' ex-post
outcomes agree with the true (held-out) outcome of the query case:

  * violence_acc : majority vote of analogs' sevviosy (severity of violence) == truth
  * violence_mae : mean |analog sevviosy - truth| (ordinal 1-4)
  * outcome_acc  : majority vote of analogs' outesr (form of outcome) == truth
  * region_hit@k : fraction of analogs in the same macro region
  * latency_ms   : median query latency

Also asserts the invariants: every returned end_date < query_date and no ex_post field in any query body.
"""
import argparse
import json
import os
import statistics
import time
from collections import Counter
from datetime import date, timedelta

import yaml

from retrieval.base import SCHEMA_FIELDS_AT, SCHEMA_FIELDS_PRE, CaseQuery
from retrieval.retrievers import (EsHybridRetriever, EsSchemaRetriever, EsVectorRetriever, FaissVectorRetriever,
                                  LocalSchemaRetriever, es_client, load_cases)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = yaml.safe_load(open(os.path.join(ROOT, "config.yaml")))
WEIGHTS = CFG["retrieval"]["schema_weights"]
EX_POST_KEYS = {"crismg", "sevviosy", "viol", "outesr", "forout", "outcom", "duration", "ex_post"}


def query_for(case):
    schema = {f: case["pre_onset"].get(f) for f in SCHEMA_FIELDS_PRE if case["pre_onset"].get(f) is not None}
    schema.update({f: case["at_onset"].get(f) for f in SCHEMA_FIELDS_AT if case["at_onset"].get(f) is not None})
    return CaseQuery(query_date=date.fromisoformat(case["onset_date"]) - timedelta(days=1),
                     vector=case.get("runup_vector"), dyad=case.get("dyad"), macro_region=case.get("macro_region"),
                     schema=schema, exclude_crisno=case["crisno"])


def _field_names(obj, acc=None):
    acc = set() if acc is None else acc
    if isinstance(obj, dict):
        for k, v in obj.items():
            acc.add(k.lower())
            _field_names(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _field_names(v, acc)
    return acc


def _no_ex_post(obj):
    names = _field_names(obj)
    return not any(any(k in n for k in EX_POST_KEYS) for n in names)


def evaluate(retriever, cases, k=5):
    agg = Counter()
    lat, mae = [], []
    n = 0
    for c in cases:
        q = query_for(c)
        if q.vector is None and retriever.name.endswith("vector"):
            continue
        t0 = time.perf_counter()
        res = retriever.retrieve(q, k)
        lat.append((time.perf_counter() - t0) * 1000)
        if not res:
            agg["empty"] += 1
            continue
        for a in res:
            assert a.end_date < q.query_date, (retriever.name, a.case_id, a.end_date, q.query_date)
            assert a.crisno != c["crisno"]
        n += 1
        truth_v, truth_o = c["ex_post"].get("sevviosy"), c["ex_post"].get("outesr")
        vs = [a.ex_post.get("sevviosy") for a in res if a.ex_post.get("sevviosy") is not None]
        os_ = [a.ex_post.get("outesr") for a in res if a.ex_post.get("outesr") is not None]
        if vs and truth_v is not None:
            agg["violence_acc"] += Counter(vs).most_common(1)[0][0] == truth_v
            mae.append(statistics.mean(abs(v - truth_v) for v in vs))
            agg["violence_n"] += 1
        if os_ and truth_o is not None:
            agg["outcome_acc"] += Counter(os_).most_common(1)[0][0] == truth_o
            agg["outcome_n"] += 1
        agg["region_hits"] += sum(a.macro_region == c["macro_region"] for a in res)
        agg["region_total"] += len(res)
    return {"retriever": retriever.name, "n_queries": n, "empty": agg["empty"],
            "violence_acc": round(agg["violence_acc"] / max(agg["violence_n"], 1), 3),
            "violence_mae": round(statistics.mean(mae), 3) if mae else None,
            "outcome_acc": round(agg["outcome_acc"] / max(agg["outcome_n"], 1), 3),
            f"region_hit@{k}": round(agg["region_hits"] / max(agg["region_total"], 1), 3),
            "latency_ms_p50": round(statistics.median(lat), 1) if lat else None}


def baseline(cases, k=5):
    """Chance-level reference: predict the most common outcome among all earlier cases."""
    allc = sorted(load_cases(), key=lambda c: c["onset_date"])
    hits_v = hits_o = n_v = n_o = 0
    for c in cases:
        prior = [p for p in allc if p["end_date"] < c["onset_date"] and p["crisno"] != c["crisno"]]
        vs = [p["ex_post"]["sevviosy"] for p in prior if p["ex_post"].get("sevviosy") is not None]
        os_ = [p["ex_post"]["outesr"] for p in prior if p["ex_post"].get("outesr") is not None]
        if vs and c["ex_post"].get("sevviosy") is not None:
            hits_v += Counter(vs).most_common(1)[0][0] == c["ex_post"]["sevviosy"]; n_v += 1
        if os_ and c["ex_post"].get("outesr") is not None:
            hits_o += Counter(os_).most_common(1)[0][0] == c["ex_post"]["outesr"]; n_o += 1
    return {"retriever": "majority_prior_baseline", "n_queries": len(cases), "empty": 0,
            "violence_acc": round(hits_v / max(n_v, 1), 3), "violence_mae": None,
            "outcome_acc": round(hits_o / max(n_o, 1), 3), f"region_hit@{k}": None, "latency_ms_p50": None}


def main(eval_start="1995-01-01", k=5, use_es=True, out=os.path.join(ROOT, "docs", "retrieval_eval.md")):
    cases = load_cases()
    seen, held = set(), []
    for c in sorted(cases, key=lambda c: c["onset_date"]):
        if c["onset_date"] >= eval_start and c.get("runup_vector") and c["crisno"] not in seen:
            held.append(c); seen.add(c["crisno"])
    print(f"held-out query cases: {len(held)} (onset >= {eval_start}, with run-up vector)")
    rows = [baseline(held, k)]
    faiss_r = FaissVectorRetriever(cases)
    local_s = LocalSchemaRetriever(WEIGHTS, cases)
    rows.append(evaluate(faiss_r, held, k))
    rows.append(evaluate(local_s, held, k))
    rows.append(evaluate(EsHybridRetriever(faiss_r, local_s), held, k) | {"retriever": "local_hybrid"})
    if use_es:
        es = es_client()
        idx = CFG["elasticsearch"]["cases_index"]
        ev = EsVectorRetriever(es, idx)
        es_s = EsSchemaRetriever(es, idx, WEIGHTS)
        # invariant: no ex-post field names appear in the query bodies
        assert _no_ex_post(es_s.build_query(query_for(held[0]), k))
        rows.append(evaluate(ev, held, k))
        rows.append(evaluate(es_s, held, k))
        rows.append(evaluate(EsHybridRetriever(ev, es_s), held, k))
    hdr = list(rows[0].keys())
    md = ["# Retrieval head-to-head", "", f"Held-out queries: crises with onset >= {eval_start} that have a GDELT run-up vector "
          f"(n={len(held)}), each queried with pre-onset info only, k={k}, candidates restricted to cases with `end_date < query_date`.",
          "", "| " + " | ".join(hdr) + " |", "|" + "---|" * len(hdr)]
    for r in rows:
        md.append("| " + " | ".join("" if r[h] is None else str(r[h]) for h in hdr) + " |")
    md += ["", "`violence_acc`/`outcome_acc`: majority vote of the analogs' *ex-post* ICB outcome (severity of violence; form of outcome) "
           "vs the held-out truth.  `majority_prior_baseline` predicts the modal outcome of all earlier crises.", "",
           "Invariants checked at run time: every returned analog has `end_date < query_date`; the case itself is excluded; "
           "no ex-post field name appears in any query body."]
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w").write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-start", default="1995-01-01")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--no-es", action="store_true")
    a = ap.parse_args()
    main(a.eval_start, a.k, not a.no_es)
