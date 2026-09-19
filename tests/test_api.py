"""API smoke + invariant tests, run against the git-tracked demo pack (no full data rebuild needed)."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["SIGNAL_DEMO_ONLY"] = "1"
os.environ.pop("ES_URL", None)  # exercise the local FAISS/schema fallback deterministically

DEMO = os.path.join(ROOT, "data", "artifacts", "demo", "models", "y_icb", "forecasts.parquet")
pytestmark = pytest.mark.skipif(not os.path.exists(DEMO), reason="demo pack missing (scripts/pack_demo.py)")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from app.api.main import app

    with TestClient(app) as c:
        yield c


def test_health_and_meta(client):
    h = client.get("/api/health").json()
    assert h["ok"] and "y_icb" in h["labels"]
    assert h["retrieval_mode"] == "local"
    m = client.get("/api/meta").json()
    assert m["t_min"] <= "1980-01-01" <= m["t_max"]
    assert len(m["heroes"]) >= 4 and {"ISR_LBN", "IND_PAK", "RUS_UKR"} <= {x["dyad"] for x in m["heroes"]}
    assert m["metrics"]["y_icb"]["model_raw"]["auc"] > 0.8
    assert m["metrics"]["y_icb"]["model_cal"]["brier"] <= m["metrics"]["y_icb"]["base_rate"]["brier"] * 1.01
    # boundaries come from the tracked train_meta.json files and config.yaml, not module constants
    assert m["sample_boundaries"] == {"trees_train_end": "2018-10-26", "icb_complete_end": "2021-12-31"}
    assert m["trees_train_end_by_label"]["y_thresh"] == "2022-09-30"
    assert not any("train_meta.json missing" in n for n in m["notes"])


def test_map_is_ranked_and_snapped_to_sunday(client):
    r = client.get("/api/map", params={"date": "2006-07-12", "label": "y_icb", "top": 10}).json()
    assert r["t"] == "2006-07-09"
    ps = [d["p_raw"] for d in r["top"]]
    assert ps == sorted(ps, reverse=True) and len(ps) == 10
    assert any(d["dyad"] == "ISR_LBN" for d in r["top"])


def test_forecast_flags_and_realised_label(client):
    f = client.get("/api/dyad/ISR_LBN/forecast", params={"date": "2006-07-09", "label": "y_icb"}).json()
    assert f["available"] and 0 <= f["p_lo"] <= f["p_cal"] <= f["p_hi"] <= 1
    assert f["flags"] == {"trees_out_of_sample": False, "calibration_out_of_sample": False, "icb_label_available": True}
    assert f["onset_within_30d"] and f["onset_within_30d"]["onset_date"] == "2006-07-12"
    assert f["drivers"]["mode"] == "local" and len(f["drivers"]["items"]) > 0

    g = client.get("/api/dyad/CHN_TWN/forecast", params={"date": "2024-07-28", "label": "y_icb"}).json()
    assert g["flags"] == {"trees_out_of_sample": True, "calibration_out_of_sample": True, "icb_label_available": False}
    assert g["onset_within_30d"] is None

    u = client.get("/api/dyad/AAA_BBB/forecast", params={"date": "2024-07-28"}).json()
    assert u["available"] is False


def test_series_window(client):
    s = client.get("/api/dyad/RUS_UKR/series", params={"start": "2021-06-01", "end": "2022-06-01", "label": "y_icb"}).json()
    ts = [p["t"] for p in s["points"]]
    assert ts == sorted(ts) and "2021-06-01" <= ts[0] and ts[-1] <= "2022-06-01"
    assert all(0 <= p["p_cal"] <= 1 for p in s["points"])


def test_analogs_respect_query_date(client):
    for dyad, d in [("ISR_LBN", "2006-07-05"), ("IND_PAK", "2019-02-10"), ("RUS_UKR", "2022-02-13")]:
        a = client.get(f"/api/dyad/{dyad}/analogs", params={"date": d, "k": 5}).json()
        assert a["source"] == "local"
        for kind in ("vector", "schema", "hybrid"):
            assert len(a[kind]) > 0, (dyad, kind)
            for c in a[kind]:
                assert c["end_date"] < d, (dyad, kind, c["name"], c["end_date"])
                assert c["dyad"] != dyad or c["onset_date"] < d


def test_bad_inputs(client):
    assert client.get("/api/map", params={"date": "yesterday"}).status_code == 400
    assert client.get("/api/map", params={"date": "2020-01-01", "label": "y_nope"}).status_code == 400
    assert client.get("/api/dyad/ISR/analogs", params={"date": "2006-07-05"}).status_code == 400
    assert client.get("/api/dyad/ISR_LBN'%20OR%20'1'='1/analogs", params={"date": "2006-07-05"}).status_code == 400
    assert client.get("/api/dyad/isr_lbn/forecast", params={"date": "2006-07-09"}).status_code == 200


def test_spa_fallback_blocks_traversal_and_unknown_api(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.main import mount_frontend

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa</html>")
    (dist / "assets" / "a.js").write_text("1")
    (tmp_path / "config.yaml").write_text("secret: 1\n")

    a = FastAPI()
    assert mount_frontend(a, str(dist))
    with TestClient(a) as c:
        for p in ("/../../config.yaml", "/..%2F..%2Fconfig.yaml", "/%2E%2E/config.yaml"):
            r = c.get(p)
            assert r.status_code in (200, 404), p
            assert "secret" not in r.text, p
        assert c.get("/some/route").text == "<html>spa</html>"
        assert c.get("/assets/a.js").text == "1"
        assert c.get("/api/nope").status_code == 404


def test_markets_and_game(client):
    m = client.get("/api/markets").json()
    assert m["available"] and m["summary"]["n_markets"] >= 20
    for r in m["rows"]:
        assert 0 <= r["p_market"] <= 1 and r["outcome"] in (0, 1)
        assert r["snapshot_date"] < r["resolution_time"]
    g = client.get("/api/game/episodes", params={"n": 8, "seed": 1}).json()["episodes"]
    assert len(g) == 8 and {e["kind"] for e in g} <= {"icb", "market"}
    for e in g:
        assert e["model_kind"] == ("stacked_percentile" if e["kind"] == "market" else "calibrated_oos")
    assert client.get("/api/game/episodes", params={"n": 8, "seed": 1}).json()["episodes"] == g
