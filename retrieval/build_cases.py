"""Build the ICB case documents (one per crisis-dyad) with tiered fields + run-up vector.

Output: data/artifacts/cases.parquet and data/artifacts/cases.jsonl (what gets indexed in ES / FAISS).
Vectors exist only for cases whose onset is >= 1979-04-01 (13 weeks of GDELT); older cases are still
indexed for schema retrieval.
"""
import json
import os

import numpy as np
import pandas as pd

from retrieval.vectors import (SCALER_PATH, _con, fit_scaler, load_scaler, runup_summary, runup_vector)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICB = os.path.join(ROOT, "data", "processed", "icb")
ART = os.path.join(ROOT, "data", "artifacts")

TRIGENT_TYPE = {1: "Verbal", 2: "Political", 3: "Economic", 4: "External change", 5: "Other non-violent",
                6: "Internal challenge", 7: "Non-violent military", 8: "Indirect violent", 9: "Violent"}


def _num(v):
    return None if pd.isna(v) else (int(v) if float(v).is_integer() else float(v))


def build(fit_scaler_if_missing=True):
    cr = pd.read_parquet(os.path.join(ICB, "crises.parquet"))
    ac = pd.read_parquet(os.path.join(ICB, "actors.parquet"))
    dy = pd.read_parquet(os.path.join(ICB, "dyads.parquet"))
    if fit_scaler_if_missing and not os.path.exists(SCALER_PATH):
        fit_scaler()
    scaler = load_scaler()
    con = _con()

    # one row per crisis-dyad with min onset / max end
    d = (dy[dy.dyad.notna() & dy.onset_date.notna()]
         .groupby(["crisno", "dyad"]).agg(onset_date=("onset_date", "min"), end_date=("end_date", "max"),
                                          iso3_a=("iso3_a", "first"), iso3_b=("iso3_b", "first")).reset_index())
    # crises without any mapped dyad (single-actor / unmatched) -> still index with actors list
    single = cr[~cr.crisno.isin(d.crisno) & cr.onset_date.notna()][["crisno", "onset_date", "end_date"]].copy()
    single["dyad"] = None
    d = pd.concat([d, single], ignore_index=True)
    d["end_date"] = d.end_date.fillna(d.onset_date + pd.Timedelta(days=365))

    # actor-level aggregates (pre-onset tier)
    ag = ac.groupby("crisno").agg(
        actors=("iso3", lambda s: sorted({x for x in s if x})),
        regime_pair=("regime", lambda s: "-".join(str(int(x)) for x in sorted(s.dropna().unique()))),
        nuclear_max=("nuclear", "max"), powsta_max=("powsta", "max"),
        outcom_labels=("outcom_label", lambda s: [x for x in s if x]),
        issue_mode=("issue", lambda s: _num(s.mode().iloc[0]) if s.notna().any() else None),
    ).reset_index()

    rows = []
    merged = d.merge(cr, on="crisno", suffixes=("", "_cr")).merge(ag, on="crisno", how="left")
    merged = merged.rename(columns={"break": "brk"})
    for r in merged.itertuples():
        onset = pd.Timestamp(r.onset_date)
        end = pd.Timestamp(r.end_date) if pd.notna(r.end_date) else pd.Timestamp(r.end_date_cr)
        vec, summ = None, {}
        if r.dyad and onset >= pd.Timestamp("1979-04-01"):
            v, fr = runup_vector(con, r.dyad, onset - pd.Timedelta(days=1), scaler)
            if np.abs(v).sum() > 0:
                vec, summ = v.tolist(), runup_summary(fr)
        actors = list(r.actors) if isinstance(r.actors, (list, np.ndarray)) else []
        rows.append({
            "case_id": f"{int(r.crisno)}_{r.dyad or 'NA'}",
            "crisno": int(r.crisno), "name": r.crisname, "region": r.region, "macro_region": r.macro_region,
            "actors": actors, "dyad": r.dyad, "onset_date": onset.date().isoformat(), "end_date": end.date().isoformat(),
            "onset_year": int(onset.year),
            "pre_onset": {"geog": _num(r.geog), "powdissy": _num(r.powdissy), "gpinv": _num(r.gpinv),
                          "powinv": _num(r.powinv), "protrac": _num(r.protrac), "pcid": _num(r.pcid),
                          "ethnic": _num(r.ethnic), "syslevsy": _num(r.syslevsy), "noactr": _num(r.noactr),
                          "regime_pair": r.regime_pair if isinstance(r.regime_pair, str) else None,
                          "nuclear_max": _num(r.nuclear_max), "powsta_max": _num(r.powsta_max),
                          "period": _num(r.period)},
            "at_onset": {"trigent_type": TRIGENT_TYPE.get(_num(r.brk)), "break": _num(r.brk),
                         "gravcr": _num(r.gravcr), "gravcr_label": r.gravcr_label, "issues": _num(r.issues),
                         "issue_mode": _num(r.issue_mode) if pd.notna(r.issue_mode) else None},
            "ex_post": {"crismg": _num(r.crismg), "crismg_label": r.crismg_label, "sevviosy": _num(r.sevviosy),
                        "sevviosy_label": r.sevviosy_label, "viol": _num(r.viol), "viol_label": r.viol_label,
                        "outesr": _num(r.outesr), "outesr_label": r.outesr_label, "forout": _num(r.forout),
                        "forout_label": r.forout_label, "duration_days": int((end - onset).days),
                        "outcom_labels": list(r.outcom_labels) if isinstance(r.outcom_labels, (list, np.ndarray)) else []},
            "runup_vector": vec, "runup_summary": summ,
        })
    os.makedirs(ART, exist_ok=True)
    with open(os.path.join(ART, "cases.jsonl"), "w") as f:
        for row in rows:
            f.write(json.dumps(row, default=str) + "\n")
    flat = pd.DataFrame([{k: v for k, v in r.items() if k not in ("pre_onset", "at_onset", "ex_post", "runup_summary")}
                         for r in rows])
    flat.to_parquet(os.path.join(ART, "cases.parquet"), index=False)
    n_vec = sum(1 for r in rows if r["runup_vector"] is not None)
    print(f"cases={len(rows)} crises={flat.crisno.nunique()} with_vector={n_vec}")
    return rows


if __name__ == "__main__":
    build()
