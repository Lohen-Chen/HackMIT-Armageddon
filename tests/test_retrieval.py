"""Unit tests for retrieval helpers, local/ES schema alignment, Wilson intervals and feature labels."""
import json
import os
import sys
from datetime import date

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.api.labels import feature_label  # noqa: E402
from models.score import wilson  # noqa: E402
from retrieval.base import (SCHEMA_FIELDS_AT, SCHEMA_FIELDS_PRE, Analog, CaseQuery,  # noqa: E402
                            dedupe_by_crisno, rrf_fuse)
from retrieval.retrievers import EsSchemaRetriever, LocalSchemaRetriever  # noqa: E402

CFG = yaml.safe_load(open(os.path.join(ROOT, "config.yaml")))
WEIGHTS = CFG["retrieval"]["schema_weights"]
CASES = os.path.join(ROOT, "data", "artifacts", "cases.jsonl")


def _doc_tiers() -> dict:
    """{field: tier} as laid out in real case documents (build_cases.py); falls back to the index mapping."""
    if os.path.exists(CASES):
        with open(CASES) as f:
            doc = json.loads(f.readline())
        return {**{k: "pre_onset" for k in doc["pre_onset"]}, **{k: "at_onset" for k in doc["at_onset"]}}
    from retrieval.index_es import MAPPING
    props = MAPPING["mappings"]["properties"]
    return {**{k: "pre_onset" for k in props["pre_onset"]["properties"]},
            **{k: "at_onset" for k in props["at_onset"]["properties"]}}


def _analog(crisno, score=1.0, source="vector"):
    return Analog(case_id=f"{crisno}_A_B", crisno=crisno, name=f"case {crisno}", region="r", macro_region="m",
                  actors=["A", "B"], dyad="A_B", onset_date=date(2000, 1, 1), end_date=date(2000, 2, 1),
                  score=score, source=source)


# ----------------------------------------------------------------------------- rrf_fuse
def test_rrf_fuse_shared_case_ranks_first_and_is_hybrid():
    vec = [_analog(1), _analog(2), _analog(3)]
    sch = [_analog(4, source="schema"), _analog(2, source="schema"), _analog(5, source="schema")]
    fused = rrf_fuse([vec, sch], k_const=60, k=3)
    assert [a.crisno for a in fused][0] == 2          # only case present in both rankings
    assert len(fused) <= 3
    assert all(a.source == "hybrid" for a in fused)
    assert len({a.crisno for a in fused}) == len(fused)


def test_rrf_fuse_respects_k():
    vec = [_analog(i) for i in range(10)]
    assert len(rrf_fuse([vec, vec[::-1]], k=4)) == 4
    assert rrf_fuse([], k=4) == []


# ----------------------------------------------------------------------------- dedupe_by_crisno
def test_dedupe_by_crisno_collapses_duplicates_preserving_order():
    ranked = [_analog(7, 0.9), _analog(3, 0.8), _analog(7, 0.7), _analog(9, 0.6), _analog(3, 0.5)]
    out = dedupe_by_crisno(ranked, k=10)
    assert [a.crisno for a in out] == [7, 3, 9]
    assert [a.score for a in out] == [0.9, 0.8, 0.6]     # first occurrence wins


def test_dedupe_by_crisno_truncates_to_k():
    ranked = [_analog(i) for i in range(6)]
    assert [a.crisno for a in dedupe_by_crisno(ranked, k=2)] == [0, 1]


# ----------------------------------------------------------------------------- local vs ES schema
def _es_terms(body):
    should = body["query"]["bool"]["should"]
    return {(list(t["term"])[0], list(t["term"].values())[0]["boost"]) for t in should}


def test_schema_field_lists_match_config_weights():
    assert set(WEIGHTS["pre_onset"]) <= set(SCHEMA_FIELDS_PRE)
    assert set(WEIGHTS["at_onset"]) <= set(SCHEMA_FIELDS_AT)
    assert not (set(SCHEMA_FIELDS_PRE) & set(SCHEMA_FIELDS_AT))


