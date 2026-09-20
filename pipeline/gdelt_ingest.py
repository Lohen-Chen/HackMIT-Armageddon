"""GDELT 1.0 -> dyad-day aggregates.

Streams every GDELT 1.0 event file (yearly 1979-2005, monthly 2006-2013/03, daily
2013-04-01 -> present) from data.gdeltproject.org, aggregates it with DuckDB to
(day, actor1_cc, actor2_cc) rows plus per-day totals, writes one
Parquet per source file and deletes the raw CSV.  Resumable: files whose two outputs
both exist are skipped (dyad_day is written last, so a partial run never looks complete).
Works with Python 3.9 (compute instance) and 3.10+.

    python pipeline/gdelt_ingest.py --workdir /dev/shm/gdelt --workers 16
    python pipeline/gdelt_ingest.py --workdir /tmp/gdelt --workers 4 --only 2018 --limit 3   # sample

Design notes (see docs/ASSUMPTIONS.md):
* GDELT 1.0 is used for the whole history so there is one schema / one coding regime.
  Daily files (>= 2013-04-01) have 58 columns (incl. SOURCEURL); the backfile has 57.
* "day" is the information-arrival day: the file date for daily files (the day the event
  entered GDELT), SQLDATE for the backfile (DATEADDED is a constant there).  Events whose
  SQLDATE is more than `max_event_lag_days` before the file date are dropped as stale
  references to old events.
* Duplicate events (same SQLDATE, Actor1Code, Actor2Code, EventCode, ActionGeo lat/long)
  are collapsed to one row keeping the max NumMentions.
* Actor country = ActorCountryCode (ISO-3166 alpha-3 as used by CAMEO).  Taiwan has no
  country code in CAMEO (actor code prefix TWN, blank country), so TWN is recovered from the
  actor code.  Regional pseudo-codes (AFR, EUR, MEA, ...) are dropped later in features.py.
"""
import argparse
import os
import re
import sys
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed

import duckdb
import requests
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = yaml.safe_load(open(os.path.join(ROOT, "config.yaml")))["gdelt"]
BASE_URL = CFG["base_url"]
FILESIZES_URL = CFG["filesizes_url"]
OUTPUTS = ("daily_totals", "dyad_day")   # dyad_day (the primary output) last

# CAMEO root codes 01..20
ROOT_CODES = ["%02d" % i for i in range(1, 21)]


def list_files(start_year=1979, end_date="20991231"):
    """Return [(name, size_bytes)] of GDELT 1.0 event zips in chronological order."""
    txt = requests.get(FILESIZES_URL, timeout=60).text
    out = []
    for line in txt.strip().splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        size, name = int(parts[0]), parts[1]
        stem = name.split(".")[0]
        if not re.fullmatch(r"\d{4}|\d{6}|\d{8}", stem):
            continue  # MASTERREDUCED etc.
        if int(stem[:4]) < start_year:
            continue
        if len(stem) == 8 and stem > end_date.replace("-", ""):
            continue
        out.append((name, size))
    out.sort(key=lambda x: x[0].split(".")[0].ljust(8, "0"))
    return out


def _download(url, dest, retries=5):
    for attempt in range(retries):
        try:
            with requests.get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            return
        except Exception as e:  # noqa: BLE001
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))
            print(f"retry {attempt+1} for {url}: {e}", file=sys.stderr)


