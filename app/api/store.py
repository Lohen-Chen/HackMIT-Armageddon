"""Data access for the demo API.

Everything the browser sees comes through here; Elasticsearch is only ever called server-side and
every retrieval falls back to local FAISS / pure-python schema search when ES is unavailable.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from functools import wraps
from datetime import date, timedelta
from typing import Dict, List, Optional

import duckdb
import numpy as np
import pandas as pd
import yaml

from app.api.labels import feature_label
from retrieval.base import CaseQuery, outcome_distribution
from retrieval.retrievers import (EsHybridRetriever, EsSchemaRetriever, EsVectorRetriever,
                                  FaissVectorRetriever, LocalSchemaRetriever, es_client, load_cases)
from retrieval.vectors import _con as vec_con
from retrieval.vectors import load_scaler, runup_summary, runup_vector

log = logging.getLogger("signal.store")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
P = lambda *a: os.path.join(ROOT, *a)  # noqa: E731
DEMO = P("data", "artifacts", "demo")
# full-pipeline location -> compact git-tracked demo pack (scripts/pack_demo.py)
_DEMO_MAP = {"data/processed/panel": "panel", "data/processed/icb": "icb", "data/processed/markets": "markets",
             "data/artifacts/models": "models"}


def R(rel: str) -> str:
    """Resolve an artifact path: prefer the full pipeline output, fall back to the demo pack."""
    full = P(rel)
    if os.path.exists(full) and not os.environ.get("SIGNAL_DEMO_ONLY"):
        return full
    for src, dst in _DEMO_MAP.items():
        if rel.startswith(src):
            return os.path.join(DEMO, dst, rel[len(src):].lstrip("/"))
    return full

# boundary of the shipped y_icb final model (t < t_cut - gap, models/train.py) when train_meta.json is absent
FALLBACK_TRAIN_END = date(2018, 10, 26)


def _sunday_on_or_before(d: date) -> date:
    return d - timedelta(days=(d.weekday() + 1) % 7)


def _locked(fn):
    """DuckDB connections are not thread-safe; FastAPI runs sync endpoints in a threadpool."""
    @wraps(fn)
    def inner(self, *a, **kw):
        with self._lock:
            return fn(self, *a, **kw)
    return inner


class Store:
    def __init__(self):
        self._lock = threading.RLock()
        self.cfg = yaml.safe_load(open(P("config.yaml")))
        self.con = duckdb.connect()
        self.notes: List[str] = []
        self.icb_end = date.fromisoformat(str(self.cfg["labels"]["icb_last_complete_date"]))
        self._load_countries()
        self._load_forecasts()
        self._load_cases()
        self._load_model()
        self._load_retrieval()
        self._load_markets()

    # ------------------------------------------------------------------ loading
    def _load_countries(self):
        df = pd.read_csv(P("data/static/countries.csv"), dtype={"iso_num": str})
        self.countries = {r.iso3: {"iso3": r.iso3, "name": r.name, "iso_num": r.iso_num,
                                   "region": r.region if isinstance(r.region, str) else None,
                                   "subregion": r.subregion if isinstance(r.subregion, str) else None,
                                   "lat": None if pd.isna(r.lat) else float(r.lat),
                                   "lon": None if pd.isna(r.lon) else float(r.lon)}
                          for r in df.itertuples()}

    def _load_forecasts(self):
        self.labels = []
        for label in ("y_icb", "y_thresh"):
            f = R(f"data/artifacts/models/{label}/forecasts.parquet")
            if os.path.exists(f):
                self.con.execute(f"CREATE VIEW fc_{label} AS SELECT * FROM read_parquet('{f}')")
                self.labels.append(label)
            pr = R(f"data/artifacts/models/{label}/predictions.parquet")
            if os.path.exists(pr):
                self.con.execute(f"CREATE VIEW oos_{label} AS SELECT dyad, CAST(t AS DATE) AS t, p_cal AS p_oos, "
                                 f"p_persist, p_base, fold FROM read_parquet('{pr}')")
        if not self.labels:
            raise RuntimeError("no forecasts.parquet found; run models/score.py")
        lo, hi = self.con.execute("SELECT min(t), max(t) FROM fc_y_icb").fetchone()
        self.t_min, self.t_max = lo, hi
        self.metrics = {l: json.load(open(P("data/artifacts/models", l, "metrics.json"))) for l in self.labels}
        self.bands = {l: json.load(open(P("data/artifacts/models", l, "calibration_bands.json"))) for l in self.labels
                      if os.path.exists(P("data/artifacts/models", l, "calibration_bands.json"))}
        panel = R("data/processed/panel/panel_labelled.parquet")
        self.has_panel = os.path.exists(panel)
        self.demo_mode = panel.startswith(DEMO)
        if self.demo_mode:
            self.notes.append("running from the compact demo pack: feature drivers/replay events cover the top dyads only")
        if self.has_panel:
            self.con.execute(f"CREATE VIEW panel AS SELECT * FROM read_parquet('{panel}')")
        else:
            self.notes.append("panel_labelled.parquet not present: feature drivers use global importance only")
        dyads = self.con.execute("SELECT dyad, count(*) n, max(p_raw) mx FROM fc_y_icb GROUP BY dyad").df()
        self.dyads = {r.dyad: {"dyad": r.dyad, "weeks": int(r.n), "max_raw": float(r.mx)} for r in dyads.itertuples()}

    def _load_cases(self):
        self.cases = load_cases()
        self.by_crisno: Dict[int, dict] = {}
        self.onsets_by_dyad: Dict[str, List[dict]] = {}
        for c in self.cases:
            self.by_crisno.setdefault(c["crisno"], c)
            self.onsets_by_dyad.setdefault(c["dyad"], []).append(c)
        acts = pd.read_parquet(R("data/processed/icb/actors.parquet"))
        acts = acts[acts.iso3.notna()].sort_values("onset_date")
        self.actor_rows = {k: g for k, g in acts.groupby("iso3")}

    def _load_model(self):
        import lightgbm as lgb
        self.model, self.features, self.importance, self.train_end, self.cal_end = {}, {}, {}, {}, {}
        for label in self.labels:
            d = P("data/artifacts/models", label)
            self.model[label] = lgb.Booster(model_file=os.path.join(d, "final_model.txt"))
            self.features[label] = json.load(open(os.path.join(d, "features.json")))
            meta = os.path.join(d, "train_meta.json")
            if os.path.exists(meta):
                tm = json.load(open(meta))
                self.train_end[label] = date.fromisoformat(tm["final_train_end"])
                self.cal_end[label] = date.fromisoformat(tm.get("final_calibration_end", str(self.icb_end)))
            else:
                self.train_end[label], self.cal_end[label] = FALLBACK_TRAIN_END, self.icb_end
                self.notes.append(f"{label}: train_meta.json missing, trees_out_of_sample boundary is the fallback {FALLBACK_TRAIN_END}")
            shp = os.path.join(d, "shap_summary.csv")
            if os.path.exists(shp):
                s = pd.read_csv(shp)
                self.importance[label] = [{"feature": r.feature, "label": feature_label(r.feature),
                                           "mean_abs_shap": float(r.mean_abs_shap)} for r in s.head(15).itertuples()]

    def _load_retrieval(self):
        rc = self.cfg["retrieval"]
        self.scaler = load_scaler()
        self.vcon = vec_con(os.path.dirname(R("data/processed/panel/dyad_week.parquet")))
        self.faiss = FaissVectorRetriever(self.cases)
        self.local_schema = LocalSchemaRetriever(rc["schema_weights"], self.cases)
        self.es = None
        self.retrieval_mode = "local"
        try:
            es = es_client()
            idx = self.cfg["elasticsearch"]["cases_index"]
            if es.indices.exists(index=idx):
                n = es.count(index=idx)["count"]
                self.es = es
                self.es_vec = EsVectorRetriever(es, idx, rc["num_candidates"])
                self.es_schema = EsSchemaRetriever(es, idx, rc["schema_weights"])
                self.es_hybrid = EsHybridRetriever(self.es_vec, self.es_schema, rc["rrf_k"])
                self.retrieval_mode = "elasticsearch"
                log.info("Elasticsearch online: %s docs in %s", n, idx)
        except Exception as e:  # noqa: BLE001
            self.notes.append(f"Elasticsearch unavailable ({type(e).__name__}); using local FAISS + schema fallback")
            log.warning("ES unavailable: %s", e)
        self.local_hybrid = EsHybridRetriever(self.faiss, self.local_schema, rc["rrf_k"])

    def _load_markets(self):
        self.market_compare = None
        self.market_joined = None
        c = R("data/processed/markets/market_compare.json")
        j = R("data/processed/markets/market_model_joined.parquet")
        if os.path.exists(c) and os.path.exists(j):
            self.market_compare = json.load(open(c))
            self.market_joined = pd.read_parquet(j)

    # ------------------------------------------------------------------ helpers
    def cname(self, iso3: str) -> str:
        return self.countries.get(iso3, {}).get("name", iso3)

    def dyad_label(self, dyad: str) -> str:
        a, b = dyad.split("_")
        return f"{self.cname(a)} – {self.cname(b)}"

    def week(self, d: date) -> date:
        w = _sunday_on_or_before(d)
        return max(self.t_min, min(self.t_max, w))

    def _horizon_coded(self, t: date) -> bool:
        """True when the whole label horizon falls inside ICB coverage."""
        return t + timedelta(days=self.cfg["labels"]["horizon_days"]) <= self.icb_end

    def _sample_flags(self, t: date, label: str) -> dict:
        return {"trees_out_of_sample": t >= self.train_end[label], "calibration_out_of_sample": t > self.cal_end[label],
                "icb_label_available": self._horizon_coded(t)}

    def _boundaries(self, label: str = "y_icb") -> dict:
        return {"trees_train_end": str(self.train_end[label]), "calibration_end": str(self.cal_end[label]),
                "icb_complete_end": str(self.icb_end)}

    # ------------------------------------------------------------------ queries
    @_locked
    def meta(self) -> dict:
        heroes = []
        for h in self.cfg["demo"]["hero_dyads"]:
            a, b = sorted([h["a"], h["b"]])
            dy = f"{a}_{b}"
            heroes.append({"dyad": dy, "label": self.dyad_label(dy), "start": h["start"], "end": h["end"],
                           "crisis": h["crisis"], "macro_region": self._macro_region(dy)})
        top = sorted(self.dyads.values(), key=lambda x: -x["max_raw"])[:400]
        pooled = {l: self.metrics[l]["pooled"] for l in self.labels}
        return {"t_min": str(self.t_min), "t_max": str(self.t_max), "labels": self.labels,
                "heroes": heroes, "retrieval_mode": self.retrieval_mode, "notes": self.notes,
                "dyads": [{"dyad": d["dyad"], "label": self.dyad_label(d["dyad"])} for d in top],
                "countries": self.countries, "metrics": pooled, "importance": self.importance,
                "sample_boundaries": self._boundaries(),
                "sample_boundaries_by_label": {l: self._boundaries(l) for l in self.labels},
                "has_markets": self.market_joined is not None}

    @_locked
    def map_snapshot(self, d: date, label: str = "y_icb", top: int = 30) -> dict:
        t = self.week(d)
        df = self.con.execute(f"""
            SELECT dyad, p_raw, p_cal, p_lo, p_hi, in_crisis,
                   percent_rank() OVER (ORDER BY p_raw) AS pct
            FROM fc_{label} WHERE t = ?""", [t]).df()
        df = df.sort_values("p_raw", ascending=False)
        country = {}
        for r in df.itertuples():
            for cc in r.dyad.split("_"):
                cur = country.get(cc)
                if cur is None or r.p_raw > cur["p_raw"]:
                    country[cc] = {"p_raw": float(r.p_raw), "p_cal": float(r.p_cal), "dyad": r.dyad, "pct": float(r.pct)}
        rows = [{"dyad": r.dyad, "label": self.dyad_label(r.dyad), "p_raw": float(r.p_raw), "p_cal": float(r.p_cal),
                 "p_lo": float(r.p_lo), "p_hi": float(r.p_hi), "pct": float(r.pct), "in_crisis": bool(r.in_crisis)}
                for r in df.head(top).itertuples()]
        return {"t": str(t), "n_dyads": int(len(df)), "top": rows, "countries": country}

    @_locked
    def series(self, dyad: str, start: date, end: date, label: str = "y_icb") -> dict:
        if dyad not in self.dyads:
            return {"dyad": dyad, "points": [], "onsets": [], "error": "dyad not in panel"}
        has_oos = self.con.execute("SELECT count(*) FROM duckdb_views() WHERE view_name = ?", [f"oos_{label}"]).fetchone()[0] > 0
        oos_join = f"LEFT JOIN oos_{label} o USING (dyad, t)" if has_oos else ""
        oos_cols = "o.p_oos, o.p_persist," if has_oos else "NULL AS p_oos, NULL AS p_persist,"
        df = self.con.execute(f"""
            SELECT f.t, f.p_raw, f.p_cal, f.p_lo, f.p_hi, f.in_crisis, f.y, {oos_cols} 1 AS _one
            FROM fc_{label} f {oos_join}
            WHERE f.dyad = ? AND f.t BETWEEN ? AND ? ORDER BY f.t""", [dyad, start, end]).df()
        ev = self.vcon.execute("""
            SELECT t, n_events, q4, q3, goldstein_sum, tone_sum FROM dw WHERE dyad = ? AND t BETWEEN ? AND ? ORDER BY t""",
                               [dyad, start, end]).df()
        ev = ev.set_index("t")
        pts = []
        for r in df.itertuples():
            e = ev.loc[r.t] if r.t in ev.index else None
            pts.append({"t": str(pd.Timestamp(r.t).date()), "p_raw": float(r.p_raw), "p_cal": float(r.p_cal), "p_lo": float(r.p_lo),
                        "p_hi": float(r.p_hi), "in_crisis": bool(r.in_crisis),
                        "y": None if pd.isna(r.y) else int(r.y),
                        "p_oos": None if pd.isna(r.p_oos) else float(r.p_oos),
                        "n_events": 0 if e is None else int(e.n_events), "q4": 0 if e is None else int(e.q4),
                        "goldstein_mean": None if e is None or e.n_events == 0 else float(e.goldstein_sum / e.n_events)})
        onsets = [{"crisno": c["crisno"], "name": c["name"], "onset_date": c["onset_date"], "end_date": c["end_date"],
                   "viol_label": c["ex_post"].get("viol_label")}
                  for c in self.onsets_by_dyad.get(dyad, [])
                  if date.fromisoformat(c["onset_date"]) <= end and date.fromisoformat(c["end_date"]) >= start]
        return {"dyad": dyad, "label": self.dyad_label(dyad), "points": pts, "onsets": onsets,
                "sample_boundaries": self._boundaries(label)}

    @_locked
    def forecast(self, dyad: str, d: date, label: str = "y_icb", n_drivers: int = 8) -> dict:
        t = self.week(d)
        row = self.con.execute(f"""
            SELECT f.*, (SELECT count(*) FROM fc_{label} g WHERE g.t = f.t) AS n_week,
                   (SELECT count(*) FROM fc_{label} g WHERE g.t = f.t AND g.p_raw > f.p_raw) AS n_above
            FROM fc_{label} f WHERE f.dyad = ? AND f.t = ?""", [dyad, t]).df()
        if row.empty:
            return {"dyad": dyad, "t": str(t), "available": False,
                    "reason": "dyad not in the active universe this week (fewer than 200 events in trailing year)"}
        r = row.iloc[0]
        out = {"dyad": dyad, "label": self.dyad_label(dyad), "t": str(t), "available": True,
               "p_raw": float(r.p_raw), "p_cal": float(r.p_cal), "p_lo": float(r.p_lo), "p_hi": float(r.p_hi),
               "in_crisis": bool(r.in_crisis), "y": None if pd.isna(r.y) else int(r.y),
               "rank": int(r.n_above) + 1, "n_dyads": int(r.n_week), "flags": self._sample_flags(t, label)}
        out["drivers"] = self.drivers(dyad, t, label, n_drivers)
        out["current_crisis"] = next(({"crisno": c["crisno"], "name": c["name"], "onset_date": c["onset_date"],
                                       "end_date": c["end_date"]} for c in self.onsets_by_dyad.get(dyad, [])
                                      if date.fromisoformat(c["onset_date"]) <= t <= date.fromisoformat(c["end_date"])), None)
        h = timedelta(days=self.cfg["labels"]["horizon_days"])
        nxt = [c for c in self.onsets_by_dyad.get(dyad, []) if t < date.fromisoformat(c["onset_date"]) <= t + h]
        out["onset_within_30d"] = None if not self._horizon_coded(t) else (
            {"crisno": nxt[0]["crisno"], "name": nxt[0]["name"], "onset_date": nxt[0]["onset_date"]} if nxt else False)
        return out

    def drivers(self, dyad: str, t: date, label: str, n: int = 8) -> dict:
        feats = self.features[label]
        if not self.has_panel:
            return {"mode": "global", "items": self.importance.get(label, [])[:n]}
        row = self.con.execute("SELECT * FROM panel WHERE dyad = ? AND t = ?", [dyad, t]).df()
        if row.empty:
            return {"mode": "global", "items": self.importance.get(label, [])[:n]}
        X = row[feats].astype(float).to_numpy()
        contrib = self.model[label].predict(X, pred_contrib=True)[0]
        bias = float(contrib[-1])
        vals = contrib[:-1]
        order = np.argsort(-np.abs(vals))[:n]
        items = []
        for i in order:
            v = row[feats[i]].iloc[0]
            items.append({"feature": feats[i], "label": feature_label(feats[i]), "contribution": float(vals[i]),
                          "value": None if pd.isna(v) else float(v)})
        wk = self.vcon.execute("""SELECT t, n_events, q4, q3, goldstein_sum FROM dw
                                  WHERE dyad = ? AND t <= ? ORDER BY t DESC LIMIT 4""", [dyad, t]).df()
        recent = {"n_events_4w": int(wk.n_events.sum()), "q4_4w": int(wk.q4.sum()),
                  "goldstein_mean_4w": None if wk.n_events.sum() == 0 else float(wk.goldstein_sum.sum() / wk.n_events.sum())}
        return {"mode": "local", "bias_logodds": bias, "items": items, "recent": recent}

    # ------------------------------------------------------------------ retrieval
    def _macro_region(self, dyad: str) -> Optional[str]:
        from pipeline.icb_prepare import GEOG
        regions = []
        for cc in dyad.split("_"):
            g = self._latest_actor(cc)
            if g is not None and pd.notna(g.get("geog")):
                regions.append(GEOG.get(int(g["geog"]), (None, None))[1])
        if regions:
            return max(set(regions), key=regions.count)
        subs = [self.countries.get(cc, {}).get("region") for cc in dyad.split("_")]
        m = {"Asia": "Asia", "Europe": "Europe", "Africa": "Africa", "Americas": "Americas", "Oceania": "Asia"}
        for s in subs:
            if s in m:
                return m[s]
        return None

    def _latest_actor(self, cc: str, before: Optional[date] = None):
        g = self.actor_rows.get(cc)
        if g is None or g.empty:
            return None
        if before is not None:
            gg = g[g.onset_date < pd.Timestamp(before)]
            if not gg.empty:
                g = gg
        return g.iloc[-1]

    def live_schema(self, dyad: str, t: date) -> dict:
        """Pre-onset schema attributes inferable for a live dyad from *earlier* ICB actor records."""
        a, b = dyad.split("_")
        ra, rb = self._latest_actor(a, t), self._latest_actor(b, t)
        schema = {}
        geogs = [int(r["geog"]) for r in (ra, rb) if r is not None and pd.notna(r.get("geog"))]
        if geogs:
            schema["geog"] = max(set(geogs), key=geogs.count)
        nuc = [int(r["nuclear"]) for r in (ra, rb) if r is not None and pd.notna(r.get("nuclear"))]
        if nuc:
            schema["nuclear_max"] = max(nuc)
        pw = [int(r["powsta"]) for r in (ra, rb) if r is not None and pd.notna(r.get("powsta"))]
        if pw:
            schema["powsta_max"] = max(pw)
        reg = sorted({int(r["regime"]) for r in (ra, rb) if r is not None and pd.notna(r.get("regime"))})
        if reg:
            schema["regime_pair"] = "-".join(str(x) for x in reg)
        prior = [c for c in self.onsets_by_dyad.get(dyad, []) if date.fromisoformat(c["end_date"]) < t]
        schema["protrac"] = 2 if len(prior) >= 2 else 1
        if prior:
            pc = prior[-1]["pre_onset"].get("pcid")
            if pc is not None:
                schema["pcid"] = pc
        return schema

    @_locked
    def analogs(self, dyad: str, d: date, k: int = 5) -> dict:
        t = self.week(d)
        vec, fr = runup_vector(self.vcon, dyad, t, self.scaler)
        summary = runup_summary(fr)
        summary["weeks"] = [{"t": str(pd.Timestamp(x.t).date()), "log_events": float(x.log_events),
                             "q4_share": float(x.q4_share), "goldstein_mean": float(x.goldstein_mean)} for x in fr.itertuples()]
        if fr.log_events.sum() == 0:
            vec = None
        schema = self.live_schema(dyad, t)
        macro = self._macro_region(dyad)
        cur = next((c["crisno"] for c in self.onsets_by_dyad.get(dyad, [])
                    if date.fromisoformat(c["onset_date"]) <= t <= date.fromisoformat(c["end_date"])), None)
        q = CaseQuery(query_date=t, vector=vec, dyad=dyad, macro_region=macro, schema=schema, exclude_crisno=cur)
        source = self.retrieval_mode
        res = {}
        try:
            if self.es is not None:
                res["vector"] = self.es_vec.retrieve(q, k) if vec is not None else []
                res["schema"] = self.es_schema.retrieve(q, k)
                res["hybrid"] = self.es_hybrid.retrieve(q, k)
            else:
                raise RuntimeError("es offline")
        except Exception as e:  # noqa: BLE001
            if self.es is not None:
                log.warning("ES query failed, falling back to local: %s", e)
            source = "local"
            res["vector"] = self.faiss.retrieve(q, k) if vec is not None else []
            res["schema"] = self.local_schema.retrieve(q, k)
            res["hybrid"] = self.local_hybrid.retrieve(q, k)
        out = {"dyad": dyad, "t": str(t), "source": source, "query": {"vector_available": vec is not None,
               "schema": schema, "macro_region": macro, "excluded_crisno": cur, "runup_summary": summary}}
        for key, lst in res.items():
            out[key] = [a.to_dict() for a in lst]
            out[f"{key}_outcomes"] = outcome_distribution(lst)
        for key in ("vector", "schema", "hybrid"):
            for a in out[key]:
                assert date.fromisoformat(a["end_date"]) < t
                a["actor_names"] = [self.cname(x) for x in a["actors"]]
        return out

    # ------------------------------------------------------------------ markets / game
    @_locked
    def markets_view(self) -> dict:
        if self.market_joined is None:
            return {"available": False, "reason": "run markets/collect.py and markets/compare.py"}
        df = self.market_joined.sort_values("resolution_time", ascending=False)
        rows = []
        for r in df.itertuples():
            rows.append({"source": r.source, "market_id": str(r.market_id), "question": r.question, "dyad": r.dyad,
                         "dyad_label": self.dyad_label(r.dyad), "outcome": int(r.outcome_esc), "direction": int(r.direction),
                         "resolution_time": str(pd.Timestamp(r.resolution_time).date()),
                         "snapshot_date": str(pd.Timestamp(r.snapshot_date).date()),
                         "p_market": float(r.p_market), "p_model": float(r.p_model), "p_model_raw": float(r.p_model_raw),
                         "model_pct": float(r.model_pct), "p_stack_both": float(r.p_stack_both), "p_stack_model": float(r.p_stack_model),
                         "url": r.url, "volume": float(r.volume)})
        return {"available": True, "summary": self.market_compare, "rows": rows}

    @_locked
    def game_episodes(self, n: int = 8, seed: Optional[int] = None) -> List[dict]:
        rng = np.random.default_rng(seed)
        eps = []
        # market-era episodes (have a market price) - up to half
        if self.market_joined is not None and len(self.market_joined):
            mj = self.market_joined.sample(frac=1.0, random_state=int(rng.integers(1 << 31)))
            for r in mj.head(n // 2).itertuples():
                q = r.question if r.direction == 1 else f"Fighting continues — does “{r.question.rstrip('?')}” resolve NO?"
                eps.append({"kind": "market", "dyad": r.dyad, "dyad_label": self.dyad_label(r.dyad),
                            "date": str(pd.Timestamp(r.snapshot_date).date()), "question": q,
                            "resolution_time": str(pd.Timestamp(r.resolution_time).date()),
                            "p_model": float(r.p_stack_model), "model_kind": "stacked_percentile",
                            "p_model_raw": float(r.p_model), "model_pct": float(r.model_pct),
                            "p_market": float(r.p_market), "outcome": int(r.outcome_esc), "url": r.url})
        # historical ICB episodes: balanced positives / negatives, walk-forward OOS windows only
        need = n - len(eps)
        salt = str(int(rng.integers(1 << 31)))
        pos = self.con.execute("""
            SELECT f.dyad, f.t, f.p_cal, f.p_raw, f.y, o.p_oos FROM fc_y_icb f JOIN oos_y_icb o USING (dyad, t)
            WHERE f.y = 1 AND f.in_crisis = 0 AND f.t >= DATE '1997-01-01'
            ORDER BY hash(concat(f.dyad, f.t, ?)) LIMIT ?""", [salt, max(1, need // 2)]).df()
        neg = self.con.execute("""
            SELECT f.dyad, f.t, f.p_cal, f.p_raw, f.y, o.p_oos FROM fc_y_icb f JOIN oos_y_icb o USING (dyad, t)
            WHERE f.y = 0 AND f.in_crisis = 0 AND f.t >= DATE '1997-01-01'
              AND f.p_raw > (SELECT quantile_cont(p_raw, 0.97) FROM fc_y_icb)
            ORDER BY hash(concat(f.dyad, f.t, ?)) LIMIT ?""", [salt, max(1, need - need // 2)]).df()
        for r in pd.concat([pos, neg]).itertuples():
            t = pd.Timestamp(r.t).date()
            nxt = next((c for c in self.onsets_by_dyad.get(r.dyad, [])
                        if t < date.fromisoformat(c["onset_date"]) <= t + timedelta(days=30)), None)
            eps.append({"kind": "icb", "dyad": r.dyad, "dyad_label": self.dyad_label(r.dyad), "date": str(t),
                        "question": f"Will an ICB-coded international crisis between {self.dyad_label(r.dyad)} begin in the 30 days after {t}?",
                        "p_model": float(r.p_oos), "model_kind": "calibrated_oos", "p_model_raw": float(r.p_raw), "p_market": None,
                        "outcome": int(r.y), "crisis": None if nxt is None else nxt["name"]})
        rng.shuffle(eps)
        return eps[:n]
