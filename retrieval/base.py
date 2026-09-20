"""Common interface for historical-analog retrievers."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Protocol

import numpy as np

# fields the schema retriever is allowed to score on (tiers pre_onset / at_onset only)
SCHEMA_FIELDS_PRE = ["geog", "powdissy", "gpinv", "powinv", "protrac", "pcid", "ethnic",
                     "syslevsy", "noactr", "regime_pair", "nuclear_max", "powsta_max"]
SCHEMA_FIELDS_AT = ["trigent_type", "gravcr", "issues"]


@dataclass
class CaseQuery:
    query_date: date                     # only cases with end_date < query_date may be returned
    vector: Optional[np.ndarray] = None  # 90-day GDELT run-up embedding (data <= query_date only)
    dyad: Optional[str] = None
    macro_region: Optional[str] = None
    schema: Dict[str, object] = field(default_factory=dict)  # pre_onset/at_onset values only
    exclude_crisno: Optional[int] = None


@dataclass
class Analog:
    case_id: str
    crisno: int
    name: str
    region: str
    macro_region: str
    actors: List[str]
    dyad: Optional[str]
    onset_date: date
    end_date: date
    score: float
    source: str                          # vector | schema | hybrid
    pre_onset: Dict[str, object] = field(default_factory=dict)
    at_onset: Dict[str, object] = field(default_factory=dict)
    ex_post: Dict[str, object] = field(default_factory=dict)   # display only
    runup_summary: Dict[str, float] = field(default_factory=dict)

    def to_dict(self):
        d = self.__dict__.copy()
        d["onset_date"] = str(self.onset_date)
        d["end_date"] = str(self.end_date)
        return d


class Retriever(Protocol):
    name: str

    def retrieve(self, q: CaseQuery, k: int = 5) -> List[Analog]: ...


def outcome_distribution(analogs: List[Analog]) -> Dict[str, Dict[str, float]]:
    """Distribution of ex-post outcome labels over the returned cases (display only)."""
    out = {}
    for key in ("sevviosy_label", "outesr_label", "crismg_label", "viol_label"):
        vals = [a.ex_post.get(key) for a in analogs if a.ex_post.get(key)]
        if not vals:
            continue
        tot = len(vals)
        dist = {}
        for v in vals:
            dist[v] = dist.get(v, 0) + 1
        out[key] = {k: round(v / tot, 3) for k, v in sorted(dist.items(), key=lambda x: -x[1])}
    return out


def rrf_fuse(rankings: List[List[Analog]], k_const: int = 60, k: int = 5) -> List[Analog]:
    """Client-side reciprocal-rank fusion; de-duplicates by crisno."""
    scores: Dict[int, float] = {}
    best: Dict[int, Analog] = {}
    for ranking in rankings:
        for rank, a in enumerate(ranking):
            scores[a.crisno] = scores.get(a.crisno, 0.0) + 1.0 / (k_const + rank + 1)
            if a.crisno not in best:
                best[a.crisno] = a
    fused = []
    for crisno, s in sorted(scores.items(), key=lambda x: -x[1])[:k]:
        a = best[crisno]
        fused.append(Analog(**{**a.__dict__, "score": round(s, 5), "source": "hybrid"}))
    return fused


def dedupe_by_crisno(analogs: List[Analog], k: int) -> List[Analog]:
    seen, out = set(), []
    for a in analogs:
        if a.crisno in seen:
            continue
        seen.add(a.crisno)
        out.append(a)
        if len(out) >= k:
            break
    return out