def build_sql(csv_path, is_daily, file_day, max_lag_days, dedupe):
    """SQL producing the two aggregate tables (dyad_day, daily_totals) from one raw CSV."""
    # column indices (0-based) in GDELT 1.0
    # 0 id, 1 SQLDATE, 5 Actor1Code, 7 Actor1CountryCode, 15 Actor2Code, 17 Actor2CountryCode,
    # 25 IsRootEvent, 26 EventCode, 28 EventRootCode, 29 QuadClass, 30 Goldstein, 31 NumMentions,
    # 32 NumSources, 33 NumArticles, 34 AvgTone, 53 ActionGeo_Lat, 54 ActionGeo_Long, 56 DATEADDED
    ncols = 58 if is_daily else 57
    cols = ", ".join(f"'column{i:02d}': 'VARCHAR'" for i in range(ncols))
    if is_daily:
        day_expr = f"DATE '{file_day[:4]}-{file_day[4:6]}-{file_day[6:]}'"
        lag_filter = (
            f"AND TRY_CAST(strptime(column01, '%Y%m%d') AS DATE) >= {day_expr} - INTERVAL {max_lag_days} DAY "
            f"AND TRY_CAST(strptime(column01, '%Y%m%d') AS DATE) <= {day_expr} + INTERVAL 1 DAY"
        )
    else:
        day_expr = "TRY_CAST(strptime(column01, '%Y%m%d') AS DATE)"
        lag_filter = ""
    raw = f"""
    SELECT {day_expr} AS day,
           column01 AS sqldate,
           nullif(column05,'') AS a1code,
           coalesce(nullif(column07,''), CASE WHEN column05 LIKE 'TWN%' THEN 'TWN' END) AS a1cc,
           nullif(column15,'') AS a2code,
           coalesce(nullif(column17,''), CASE WHEN column15 LIKE 'TWN%' THEN 'TWN' END) AS a2cc,
           TRY_CAST(column25 AS TINYINT) AS is_root,
           column26 AS event_code, column28 AS root_code,
           TRY_CAST(column29 AS TINYINT) AS quad,
           TRY_CAST(column30 AS DOUBLE) AS goldstein,
           TRY_CAST(column31 AS INTEGER) AS mentions,
           TRY_CAST(column33 AS INTEGER) AS articles,
           TRY_CAST(column34 AS DOUBLE) AS tone,
           column53 AS lat, column54 AS lon
    FROM read_csv('{csv_path}', delim='\\t', header=false, quote='', escape='', columns={{{cols}}},
                  ignore_errors=true, null_padding=true)
    WHERE column01 IS NOT NULL AND length(column01)=8 {lag_filter}
    """
    if dedupe:
        ev = """
        SELECT day, sqldate, a1code, a1cc, a2code, a2cc, event_code, root_code, lat, lon,
               max(is_root) AS is_root, max(quad) AS quad, avg(goldstein) AS goldstein,
               max(mentions) AS mentions, max(articles) AS articles, avg(tone) AS tone
        FROM raw GROUP BY ALL
        """
    else:
        ev = "SELECT * FROM raw"
    root_counts = ",\n".join(
        f"count(*) FILTER (root_code='{rc}') AS r{rc}, sum(mentions) FILTER (root_code='{rc}') AS m{rc}"
        for rc in ROOT_CODES
    )
    dyad = f"""
    SELECT day, a1cc AS actor1_cc, a2cc AS actor2_cc,
           count(*) AS n_events,
           sum(mentions) AS n_mentions,
           sum(articles) AS n_articles,
           count(*) FILTER (is_root=1) AS n_root,
           sum(goldstein) AS goldstein_sum,
           sum(goldstein*mentions) AS goldstein_wsum,
           sum(tone) AS tone_sum,
           sum(tone*mentions) AS tone_wsum,
           count(*) FILTER (quad=1) AS q1, count(*) FILTER (quad=2) AS q2,
           count(*) FILTER (quad=3) AS q3, count(*) FILTER (quad=4) AS q4,
           sum(mentions) FILTER (quad=1) AS q1_m, sum(mentions) FILTER (quad=2) AS q2_m,
           sum(mentions) FILTER (quad=3) AS q3_m, sum(mentions) FILTER (quad=4) AS q4_m,
           {root_counts}
    FROM ev
    WHERE a1cc IS NOT NULL AND a2cc IS NOT NULL AND a1cc <> a2cc AND day IS NOT NULL
    GROUP BY ALL
    """
    daily = """
    SELECT day, count(*) AS n_events, sum(mentions) AS n_mentions,
           count(*) FILTER (a1cc IS NOT NULL AND a2cc IS NOT NULL AND a1cc<>a2cc) AS n_dyadic,
           count(*) FILTER (quad=4) AS q4, count(*) FILTER (quad=3) AS q3
    FROM ev WHERE day IS NOT NULL GROUP BY ALL
    """
    return raw, ev, dyad, daily


