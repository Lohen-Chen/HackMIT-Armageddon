"""Collect resolved geopolitical binary markets from Polymarket (Gamma + CLOB) and Kalshi public APIs.

Outputs
  data/raw/markets/polymarket_markets.json, kalshi_markets.json   (raw API payloads)
  data/processed/markets/markets.parquet     one row per market: id, source, question, dyad, outcome, resolution_time,
                                             snapshot prices at N days before resolution
  data/processed/markets/market_dyad_map.csv human-checkable mapping question -> dyad

Dyad mapping is keyword based (country aliases in the question text); questions with != 2 countries
detected are kept in the raw dump but excluded from the comparison.
"""
import json
import os
import re
import time
from datetime import datetime, timezone

import pandas as pd
import requests
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = yaml.safe_load(open(os.path.join(ROOT, "config.yaml")))
RAW = os.path.join(ROOT, "data", "raw", "markets")
OUT = os.path.join(ROOT, "data", "processed", "markets")
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
SNAP_DAYS = CFG["markets"]["snapshot_days_before_resolution"]

POLY_TAGS = ["geopolitics", "middle-east", "israel", "iran", "ukraine", "china", "taiwan", "war", "russia",
             "india", "pakistan", "north-korea", "venezuela", "gaza", "hamas", "hezbollah", "houthis", "syria"]
ESCALATION_KW = re.compile(
    r"\b(strike|strikes|attack|attacks|invade|invasion|invades|ceasefire|cease-fire|truce|war|troops|missile|"
    r"nuclear|military|bomb|bombing|capture|captures|seize|occupy|offensive|escalat|blockade|incursion|airstrike|"
    r"ground operation|declare|hostilit|shoot down|drone|kill|assassinat|annex|peace deal|peace agreement)\b", re.I)

COUNTRY_ALIASES = {
    "ISR": ["israel", "israeli", "idf"], "IRN": ["iran", "iranian", "tehran"], "LBN": ["lebanon", "lebanese", "hezbollah"],
    "PSE": ["gaza", "hamas", "palestin", "west bank", "rafah"], "SYR": ["syria", "syrian", "assad"],
    "YEM": ["yemen", "houthi"], "USA": ["u.s.", "us ", "united states", "america", "trump", "biden", "pentagon", "washington"],
    "RUS": ["russia", "russian", "putin", "kremlin", "moscow"], "UKR": ["ukraine", "ukrainian", "zelensky", "kyiv", "kiev"],
    "CHN": ["china", "chinese", "beijing", "pla ", "xi jinping"], "TWN": ["taiwan", "taiwanese", "taipei"],
    "IND": ["india", "indian", "new delhi", "modi"], "PAK": ["pakistan", "pakistani", "islamabad"],
    "PRK": ["north korea", "north korean", "dprk", "kim jong", "pyongyang"], "KOR": ["south korea", "south korean", "seoul"],
    "VEN": ["venezuela", "venezuelan", "maduro", "caracas"], "GUY": ["guyana", "essequibo"],
    "ARM": ["armenia", "armenian"], "AZE": ["azerbaijan", "azerbaijani", "nagorno", "karabakh"],
    "SRB": ["serbia", "serbian"], "XKX": ["kosovo"], "TUR": ["turkey", "turkish", "türkiye", "erdogan"],
    "GRC": ["greece", "greek"], "PHL": ["philippines", "philippine", "manila"], "JPN": ["japan", "japanese"],
    "SAU": ["saudi", "riyadh"], "QAT": ["qatar"], "IRQ": ["iraq", "iraqi", "baghdad"], "AFG": ["afghanistan", "taliban"],
    "SDN": ["sudan"], "ETH": ["ethiopia"], "ERI": ["eritrea"], "EGY": ["egypt"], "GBR": ["britain", "uk ", "united kingdom"],
    "POL": ["poland", "polish"], "BLR": ["belarus"], "MDA": ["moldova", "transnistria"], "GEO": ["georgia"],
    "COL": ["colombia"], "MEX": ["mexico", "mexican", "cartel"], "CAN": ["canada", "canadian"], "PAN": ["panama"],
    "DNK": ["denmark", "greenland", "danish"], "CUB": ["cuba", "cuban"], "COD": ["congo", "drc", "m23"], "RWA": ["rwanda"],
    "THA": ["thailand", "thai "], "KHM": ["cambodia", "cambodian"],
}
GENERIC_US = {"trump", "biden", "pentagon", "washington", "america"}


