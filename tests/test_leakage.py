"""Leakage tests: no post-forecast-date information may enter features or similarity scoring."""
import json
import os
import sys

import duckdb
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from models.train import FORBIDDEN, FORBIDDEN_PATTERNS, feature_columns  # noqa: E402
from pipeline.icb_prepare import TIER_ACTOR, TIER_SYSTEM  # noqa: E402

PANEL = os.path.join(ROOT, "data", "processed", "panel", "panel_labelled.parquet")
FEATURES_JSON = os.path.join(ROOT, "data", "artifacts", "models", "y_icb", "features.json")


def test_feature_selector_excludes_forward_and_label_columns():
    df = pd.DataFrame({"dyad": ["A_B"], "t": [pd.Timestamp("2020-01-05")], "n_events_w4": [1.0],
                       "q4_next4w": [3.0], "y_icb": [0], "y_thresh": [1], "ever_icb": [True],
                       "next_onset": [pd.Timestamp("2020-02-01")], "goldstein_mean_w4": [0.1],
                       "sevviosy": [2], "year": [2020]})
    feats = feature_columns(df)
    assert feats == ["n_events_w4", "goldstein_mean_w4"]


def test_saved_feature_list_is_clean():
    if not os.path.exists(FEATURES_JSON):
        pytest.skip("model not trained yet")
    feats = json.load(open(FEATURES_JSON))
    ex_post = set(TIER_SYSTEM["ex_post"]) | set(TIER_ACTOR["ex_post"])
    for f in feats:
        assert f not in FORBIDDEN, f
        assert f not in ex_post, f
        assert not any(p in f for p in FORBIDDEN_PATTERNS), f


def test_tiers_are_disjoint():
    for tiers in (TIER_SYSTEM, TIER_ACTOR):
        seen = {}
        for tier, cols in tiers.items():
            for c in cols:
                assert c not in seen or seen[c] == tier or c in ("yrterm", "moterm", "daterm"), (c, tier, seen.get(c))
                seen[c] = tier


def test_features_only_use_data_up_to_t():
    """Recompute a rolling feature from the raw weekly sums and compare with the panel.

    If any feature peeked past t, the recomputation from weeks <= t would not match.
    """
    week = os.path.join(ROOT, "data", "processed", "panel", "dyad_week.parquet")
    if not (os.path.exists(PANEL) and os.path.exists(week)):
        pytest.skip("panel not built yet")
    con = duckdb.connect()
    rows = con.execute(f"""
      WITH p AS (SELECT dyad, t, n_events_w4, q4_w13 FROM read_parquet('{PANEL}')
                 WHERE n_events_w4 > 50 USING SAMPLE 200 ROWS (reservoir, 42)),
           w AS (SELECT dyad, t, n_events, q4 FROM read_parquet('{week}'))
      SELECT p.dyad, p.t, p.n_events_w4, p.q4_w13,
             (SELECT sum(n_events) FROM w WHERE w.dyad=p.dyad AND w.t <= p.t AND w.t > p.t - INTERVAL 28 DAY) AS re_w4,
             (SELECT sum(q4) FROM w WHERE w.dyad=p.dyad AND w.t <= p.t AND w.t > p.t - INTERVAL 91 DAY) AS re_q4_w13
      FROM p""").df()
    assert len(rows) > 0
    assert (rows.n_events_w4 == rows.re_w4.fillna(0)).all()
    assert (rows.q4_w13 == rows.re_q4_w13.fillna(0)).all()


def test_labels_are_strictly_after_t():
    if not os.path.exists(PANEL):
        pytest.skip("panel not built yet")
    con = duckdb.connect()
    bad = con.execute(f"""SELECT count(*) FROM read_parquet('{PANEL}')
                          WHERE y_icb=1 AND NOT (next_onset > t AND next_onset <= t + INTERVAL 30 DAY)""").fetchone()[0]
    assert bad == 0


def test_icb_prepare_has_no_unknown_actor_codes():
    from pipeline.icb_prepare import COW_TO_ISO3, RAW
    act = pd.read_csv(os.path.join(RAW, "icb2v16.csv"))
    unknown = set(act.actor) - set(COW_TO_ISO3)
    assert not unknown, unknown
