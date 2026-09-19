"""FaissVectorRetriever, EsVectorRetriever, EsSchemaRetriever, EsHybridRetriever.

All retrievers enforce end_date < query_date.  For the ES vector retriever the date filter is
inside the knn clause (pre-filtering), so top-k is computed only over eligible cases.
Ex-post fields are never part of any query body (asserted in retrieval/eval.py).
"""
from __future__ import annotations

import json
import os
from datetime import date
from typing import Dict, List, Optional

import numpy as np

from retrieval.base import (SCHEMA_FIELDS_AT, SCHEMA_FIELDS_PRE, Analog, CaseQuery, Retriever,
                            dedupe_by_crisno, rrf_fuse)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASES = os.path.join(ROOT, "data", "artifacts", "cases.jsonl")


def load_cases(path=CASES) -> List[dict]:
    with open(path) as f:
        return [json.loads(l) for l in f]


def _analog(doc: dict, score: float, source: str) -> Analog:
    return Analog(case_id=doc["case_id"], crisno=doc["crisno"], name=doc["name"], region=doc.get("region") or "",
                  macro_region=doc.get("macro_region") or "", actors=doc.get("actors") or [], dyad=doc.get("dyad"),
                  onset_date=date.fromisoformat(doc["onset_date"]), end_date=date.fromisoformat(doc["end_date"]),
                  score=float(score), source=source, pre_onset=doc.get("pre_onset") or {},
                  at_onset=doc.get("at_onset") or {}, ex_post=doc.get("ex_post") or {},
                  runup_summary=doc.get("runup_summary") or {})


# ----------------------------------------------------------------------------- FAISS / local
class FaissVectorRetriever:
    name = "faiss_vector"

    def __init__(self, cases: Optional[List[dict]] = None):
        import faiss
        self.cases = [c for c in (cases or load_cases()) if c.get("runup_vector")]
        X = np.array([c["runup_vector"] for c in self.cases], dtype=np.float32)
        faiss.normalize_L2(X)
        self.index = faiss.IndexFlatIP(X.shape[1])
        self.index.add(X)
        self.end_dates = np.array([date.fromisoformat(c["end_date"]).toordinal() for c in self.cases])

    def retrieve(self, q: CaseQuery, k: int = 5) -> List[Analog]:
        import faiss
        v = np.asarray(q.vector, dtype=np.float32).reshape(1, -1).copy()
        faiss.normalize_L2(v)
        # date filter inside the search (like the ES knn.filter) so future cases never consume the candidate budget
        eligible = np.flatnonzero(self.end_dates < q.query_date.toordinal()).astype(np.int64)
        if q.exclude_crisno is not None:
            eligible = np.array([i for i in eligible if self.cases[i]["crisno"] != q.exclude_crisno], dtype=np.int64)
        if len(eligible) == 0:
            return []
        n = min(len(eligible), max(k * 20, 100))
        params = faiss.SearchParameters(sel=faiss.IDSelectorBatch(eligible))
        scores, idx = self.index.search(v, n, params=params)
        out = [_analog(self.cases[i], s, "vector") for s, i in zip(scores[0], idx[0]) if i >= 0]
        return dedupe_by_crisno(out, k)


class LocalSchemaRetriever:
    """Pure-python fallback for the schema retriever (same scoring as EsSchemaRetriever)."""
    name = "local_schema"

    def __init__(self, weights: Dict[str, Dict[str, float]], cases: Optional[List[dict]] = None):
        self.cases = cases or load_cases()
        self.w = {**weights.get("pre_onset", {}), **weights.get("at_onset", {})}

    def retrieve(self, q: CaseQuery, k: int = 5) -> List[Analog]:
        out = []
        for c in self.cases:
            if date.fromisoformat(c["end_date"]) >= q.query_date:
                continue
            if q.exclude_crisno is not None and c["crisno"] == q.exclude_crisno:
                continue
            s = 0.0
            for f, w in self.w.items():
                qv = q.schema.get(f)
                if qv is None:
                    continue
                cv = c["pre_onset"].get(f) if f in c["pre_onset"] else c["at_onset"].get(f)
                if cv is not None and cv == qv:
                    s += w
            if q.macro_region and c.get("macro_region") == q.macro_region:
                s += 1.0
            if s > 0:
                out.append(_analog(c, s, "schema"))
        out.sort(key=lambda a: (-a.score, -a.onset_date.toordinal()))
        return dedupe_by_crisno(out, k)


