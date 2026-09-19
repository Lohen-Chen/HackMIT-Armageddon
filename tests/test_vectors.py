"""weekly_frame() must return exactly 13 Sunday rows with missing weeks zero-filled in place."""
import os
import sys

import duckdb
import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from retrieval.vectors import FEATS, N_WEEKS, weekly_frame  # noqa: E402

SUNDAYS = pd.date_range("2020-01-05", periods=N_WEEKS, freq="7D")   # 2020-01-05 is a Sunday


@pytest.fixture
def con():
    dw = pd.DataFrame({"dyad": "AAA_BBB", "t": SUNDAYS.date, "n_events": np.arange(1, N_WEEKS + 1) * 10,
                       "q4": np.arange(1, N_WEEKS + 1), "q3": 2, "goldstein_sum": -5.0, "tone_sum": -3.0})
    wt = pd.DataFrame({"t": SUNDAYS.date, "tot_events": 100_000})
    c = duckdb.connect()
    c.register("dw_src", dw)
    c.register("wt_src", wt)
    c.execute("CREATE VIEW dw AS SELECT dyad, CAST(t AS DATE) t, n_events, q4, q3, goldstein_sum, tone_sum FROM dw_src")
    c.execute("CREATE VIEW wt AS SELECT CAST(t AS DATE) t, tot_events FROM wt_src")
    return c


def test_all_weeks_round_trip(con):
    fr = weekly_frame(con, "AAA_BBB", SUNDAYS[-1])
    assert len(fr) == N_WEEKS and list(fr.columns) == ["t"] + FEATS
    assert list(pd.to_datetime(fr.t)) == list(SUNDAYS)
    assert np.allclose(fr.log_events, np.log1p(np.arange(1, N_WEEKS + 1) * 10))
    assert (fr.log_events > 0).all()


def test_missing_trailing_weeks_are_zero_at_the_end(con):
    fr = weekly_frame(con, "AAA_BBB", SUNDAYS[-1] + pd.Timedelta(weeks=2))
    assert len(fr) == N_WEEKS
    assert list(pd.to_datetime(fr.t)) == list(SUNDAYS[2:]) + [SUNDAYS[-1] + pd.Timedelta(weeks=1), SUNDAYS[-1] + pd.Timedelta(weeks=2)]
    assert (fr[FEATS].iloc[-2:] == 0).all().all()
    assert (fr.log_events.iloc[:-2] > 0).all()


def test_missing_leading_weeks_are_zero_at_the_start(con):
    fr = weekly_frame(con, "AAA_BBB", SUNDAYS[-1] - pd.Timedelta(weeks=3))
    assert len(fr) == N_WEEKS
    assert (fr[FEATS].iloc[:3] == 0).all().all()
    assert (fr.log_events.iloc[3:] > 0).all()


def test_unknown_dyad_is_all_zero(con):
    fr = weekly_frame(con, "XXX_YYY", SUNDAYS[-1])
    assert len(fr) == N_WEEKS and (fr[FEATS] == 0).all().all()
