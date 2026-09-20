"""Unit tests for the GDELT ingest SQL: dedup, stale-event filter, Taiwan recovery."""
import os
import sys

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline.gdelt_ingest import build_sql  # noqa: E402

NCOLS = 58


def _row(sqldate, a1code, a1cc, a2code, a2cc, event="190", root="19", quad="4", gold="-10",
         mentions="5", lat="1.0", lon="2.0"):
    cols = [""] * NCOLS
    cols[0] = "1"; cols[1] = sqldate; cols[5] = a1code; cols[7] = a1cc; cols[15] = a2code; cols[17] = a2cc
    cols[25] = "1"; cols[26] = event; cols[28] = root; cols[29] = quad; cols[30] = gold
    cols[31] = mentions; cols[33] = mentions; cols[34] = "-2.5"; cols[53] = lat; cols[54] = lon
    cols[56] = "20180101"
    return "\t".join(cols)


def _run(rows, tmp_path, dedupe=True, file_day="20180101"):
    p = tmp_path / "x.csv"
    p.write_text("\n".join(rows) + "\n")
    raw, ev, dyad, daily = build_sql(str(p), True, file_day, 7, dedupe)
    con = duckdb.connect()
    con.execute(f"CREATE TEMP TABLE ev AS WITH raw AS ({raw}) {ev}")
    return con, con.execute(dyad).df()


def test_dedupe_collapses_identical_events(tmp_path):
    rows = [_row("20180101", "USA", "USA", "IRN", "IRN", mentions="3"),
            _row("20180101", "USA", "USA", "IRN", "IRN", mentions="9"),
            _row("20180101", "USA", "USA", "IRN", "IRN", event="010", root="01", quad="1")]
    con, d = _run(rows, tmp_path)
    assert d.n_events.sum() == 2
    assert d.n_mentions.sum() == 9 + 5  # max mentions (9, not 3+9) kept for the duplicate pair
    con2, d2 = _run(rows, tmp_path, dedupe=False)
    assert d2.n_events.sum() == 3


def test_stale_events_dropped_from_daily_files(tmp_path):
    rows = [_row("20180101", "USA", "USA", "IRN", "IRN"),
            _row("20171201", "USA", "USA", "IRN", "IRN", lat="5.0")]  # 31 days old -> stale
    con, d = _run(rows, tmp_path)
    assert d.n_events.sum() == 1


def test_taiwan_recovered_from_actor_code(tmp_path):
    rows = [_row("20180101", "CHN", "CHN", "TWN", "", lat="3.0"),
            _row("20180101", "TWNGOV", "", "CHNMIL", "CHN", lat="4.0")]
    con, d = _run(rows, tmp_path)
    assert set(d.actor1_cc) | set(d.actor2_cc) == {"CHN", "TWN"}
    assert d.n_events.sum() == 2


def test_same_country_events_excluded_from_dyads(tmp_path):
    rows = [_row("20180101", "USAGOV", "USA", "USAMIL", "USA"),
            _row("20180101", "USA", "USA", "", "", lat="9.0")]
    con, d = _run(rows, tmp_path)
    assert len(d) == 0


def test_process_file_regenerates_partial_outputs(tmp_path, monkeypatch):
    import zipfile
    from pipeline import gdelt_ingest

    csv = tmp_path / "20180101.export.CSV"
    csv.write_text(_row("20180101", "USA", "USA", "IRN", "IRN") + "\n")
    fixture = tmp_path / "fixture.zip"
    with zipfile.ZipFile(fixture, "w") as z:
        z.write(csv, csv.name)
    csv.unlink()

    calls = []

    def fake_download(url, dest, retries=5):
        calls.append(url)
        dest_dir = os.path.dirname(dest)
        os.makedirs(dest_dir, exist_ok=True)
        with open(fixture, "rb") as src, open(dest, "wb") as dst:
            dst.write(src.read())

    monkeypatch.setattr(gdelt_ingest, "_download", fake_download)
    work, out = tmp_path / "work", tmp_path / "out"
    work.mkdir()
    name = "20180101.export.CSV.zip"

    stem, msg, _ = gdelt_ingest.process_file(name, str(work), str(out), threads=1)
    assert msg == "1 events"
    for sub in ("dyad_day", "daily_totals"):
        assert (out / sub / f"{stem}.parquet").exists()
    assert gdelt_ingest.process_file(name, str(work), str(out), threads=1)[1] == "skip"
    assert len(calls) == 1

    (out / "daily_totals" / f"{stem}.parquet").unlink()
    stem2, msg2, _ = gdelt_ingest.process_file(name, str(work), str(out), threads=1)
    assert msg2 != "skip" and (out / "daily_totals" / f"{stem2}.parquet").exists()
    assert len(calls) == 2