def detect_countries(text):
    t = " " + text.lower() + " "
    found = []
    for iso, aliases in COUNTRY_ALIASES.items():
        if any(a in t for a in aliases):
            found.append(iso)
    return found


def dyad_from_countries(cs):
    cs = sorted(set(cs))
    if len(cs) == 2:
        return f"{cs[0]}_{cs[1]}"
    # US is often implicit in "strike Iran" type questions; drop US if it makes exactly two
    if len(cs) == 3 and "USA" in cs:
        rest = [c for c in cs if c != "USA"]
        return f"{rest[0]}_{rest[1]}"
    return None


def _get(url, params=None, tries=3):
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
        time.sleep(1.5 * (i + 1))
    return None


# ------------------------------------------------------------------------------------ Polymarket
def poly_markets():
    seen, out = set(), []
    for tag in POLY_TAGS:
        for offset in range(0, 1000, 100):
            ev = _get(f"{GAMMA}/events", {"tag_slug": tag, "closed": "true", "limit": 100, "offset": offset})
            if not ev:
                break
            for e in ev:
                for m in e.get("markets", []):
                    if m["id"] in seen:
                        continue
                    seen.add(m["id"])
                    m["_event_title"] = e.get("title")
                    out.append(m)
            if len(ev) < 100:
                break
    return out


def poly_history(token_id):
    cache = os.path.join(RAW, "poly_hist", f"{token_id}.json")
    if os.path.exists(cache):
        return json.load(open(cache))
    h = _get(f"{CLOB}/prices-history", {"market": token_id, "interval": "max", "fidelity": 1440})
    hist = (h or {}).get("history", [])
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    json.dump(hist, open(cache, "w"))
    return hist


def parse_poly(m):
    try:
        outcomes = json.loads(m.get("outcomes") or "[]")
        prices = [float(x) for x in json.loads(m.get("outcomePrices") or "[]")]
        tokens = json.loads(m.get("clobTokenIds") or "[]")
    except (ValueError, TypeError):
        return None
    if len(outcomes) != 2 or set(o.lower() for o in outcomes) != {"yes", "no"} or len(prices) != 2 or len(tokens) != 2:
        return None
    if not m.get("closed") or max(prices) < 0.98:      # not resolved to a definite outcome
        return None
    q = m.get("question") or ""
    if not ESCALATION_KW.search(q):
        return None
    if float(m.get("volumeNum") or m.get("volume") or 0) < 5000:
        return None
    yes_idx = [o.lower() for o in outcomes].index("yes")
    outcome = 1 if prices[yes_idx] >= 0.98 else 0
    end = m.get("closedTime") or m.get("endDate")
    return {"source": "polymarket", "market_id": str(m["id"]), "question": q, "event": m.get("_event_title"),
            "yes_token": tokens[yes_idx], "outcome": outcome, "resolution_time": end,
            "volume": float(m.get("volumeNum") or m.get("volume") or 0), "url": f"https://polymarket.com/market/{m.get('slug')}"}


# ------------------------------------------------------------------------------------ Kalshi
KALSHI_SERIES_KW = re.compile(r"(iran|israel|ukrain|russia|china|taiwan|ceasefire|war|strike|invade|nato|gaza|hamas|korea|"
                              r"india|pakistan|venezuela|nuclear|missile|houthi|hezbollah|military|troops)", re.I)


def kalshi_markets():
    series = []
    for cat in ("Politics", "World", "Geopolitics"):
        s = _get(f"{KALSHI}/series", {"category": cat}) or {}
        series += [x for x in (s.get("series") or []) if KALSHI_SERIES_KW.search((x.get("title") or "") + " " + x["ticker"])]
    out = []
    for s in {x["ticker"]: x for x in series}.values():
        mk = _get(f"{KALSHI}/markets", {"series_ticker": s["ticker"], "status": "settled", "limit": 200}) or {}
        for m in mk.get("markets", []):
            m["_series_title"] = s["title"]
            out.append(m)
    return out


def kalshi_history(series_ticker, ticker, start, end):
    h = _get(f"{KALSHI}/series/{series_ticker}/markets/{ticker}/candlesticks",
             {"start_ts": int(start.timestamp()), "end_ts": int(end.timestamp()), "period_interval": 1440}) or {}
    pts = []
    for c in h.get("candlesticks", []):
        p = c.get("price", {}).get("close") or c.get("yes_ask", {}).get("close")
        if p is not None:
            pts.append({"t": c["end_period_ts"], "p": float(p) / 100.0})
    return pts


