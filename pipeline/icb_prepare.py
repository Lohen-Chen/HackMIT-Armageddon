"""Load ICB v16 (system, actor, dyad), normalise actor codes to GDELT/ISO-3 country codes,
attach human-readable labels, and write processed parquet + a coverage report.

Outputs (data/processed/icb/):
  crises.parquet   one row per ICB crisis (system level) with onset/end dates + labels
  actors.parquet   one row per crisis-actor with iso3 + actor-level labels
  dyads.parquet    one row per ICB crisis dyad with iso3 for both sides
  unmatched_actors.csv   ICB actor codes with no GDELT country code
  docs/icb_coverage.md   coverage / variable report (auto-generated)

ICB uses Correlates-of-War state abbreviations; GDELT/CAMEO uses ISO-3166 alpha-3.  The mapping
below is hand-built.  Historical entities are mapped to the code GDELT itself uses for them
(GDELT maps "Soviet Union" -> RUS, "Yugoslavia" -> SRB, "Czechoslovakia" -> CZE, "Zaire" -> COD,
"North/South Vietnam" -> VNM, "South Yemen" -> YEM).  Entities GDELT has no country code for
(Kosovo, East Germany in the 1979-90 window) are logged as unmatched, never silently dropped.
"""
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw", "icb")
OUT = os.path.join(ROOT, "data", "processed", "icb")
DOCS = os.path.join(ROOT, "docs")

# COW abbreviation (ICB `actor`) -> ISO-3 (GDELT ActorCountryCode)
COW_TO_ISO3 = {
    "USA": "USA", "CAN": "CAN", "CUB": "CUB", "HAI": "HTI", "DOM": "DOM", "GRN": "GRD",
    "MEX": "MEX", "GUA": "GTM", "HON": "HND", "SAL": "SLV", "NIC": "NIC", "COS": "CRI",
    "PAN": "PAN", "COL": "COL", "VEN": "VEN", "GUY": "GUY", "ECU": "ECU", "PER": "PER",
    "BOL": "BOL", "PAR": "PRY", "CHL": "CHL", "ARG": "ARG",
    "UKG": "GBR", "NTH": "NLD", "BEL": "BEL", "LUX": "LUX", "VFR": "FRA", "FRN": "FRA",
    "SWZ": "CHE", "SPN": "ESP", "POR": "PRT", "GMY": "DEU", "GFR": "DEU",
    "GDR": None,  # East Germany: GDELT actor code GME has no country code
    "POL": "POL", "AUS": "AUT", "HUN": "HUN", "CZE": "CZE", "ITA": "ITA", "MLT": "MLT",
    "ALB": "ALB", "CRO": "HRV", "SER": "SRB", "YUG": "SRB", "BOS": "BIH",
    "KOS": None,  # Kosovo: no CAMEO country code
    "SLV": "SVN", "GRC": "GRC", "CYP": "CYP", "BUL": "BGR", "RUM": "ROU", "RUS": "RUS",
    "EST": "EST", "LAT": "LVA", "LIT": "LTU", "UKR": "UKR", "BLR": "BLR", "ARM": "ARM",
    "GRG": "GEO", "AZE": "AZE", "FIN": "FIN", "SWD": "SWE", "NOR": "NOR", "DEN": "DNK",
    "ICE": "ISL",
    "GAM": "GMB", "MLI": "MLI", "SEN": "SEN", "BEN": "BEN", "MAA": "MRT", "NIR": "NER",
    "CDI": "CIV", "GUI": "GIN", "BFO": "BFA", "SIE": "SLE", "GHA": "GHA", "TOG": "TGO",
    "CAO": "CMR", "NIG": "NGA", "CHA": "TCD", "DRC": "COD", "UGA": "UGA", "KEN": "KEN",
    "TAZ": "TZA", "BUI": "BDI", "RWA": "RWA", "SOM": "SOM", "DJI": "DJI", "ETH": "ETH",
    "ERI": "ERI", "ANG": "AGO", "MZM": "MOZ", "ZAM": "ZMB", "ZIM": "ZWE", "MAW": "MWI",
    "SAF": "ZAF", "NAM": "NAM", "LES": "LSO", "BOT": "BWA",
    "MOR": "MAR", "ALG": "DZA", "TUN": "TUN", "LIB": "LBY", "SUD": "SDN", "SSD": "SSD",
    "IRN": "IRN", "TUR": "TUR", "IRQ": "IRQ", "EGY": "EGY", "SYR": "SYR", "LEB": "LBN",
    "JOR": "JOR", "ISR": "ISR", "SAU": "SAU", "HIJ": "SAU", "NAJ": "SAU", "YEM": "YEM",
    "YPR": "YEM", "KUW": "KWT", "BAH": "BHR", "QAT": "QAT", "UAE": "ARE", "OMA": "OMN",
    "AFG": "AFG", "TAJ": "TJK", "KYR": "KGZ", "CHN": "CHN", "TAW": "TWN", "PRK": "PRK",
    "ROK": "KOR", "JPN": "JPN", "IND": "IND", "PAK": "PAK", "BNG": "BGD", "MYA": "MMR",
    "SRI": "LKA", "THI": "THA", "CAM": "KHM", "LAO": "LAO", "DRV": "VNM", "RVN": "VNM",
    "MAL": "MYS", "PHI": "PHL", "INS": "IDN", "AUL": "AUS", "PNG": "PNG", "NEW": "NZL",
    "SOL": "SLB",
}