def test_local_and_es_schema_score_the_same_fields():
    """Every ES `should` term (tier.field, boost) must be a field the local retriever scores with the same
    weight, stored under that tier in real case documents, and the sum of boosts must equal the local
    score of a case matching on every weighted field."""
    tiers = _doc_tiers()
    weighted = {**WEIGHTS["pre_onset"], **WEIGHTS["at_onset"]}
    values = {f: (f"v{i}" if f in ("regime_pair", "trigent_type") else i + 1) for i, f in enumerate(sorted(weighted))}
    pre = {f: v for f, v in values.items() if tiers.get(f) == "pre_onset"}
    at = {f: v for f, v in values.items() if tiers.get(f) == "at_onset"}
    assert set(pre) | set(at) == set(values), "weighted field missing from case documents"
    case = {"case_id": "1_X_Y", "crisno": 1, "name": "match", "region": "r", "macro_region": "Europe",
            "actors": ["X", "Y"], "dyad": "X_Y", "onset_date": "1990-01-01", "end_date": "1990-06-01",
            "pre_onset": pre, "at_onset": at, "ex_post": {}, "runup_summary": {}}
    other = {**case, "case_id": "2_P_Q", "crisno": 2, "name": "other", "macro_region": "Asia",
             "pre_onset": {f: "none" for f in pre}, "at_onset": {f: "none" for f in at}}
    q = CaseQuery(query_date=date(2000, 1, 1), schema=values, macro_region="Europe")

    body = EsSchemaRetriever(es=None, index="x", weights=WEIGHTS).build_query(q, k=5)
    es_terms = _es_terms(body)
    region_terms = {t for t in es_terms if t[0] == "macro_region"}
    assert region_terms == {("macro_region", 1.0)}
    field_terms = es_terms - region_terms

    local = LocalSchemaRetriever(WEIGHTS, cases=[case, other])
    local_fields = {(f, w) for f, w in local.w.items() if q.schema.get(f) is not None}
    # ES paths are "<tier>.<field>"; the tier must be the one the case document actually stores the field in
    es_fields = set()
    for path, boost in field_terms:
        tier, f = path.split(".", 1)
        assert tiers.get(f) == tier, f"{path} queried but case documents store {f} under {tiers.get(f)}"
        es_fields.add((f, boost))
    assert es_fields == local_fields == set(weighted.items())

    hits = local.retrieve(q, k=5)
    assert [a.crisno for a in hits] == [1]                     # `other` matches nothing -> not returned
    assert abs(hits[0].score - (sum(b for _, b in es_terms))) < 1e-9


def test_es_query_filters_on_query_date_and_excluded_crisno():
    q = CaseQuery(query_date=date(2001, 2, 3), schema={"geog": 1}, exclude_crisno=42)
    body = EsSchemaRetriever(es=None, index="x", weights=WEIGHTS).build_query(q, k=3)
    filt = body["query"]["bool"]["filter"]
    assert {"range": {"end_date": {"lt": "2001-02-03"}}} in filt
    assert {"bool": {"must_not": {"term": {"crisno": 42}}}} in filt
    assert body["size"] == 12


# ----------------------------------------------------------------------------- wilson
def test_wilson_empty_is_full_interval():
    assert wilson(0, 0) == (0.0, 1.0)


def test_wilson_brackets_point_estimate_and_narrows_with_n():
    lo, hi = wilson(5, 10)
    assert lo < 0.5 < hi
    lo2, hi2 = wilson(1, 2)
    assert lo2 < 0.5 < hi2
    assert (hi - lo) < (hi2 - lo2)
    assert 0.0 <= lo and hi <= 1.0


# ----------------------------------------------------------------------------- feature labels
def test_feature_label_cameo_root_windows():
    assert feature_label("r19_share_w4") == "share of fighting (events), last 4 wks"
    assert feature_label("m13_w13") == "threats (mentions), last 13 wks"
    assert feature_label("r10_w1") == "demands (events), last week"


def test_feature_label_base_and_unknown():
    assert feature_label("n_events_w4") == "event volume, last 4 wks"
    assert feature_label("icb_prior_crises") == "prior ICB crises (this dyad)"
    assert feature_label("some_new_thing") == "some new thing"
