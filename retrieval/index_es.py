"""Create the signal_icb_cases index and bulk-load data/artifacts/cases.jsonl."""
import argparse
import os

import yaml
from elasticsearch.helpers import bulk

from retrieval.retrievers import es_client, load_cases
from retrieval.vectors import DIM

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = yaml.safe_load(open(os.path.join(ROOT, "config.yaml")))
INDEX = CFG["elasticsearch"]["cases_index"]
assert INDEX.startswith("signal_")

MAPPING = {
    "mappings": {
        "dynamic": False,
        "properties": {
            "case_id": {"type": "keyword"}, "crisno": {"type": "integer"},
            "name": {"type": "text", "fields": {"kw": {"type": "keyword"}}},
            "region": {"type": "keyword"}, "macro_region": {"type": "keyword"},
            "actors": {"type": "keyword"}, "dyad": {"type": "keyword"},
            "onset_date": {"type": "date"}, "end_date": {"type": "date"}, "onset_year": {"type": "integer"},
            "pre_onset": {"properties": {
                "geog": {"type": "integer"}, "powdissy": {"type": "integer"}, "gpinv": {"type": "integer"},
                "powinv": {"type": "integer"}, "protrac": {"type": "integer"}, "pcid": {"type": "integer"},
                "ethnic": {"type": "integer"}, "syslevsy": {"type": "integer"}, "noactr": {"type": "integer"},
                "regime_pair": {"type": "keyword"}, "nuclear_max": {"type": "integer"},
                "powsta_max": {"type": "integer"}, "period": {"type": "integer"}}},
            "at_onset": {"properties": {
                "trigent_type": {"type": "keyword"}, "break": {"type": "integer"}, "gravcr": {"type": "integer"},
                "gravcr_label": {"type": "keyword"}, "issues": {"type": "integer"}, "issue_mode": {"type": "integer"}}},
            # ex_post: stored + returned, never queried (index: false)
            "ex_post": {"type": "object", "enabled": False},
            "runup_summary": {"type": "object", "enabled": False},
            "runup_vector": {"type": "dense_vector", "dims": DIM, "index": True, "similarity": "cosine"},
        }
    }
}


def main(recreate=True):
    es = es_client()
    if recreate and es.indices.exists(index=INDEX):
        es.indices.delete(index=INDEX)
    if not es.indices.exists(index=INDEX):
        es.indices.create(index=INDEX, **MAPPING)
    cases = load_cases()
    actions = []
    for c in cases:
        doc = dict(c)
        if doc.get("runup_vector") is None:
            doc.pop("runup_vector", None)
        actions.append({"_index": INDEX, "_id": doc["case_id"], "_source": doc})
    ok, _ = bulk(es, actions, refresh="wait_for", request_timeout=120)
    n = es.count(index=INDEX)["count"]
    print(f"indexed {ok} docs into {INDEX}; count={n}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-recreate", action="store_true")
    a = ap.parse_args()
    main(recreate=not a.no_recreate)