def process_file(name, workdir, outdir, threads=3, max_lag_days=7, dedupe=True):
    stem = name.split(".")[0]
    if all(os.path.exists(os.path.join(outdir, sub, f"{stem}.parquet")) for sub in OUTPUTS):
        return stem, "skip", 0
    t0 = time.time()
    zpath = os.path.join(workdir, name)
    _download(BASE_URL + name, zpath)
    with zipfile.ZipFile(zpath) as z:
        members = [m for m in z.namelist() if m.lower().endswith(".csv")]
        z.extract(members[0], workdir)
        csv_path = os.path.join(workdir, members[0])
    os.remove(zpath)
    is_daily = len(stem) == 8
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={threads}")
    con.execute("PRAGMA memory_limit='6GB'")
    raw, ev, dyad, daily = build_sql(csv_path, is_daily, stem, max_lag_days, dedupe)
    con.execute(f"CREATE TEMP TABLE ev AS WITH raw AS ({raw}) {ev}")
    n = con.execute("SELECT count(*) FROM ev").fetchone()[0]
    sqls = {"dyad_day": dyad, "daily_totals": daily}
    for sub in OUTPUTS:
        sql = sqls[sub]
        os.makedirs(os.path.join(outdir, sub), exist_ok=True)
        tmp = os.path.join(outdir, sub, f"{stem}.parquet.tmp")
        con.execute(f"COPY ({sql}) TO '{tmp}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        os.replace(tmp, os.path.join(outdir, sub, f"{stem}.parquet"))
    con.close()
    os.remove(csv_path)
    return stem, f"{n} events", time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", default="/tmp/gdelt_work")
    ap.add_argument("--outdir", default=None, help="default: <workdir>/out")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--threads", type=int, default=3, help="duckdb threads per worker")
    ap.add_argument("--start-year", type=int, default=int(CFG["start_year"]))
    ap.add_argument("--end-date", default=str(CFG["end_date"]).replace("-", ""))
    ap.add_argument("--only", default=None, help="regex on file stem, e.g. '^2018'")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--max-lag-days", type=int, default=int(CFG["max_event_lag_days"]))
    ap.add_argument("--no-dedupe", action="store_true", default=not CFG["dedupe"])
    args = ap.parse_args()
    outdir = args.outdir or os.path.join(args.workdir, "out")
    os.makedirs(args.workdir, exist_ok=True)
    os.makedirs(outdir, exist_ok=True)
    files = list_files(args.start_year, args.end_date)
    if args.only:
        files = [f for f in files if re.search(args.only, f[0].split(".")[0])]
    if args.limit:
        files = files[: args.limit]
    total_gb = sum(s for _, s in files) / 1e9
    print(f"{len(files)} files, {total_gb:.1f} GB zipped -> {outdir}", flush=True)
    done = 0
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = {
            ex.submit(process_file, n, args.workdir, outdir, args.threads, args.max_lag_days, not args.no_dedupe): n
            for n, _ in files
        }
        for fut in as_completed(futs):
            done += 1
            try:
                stem, msg, dt = fut.result()
                if msg != "skip" or done % 200 == 0:
                    print(f"[{done}/{len(files)}] {stem}: {msg} ({dt:.1f}s) elapsed {time.time()-t0:.0f}s", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"[{done}/{len(files)}] FAILED {futs[fut]}: {e}", file=sys.stderr, flush=True)
    print(f"finished in {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