# ----------------------------------------------------------------------------- Elasticsearch
def es_client():
    from elasticsearch import Elasticsearch
    url, key = os.environ.get("ES_URL"), os.environ.get("ES_API_KEY")
    if not url or not key:
        raise RuntimeError("ES_URL / ES_API_KEY not set")
    return Elasticsearch(url, api_key=key, request_timeout=30)


class EsVectorRetriever:
    name = "es_vector"

    def __init__(self, es, index: str, num_candidates: int = 200):
        self.es, self.index, self.num_candidates = es, index, num_candidates

    def _filter(self, q: CaseQuery):
        f = [{"range": {"end_date": {"lt": q.query_date.isoformat()}}}]
        if q.exclude_crisno is not None:
            f.append({"bool": {"must_not": {"term": {"crisno": q.exclude_crisno}}}})
        return f

    def retrieve(self, q: CaseQuery, k: int = 5) -> List[Analog]:
        body = {
            "knn": {"field": "runup_vector", "query_vector": [float(x) for x in q.vector],
                    "k": k * 4, "num_candidates": max(self.num_candidates, k * 4),
                    "filter": self._filter(q)},           # date filter INSIDE knn = pre-filter
            "size": k * 4, "_source": {"excludes": ["runup_vector"]},
        }
        r = self.es.search(index=self.index, body=body)
        return dedupe_by_crisno([_analog(h["_source"], h["_score"], "vector") for h in r["hits"]["hits"]], k)


class EsSchemaRetriever:
    name = "es_schema"

    def __init__(self, es, index: str, weights: Dict[str, Dict[str, float]]):
        self.es, self.index = es, index
        self.weights = weights

    def build_query(self, q: CaseQuery, k: int):
        should = []
        for tier, fields in (("pre_onset", SCHEMA_FIELDS_PRE), ("at_onset", SCHEMA_FIELDS_AT)):
            for f in fields:
                v = q.schema.get(f)
                w = self.weights.get(tier, {}).get(f)
                if v is None or not w:
                    continue
                should.append({"term": {f"{tier}.{f}": {"value": v, "boost": w}}})
        if q.macro_region:
            should.append({"term": {"macro_region": {"value": q.macro_region, "boost": 1.0}}})
        filt = [{"range": {"end_date": {"lt": q.query_date.isoformat()}}}]
        if q.exclude_crisno is not None:
            filt.append({"bool": {"must_not": {"term": {"crisno": q.exclude_crisno}}}})
        return {"query": {"bool": {"should": should, "minimum_should_match": 1, "filter": filt}},
                "size": k * 4, "_source": {"excludes": ["runup_vector"]},
                "sort": ["_score", {"onset_date": "desc"}]}

    def retrieve(self, q: CaseQuery, k: int = 5) -> List[Analog]:
        r = self.es.search(index=self.index, body=self.build_query(q, k))
        return dedupe_by_crisno([_analog(h["_source"], h["_score"] or 0.0, "schema") for h in r["hits"]["hits"]], k)


class EsHybridRetriever:
    name = "es_hybrid"

    def __init__(self, vec: Retriever, schema: Retriever, rrf_k: int = 60):
        self.vec, self.schema, self.rrf_k = vec, schema, rrf_k

    def retrieve(self, q: CaseQuery, k: int = 5) -> List[Analog]:
        rankings = []
        if q.vector is not None:
            rankings.append(self.vec.retrieve(q, k * 2))
        if q.schema or q.macro_region:
            rankings.append(self.schema.retrieve(q, k * 2))
        return rrf_fuse(rankings, self.rrf_k, k)
