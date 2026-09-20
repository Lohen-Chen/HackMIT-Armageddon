"""Shared fixtures.

`panel_paths` points the leakage tests at the real panel when it has been built, and otherwise
at a small synthetic panel produced by running the real ingest SQL -> features.build ->
build_labels.build on generated GDELT-format rows, so the leakage checks never skip in CI.
"""
import os
import random
import sys
from datetime import date, timedelta

import duckdb
import pandas as pd
import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipeline.gdelt_ingest import build_sql  # noqa: E402
from test_ingest import _row  # noqa: E402

REAL_PANEL = os.path.join(ROOT, "data", "processed", "panel", "panel_labelled.parquet")
REAL_WEEK = os.path.join(ROOT, "data", "processed", "panel", "dyad_week.parquet")

DYADS = [("USA", "IRN"), ("IND", "PAK"), ("RUS", "UKR")]
FIRST_DAY = date(2018, 1, 1)
N_DAYS = 120
CRISIS = {"crisno": 9001, "crisname": "Synthetic Gulf Crisis", "dyad": "IRN_USA",
          "onset_date": pd.Timestamp("2018-03-15"), "end_date": pd.Timestamp("2018-04-10")}


def _synthetic_gdelt(out_dir: str) -> None:
    """Write dyad_day/ and daily_totals/ parquet for N_DAYS daily files via the real ingest SQL."""
    rng = random.Random(0)
    con = duckdb.connect()
    for sub in ("dyad_day", "daily_totals"):
        os.makedirs(os.path.join(out_dir, sub), exist_ok=True)
    csv_dir = os.path.join(out_dir, "csv")
    os.makedirs(csv_dir, exist_ok=True)
    for i in range(N_DAYS):
        d = FIRST_DAY + timedelta(days=i)
        stem = d.strftime("%Y%m%d")
        rows = []
        for a, b in DYADS:
            n = rng.randint(3, 9)
            if (a, b) == ("USA", "IRN") and date(2018, 3, 1) <= d <= date(2018, 3, 20):
                n += 12                                        # run-up before the synthetic crisis
            for j in range(n):
                quad = rng.choice(["1", "2", "3", "4", "4"])
                root = {"1": "04", "2": "05", "3": "13", "4": "19"}[quad]
                event = root + "0"
                rows.append(_row(stem, a, a, b, b, event=event, root=root, quad=quad,
                                 gold=str(rng.uniform(-10, 5)), mentions=str(rng.randint(1, 20)),
                                 lat=f"{j}.0", lon=f"{i}.0"))
        csv = os.path.join(csv_dir, f"{stem}.export.CSV")
        with open(csv, "w") as f:
            f.write("\n".join(rows) + "\n")
        raw, ev, dyad, daily = build_sql(csv, True, stem, 7, True)
        con.execute(f"CREATE OR REPLACE TEMP TABLE ev AS WITH raw AS ({raw}) {ev}")
        for sub, sql in (("dyad_day", dyad), ("daily_totals", daily)):
            con.execute(f"COPY ({sql}) TO '{os.path.join(out_dir, sub, stem + '.parquet')}' (FORMAT PARQUET)")
        os.remove(csv)
    con.close()


def _synthetic_icb(path: str) -> None:
    pd.DataFrame([CRISIS]).to_parquet(path, index=False)


@pytest.fixture(scope="session")
def synthetic_gdelt(tmp_path_factory):
    """Synthetic GDELT aggregates + one-crisis ICB dyads file; returns the directory."""
    d = tmp_path_factory.mktemp("synthetic")
    _synthetic_gdelt(os.path.join(d, "gdelt"))
    _synthetic_icb(os.path.join(d, "icb_dyads.parquet"))
    return str(d)


@pytest.fixture(scope="session")
def synthetic_panel(synthetic_gdelt):
    """Run features.build + build_labels.build on the synthetic data; returns {panel, week}."""
    from labels.build_labels import build as build_labels
    from pipeline.features import build as build_features

    cfg = yaml.safe_load(open(os.path.join(ROOT, "config.yaml")))
    out = os.path.join(synthetic_gdelt, "panel")
    icb = os.path.join(synthetic_gdelt, "icb_dyads.parquet")
    build_features(os.path.join(synthetic_gdelt, "gdelt"), out, cfg, threads=2, mem="1GB", icb_dyads=icb)
    labelled = os.path.join(out, "panel_labelled.parquet")
    build_labels(os.path.join(out, "panel.parquet"), icb, labelled, os.path.join(out, "labels_report.md"),
                 cfg, threads=2)
    return {"panel": labelled, "week": os.path.join(out, "dyad_week.parquet"), "synthetic": True}


@pytest.fixture(scope="session")
def panel_paths(request):
    """Real panel if built (and SIGNAL_SYNTHETIC_PANEL is unset), else the synthetic one."""
    if not os.environ.get("SIGNAL_SYNTHETIC_PANEL") and os.path.exists(REAL_PANEL) and os.path.exists(REAL_WEEK):
        return {"panel": REAL_PANEL, "week": REAL_WEEK, "synthetic": False}
    return request.getfixturevalue("synthetic_panel")