def parse_kalshi(m):
    q = f"{m.get('title', '')} {m.get('subtitle', '') or ''} {m.get('yes_sub_title', '') or ''}".strip()
    if not ESCALATION_KW.search(q) or m.get("result") not in ("yes", "no"):
        return None
    if float(m.get("volume") or 0) < 500:
        return None
    return {"source": "kalshi", "market_id": m["ticker"], "question": q, "event": m.get("_series_title"),
            "series_ticker": m.get("event_ticker", "").rsplit("-", 1)[0] if m.get("event_ticker") else None,
            "outcome": 1 if m["result"] == "yes" else 0, "resolution_time": m.get("settlement_ts") or m.get("close_time"),
            "volume": float(m.get("volume") or 0), "url": f"https://kalshi.com/markets/{m['ticker'].lower()}"}


# ------------------------------------------------------------------------------------ snapshots
def snapshot_prices(history, resolution_time):
    """Last observed price strictly before resolution - d days, for each d in SNAP_DAYS."""
    if not history:
        return {}
    hist = sorted(((int(h["t"]), float(h["p"])) for h in history), key=lambda x: x[0])
    res = pd.Timestamp(resolution_time).tz_convert("UTC") if pd.Timestamp(resolution_time).tzinfo else pd.Timestamp(resolution_time).tz_localize("UTC")
    out = {}
    for d in SNAP_DAYS:
        cutoff = (res - pd.Timedelta(days=d)).timestamp()
        prior = [p for t, p in hist if t <= cutoff]
        if prior:
            out[f"price_d{d}"] = prior[-1]
    out["first_trade"] = datetime.fromtimestamp(hist[0][0], tz=timezone.utc).isoformat()
    return out


def main():
    os.makedirs(RAW, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    rows = []

    pm_path = os.path.join(RAW, "polymarket_markets.json")
    if os.path.exists(pm_path) and not os.environ.get("REFRESH_MARKETS"):
        pm = json.load(open(pm_path))
    else:
        pm = poly_markets()
        json.dump(pm, open(pm_path, "w"))
    print(f"polymarket closed markets fetched: {len(pm)}")
    for m in pm:
        r = parse_poly(m)
        if not r:
            continue
        cs = detect_countries(r["question"] + " " + (r["event"] or ""))
        r["countries"] = ",".join(sorted(set(cs)))
        r["dyad"] = dyad_from_countries(cs)
        r.update(snapshot_prices(poly_history(r["yes_token"]), r["resolution_time"]))
        rows.append(r)
    print(f"polymarket escalation binaries: {len(rows)} (with dyad: {sum(1 for r in rows if r['dyad'])})")

    _write(rows)
    try:
        km = kalshi_markets()
    except Exception as e:  # noqa: BLE001 - Kalshi is optional; keep the Polymarket set
        print("kalshi fetch failed:", e)
        km = []
    json.dump(km, open(os.path.join(RAW, "kalshi_markets.json"), "w"))
    n0 = len(rows)
    for m in km:
        r = parse_kalshi(m)
        if not r or not r.get("series_ticker"):
            continue
        cs = detect_countries(r["question"] + " " + (r["event"] or ""))
        r["countries"] = ",".join(sorted(set(cs)))
        r["dyad"] = dyad_from_countries(cs)
        end = pd.Timestamp(r["resolution_time"])
        hist = kalshi_history(r["series_ticker"], r["market_id"], end - pd.Timedelta(days=120), end)
        r.update(snapshot_prices(hist, r["resolution_time"]))
        rows.append(r)
    print(f"kalshi settled escalation markets: {len(rows) - n0}")
    _write(rows)


def _write(rows):
    df = pd.DataFrame(rows)
    df["resolution_time"] = pd.to_datetime(df["resolution_time"], utc=True, errors="coerce")
    df = df.dropna(subset=["resolution_time"])
    df.to_parquet(os.path.join(OUT, "markets.parquet"), index=False)
    df[["source", "market_id", "question", "countries", "dyad", "outcome", "resolution_time", "volume", "url"]] \
        .sort_values(["dyad", "resolution_time"]).to_csv(os.path.join(OUT, "market_dyad_map.csv"), index=False)
    usable = df[df.dyad.notna() & df.get("price_d7", pd.Series(dtype=float)).notna()]
    print(f"total {len(df)}, usable (dyad + price 7d before resolution): {len(usable)}; "
          f"dyads: {usable.dyad.value_counts().head(10).to_dict()}")


if __name__ == "__main__":
    main()