# ICB region code (GEOG) -> label and coarse demo region
GEOG = {
    9: ("Central Asia", "Asia"), 10: ("West Asia", "Middle East"), 11: ("East Asia", "Asia"),
    12: ("South-East Asia", "Asia"), 13: ("South Asia", "Asia"), 15: ("Middle East", "Middle East"),
    20: ("West Africa", "Africa"), 21: ("North Africa", "Middle East"), 22: ("East Africa", "Africa"),
    23: ("Southern Africa", "Africa"), 24: ("Central Africa", "Africa"),
    30: ("Euro-Asia (Russia)", "Europe"), 31: ("East Europe", "Europe"), 32: ("Central Europe", "Europe"),
    33: ("West Europe", "Europe"), 34: ("North Europe", "Europe"), 35: ("South Europe", "Europe"),
    41: ("North America", "Americas"), 42: ("Central America & Caribbean", "Americas"),
    43: ("South America", "Americas"), 51: ("Australasia & Oceania", "Asia"),
}

LABELS = {
    "gravcr": {0: "Economic threat", 1: "Limited military threat", 2: "Political threat",
               3: "Territorial threat", 4: "Threat to influence", 5: "Threat of grave damage",
               6: "Threat to existence", 7: "Other"},
    "crismg": {1: "Negotiation", 2: "Adjudication/arbitration", 3: "Mediation",
               4: "Multiple, non-violent", 5: "Non-military pressure", 6: "Non-violent military",
               7: "Multiple incl. violence", 8: "Violence"},
    "sevviosy": {1: "No violence", 2: "Minor clashes", 3: "Serious clashes", 4: "Full-scale war"},
    "viol": {1: "No violence", 2: "Minor violence", 3: "Violence important", 4: "Violence preeminent"},
    "outesr": {1: "Tension escalation (recurred within 5y)", 2: "Tension reduction", 3: "Recent case"},
    "forout": {1: "Formal agreement", 2: "Semi-formal agreement", 3: "Tacit understanding",
               4: "Unilateral act", 5: "Imposed agreement", 6: "Other", 7: "Crisis faded"},
    "break": {1: "Verbal act", 2: "Political act", 3: "Economic act", 4: "External change",
              5: "Other non-violent act", 6: "Internal challenge", 7: "Non-violent military act",
              8: "Indirect violent act", 9: "Violent act"},
    "outcom": {1: "Victory", 2: "Compromise", 3: "Stalemate", 4: "Defeat", 5: "Other"},
    "triggr": {1: "Verbal act", 2: "Political act", 3: "Economic act", 4: "External change",
               5: "Other non-violent act", 6: "Internal challenge", 7: "Non-violent military act",
               8: "Indirect violent act", 9: "Violent act"},
    "issue": {1: "Military-security", 2: "Political-diplomatic", 3: "Economic-developmental",
              4: "Cultural-status", 5: "Other"},
    "regime": {1: "Democratic", 2: "Civil authoritarian", 3: "Military direct", 4: "Military indirect",
               5: "Military dual"},
    "powsta": {1: "Small power", 2: "Middle power", 3: "Great power", 4: "Superpower"},
    "nuclear": {1: "None", 2: "Foreseeable", 3: "Possesses", 4: "Second-strike"},
    "majres": {1: "No response", 2: "Verbal act", 3: "Political act", 4: "Economic act",
               5: "Other non-violent", 6: "Non-violent military", 7: "Multiple incl. non-violent military",
               8: "Violent military act"},
}

