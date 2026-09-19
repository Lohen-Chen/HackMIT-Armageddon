import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from markets.compare import direction, select_markets  # noqa: E402


def test_direction_orientation():
    assert direction("US strikes Iran by February 28, 2026?") == 1
    assert direction("Will China invade Taiwan in 2025?") == 1
    assert direction("Russia x Ukraine ceasefire by May 31, 2026?") == -1
    assert direction("Trump ends Ukraine war in first 90 days?") == -1
    assert direction("Will no US x Venezuela military engagement occur in 2025?") == -1
    assert direction("Will there be no Russia x Ukraine ceasefire in 2025?") == 1
    assert direction("Will North Korea invade South Korea in 2025?") == 1  # "North" is not a negation


def _row(question, price, outcome):
    return {"source": "polymarket", "market_id": question, "event": question, "dyad": "AAA_BBB", "question": question,
            "volume": 1e6, "outcome": outcome, "price_d30": price, "resolution_time": "2025-12-31T00:00:00Z"}


def test_select_markets_flips_probability_and_outcome_together():
    m = pd.DataFrame([
        _row("US strikes Iran by February 28, 2026?", 0.8, 1),
        _row("Russia x Ukraine ceasefire by May 31, 2026?", 0.8, 1),
        _row("Will no US x Venezuela military engagement occur in 2025?", 0.8, 1),
        _row("Israel x Hamas ceasefire before July?", 0.3, 0),
    ])
    u = select_markets(m).set_index("question")
    assert (u.loc["US strikes Iran by February 28, 2026?", ["p_market", "outcome_esc"]] == [0.8, 1]).all()
    r = u.loc["Russia x Ukraine ceasefire by May 31, 2026?"]
    assert np.isclose(r.p_market, 0.2) and r.outcome_esc == 0
    r = u.loc["Will no US x Venezuela military engagement occur in 2025?"]
    assert np.isclose(r.p_market, 0.2) and r.outcome_esc == 0
    r = u.loc["Israel x Hamas ceasefire before July?"]
    assert np.isclose(r.p_market, 0.7) and r.outcome_esc == 1