# Variable tiers (see docs/icb_variable_tiers.md).  Only pre_onset + at_onset may feed
# similarity scoring; ex_post is display-only.
TIER_SYSTEM = {
    "pre_onset": ["geog", "period", "protrac", "pcid", "powdissy", "ethnic", "syslevsy", "noactr", "gpinv", "powinv"],
    "at_onset": ["break", "trigent", "gravcr", "issues"],
    "ex_post": ["crismg", "cenviosy", "sevviosy", "viol", "timvio", "iwcmb", "outesr", "forout", "subout",
                "exsat", "usinv", "suinv", "chinv", "globorg", "globefct", "regorg", "roefct", "mediate",
                "yrterm", "moterm", "daterm"],
}
TIER_ACTOR = {
    "pre_onset": ["regime", "durreg", "powsta", "nuclear", "territ", "age", "allycap", "globmemb",
                  "econdt", "regrep", "socunr", "massvl", "gvinst", "pethin", "col"],
    "at_onset": ["triggr", "trigent", "trigloc", "gravty", "issue", "chissu"],
    "ex_post": ["majres", "trgresra", "crismg", "cenvio", "sevvio", "outcom", "outfor", "outevl", "outesr",
                "yrterm", "moterm", "daterm", "usinv", "suinv", "globorg", "regorg"],
}


def _date(y, m, d):
    y = pd.to_numeric(y, errors="coerce")
    m = pd.to_numeric(m, errors="coerce").fillna(1).clip(1, 12)
    d = pd.to_numeric(d, errors="coerce").fillna(1).clip(1, 31)
    out = pd.to_datetime(dict(year=y, month=m, day=d), errors="coerce")
    # roll invalid day-of-month (e.g. 31 Feb) back to month end
    bad = out.isna() & y.notna()
    if bad.any():
        out[bad] = pd.to_datetime(dict(year=y[bad], month=m[bad], day=1)) + pd.offsets.MonthEnd(0)
    return out


def load():
    sysdf = pd.read_csv(os.path.join(RAW, "icb1v16.csv"))
    act = pd.read_csv(os.path.join(RAW, "icb2v16.csv"))
    dy = pd.read_csv(os.path.join(RAW, "icbdy_v16.csv"))
    return sysdf, act, dy


def prepare(write=True):
    sysdf, act, dy = load()

    # ---- system level
    cr = sysdf.copy()
    cr["onset_date"] = _date(cr.yrtrig, cr.motrig, cr.datrig)
    cr["end_date"] = _date(cr.yrterm, cr.moterm, cr.daterm)
    cr["region"] = cr.geog.map(lambda g: GEOG.get(int(g), ("Unknown", "Other"))[0] if pd.notna(g) else None)
    cr["macro_region"] = cr.geog.map(lambda g: GEOG.get(int(g), ("Unknown", "Other"))[1] if pd.notna(g) else None)
    for col, lab in LABELS.items():
        if col in cr.columns:
            cr[col + "_label"] = cr[col].map(lambda v: lab.get(int(v)) if pd.notna(v) else None)
    cr["crisname"] = cr.crisname.str.strip().str.title()

    # ---- actor level
    ac = act.copy()
    ac["iso3"] = ac.actor.map(COW_TO_ISO3)
    ac["mapped"] = ac.actor.isin([k for k, v in COW_TO_ISO3.items() if v])
    ac["onset_date"] = _date(ac.yrtrig, ac.motrig, ac.datrig)
    ac["end_date"] = _date(ac.yrterm, ac.moterm, ac.daterm)
    for col, lab in LABELS.items():
        if col in ac.columns:
            ac[col + "_label"] = ac[col].map(lambda v: lab.get(int(v)) if pd.notna(v) else None)
    unmatched = ac[~ac.mapped].groupby(["actor", "cracid"]).agg(
        n_rows=("crisno", "size"), crises=("crisname", lambda s: "; ".join(sorted(set(s))[:5])),
        first_year=("yrtrig", "min"), last_year=("yrtrig", "max")).reset_index()
    unknown_codes = sorted(set(ac.actor) - set(COW_TO_ISO3))
    if unknown_codes:
        print("WARNING: ICB actor codes missing from COW_TO_ISO3:", unknown_codes, file=sys.stderr)

    # ---- dyad level
    d = dy.copy()
    d["iso3_a"] = d.namea.map(COW_TO_ISO3)
    d["iso3_b"] = d.nameb.map(COW_TO_ISO3)
    d["onset_date"] = _date(d.trgyrdy, d.trgmody, d.trgdady)
    d["end_date"] = _date(d.trmyrdy, d.trmmody, d.trmdady)
    # placeholder crises (no system-level trigger date, e.g. the uncoded 2022 Ukraine entry) carry a
    # dummy 1 Jan dyad date; treat them as undated so they never become labels or analogs
    undated = set(cr.loc[cr.onset_date.isna(), "crisno"])
    d.loc[d.crisno.isin(undated), ["onset_date", "end_date"]] = pd.NaT
    d["crisname"] = d.crisname.str.strip().str.title()
    d["dyad"] = [None if (pd.isna(a) or pd.isna(b) or a == b) else "_".join(sorted([a, b]))
                 for a, b in zip(d.iso3_a, d.iso3_b)]
    d = d.merge(cr[["crisno", "region", "macro_region", "gravcr", "sevviosy", "viol", "outesr",
                    "sevviosy_label", "outesr_label"]], on="crisno", how="left")

    if write:
        os.makedirs(OUT, exist_ok=True)
        cr.to_parquet(os.path.join(OUT, "crises.parquet"), index=False)
        ac.to_parquet(os.path.join(OUT, "actors.parquet"), index=False)
        d.to_parquet(os.path.join(OUT, "dyads.parquet"), index=False)
        unmatched.to_csv(os.path.join(OUT, "unmatched_actors.csv"), index=False)
        write_report(cr, ac, d, unmatched, unknown_codes)
    return cr, ac, d, unmatched


def write_report(cr, ac, d, unmatched, unknown_codes):
    os.makedirs(DOCS, exist_ok=True)
    g = cr[cr.onset_date >= "1979-01-01"]
    g13 = cr[cr.onset_date >= "2013-04-01"]
    lines = ["# ICB v16 coverage report", "", "Auto-generated by `pipeline/icb_prepare.py`.", ""]
    lines += ["## Files", "",
              f"- `icb1v16.csv` (system level): {len(cr)} crises x {cr.shape[1] - 10} raw variables",
              f"- `icb2v16.csv` (actor level): {len(ac)} crisis-actors, {ac.actor.nunique()} distinct actor codes",
              f"- `icbdy_v16.csv` (dyad level): {len(d)} dyad-years, {d.crisno.nunique()} crises, "
              f"{d.dyad.nunique()} distinct ISO-3 dyads", ""]
    lines += ["## Date coverage", "",
              f"- Crisis onsets: {cr.onset_date.min().date()} .. {cr.onset_date.max().date()}",
              f"- Crisis terminations: {cr.end_date.min().date()} .. {cr.end_date.max().date()}",
              f"- Crises with onset >= 1979-01-01 (GDELT 1.0 backfile era): **{len(g)}**",
              f"- Crises with onset >= 2013-04-01 (GDELT daily era): **{len(g13)}**",
              f"- Rows with missing onset date: {int(cr.onset_date.isna().sum())} "
              f"({', '.join(cr[cr.onset_date.isna()].crisname.tolist())})",
              "", "The last coded ICB crisis onset is in 2021; GDELT runs to the present, so the "
              "2022+ window has GDELT features but no ICB labels (see docs/ASSUMPTIONS.md).", ""]
    lines += ["## Crises by region (onset >= 1979)", "", g.macro_region.value_counts().to_markdown(), ""]
    lines += ["## Actor code mapping (COW abbreviation -> ISO-3 / GDELT)", "",
              f"- Mapped actor codes: {ac[ac.mapped].actor.nunique()} / {ac.actor.nunique()}",
              f"- Unmatched crisis-actor rows: {int((~ac.mapped).sum())} / {len(ac)}", ""]
    if len(unmatched):
        lines += [unmatched.to_markdown(index=False), ""]
    if unknown_codes:
        lines += [f"**Codes with no entry in the map (need attention):** {unknown_codes}", ""]
    lines += ["Historical entities are mapped to the ISO-3 code GDELT uses for their successor "
              "(USSR->RUS, Yugoslavia->SRB, Czechoslovakia->CZE, N/S Vietnam->VNM, S. Yemen->YEM, "
              "Zaire->COD, Hejaz/Najd->SAU, Vichy France->FRA, W. Germany->DEU).  Taiwan is TWN "
              "(recovered from the CAMEO actor code, see gdelt_ingest.py).", ""]
    lines += ["## Variable tiers", "", "See `docs/icb_variable_tiers.md`.  Counts of variables per tier:", ""]
    for name, tiers in [("system", TIER_SYSTEM), ("actor", TIER_ACTOR)]:
        for t, cols in tiers.items():
            lines.append(f"- {name}/{t}: {len(cols)} vars")
    lines += ["", "## All system-level variables", "", ", ".join(f"`{c}`" for c in cr.columns if not c.endswith("_label")), "",
              "## All actor-level variables", "", ", ".join(f"`{c}`" for c in ac.columns if not c.endswith("_label")), ""]
    with open(os.path.join(DOCS, "icb_coverage.md"), "w") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    cr, ac, d, unmatched = prepare()
    print(f"crises={len(cr)} actors={len(ac)} dyads={len(d)} unmatched_actor_rows={len(unmatched)}")
    print(unmatched.to_string())
