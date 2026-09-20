"""Signal in the Noise - demo API.

    uvicorn app.api.main:app --reload --port 8000

The browser talks only to this service; Elasticsearch credentials never leave the server.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.store import Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("signal.api")

app = FastAPI(title="Signal in the Noise", version="0.1")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
store: Optional[Store] = None


@app.on_event("startup")
def _startup():
    global store
    store = Store()
    log.info("store ready: %d dyads, %s..%s, retrieval=%s", len(store.dyads), store.t_min, store.t_max, store.retrieval_mode)


def _store() -> Store:
    if store is None:
        raise HTTPException(503, "store not ready")
    return store


def _date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise HTTPException(400, f"bad date {s!r}; use YYYY-MM-DD")


DYAD_RE = re.compile(r"^[A-Z]{3}_[A-Z]{3}$")


def _dyad(s: str) -> str:
    s = s.upper()
    if not DYAD_RE.fullmatch(s):
        raise HTTPException(400, f"bad dyad {s!r}; use AAA_BBB with ISO3 codes")
    return s


def _label(label: str) -> str:
    if label not in _store().labels:
        raise HTTPException(400, f"label must be one of {_store().labels}")
    return label


@app.get("/api/health")
def health():
    s = _store()
    return {"ok": True, "retrieval_mode": s.retrieval_mode, "labels": s.labels, "notes": s.notes}


@app.get("/api/meta")
def meta():
    return _store().meta()


@app.get("/api/map")
def map_snapshot(date: str = Query(...), label: str = "y_icb", top: int = 30):
    return _store().map_snapshot(_date(date), _label(label), top)


@app.get("/api/dyad/{dyad}/series")
def series(dyad: str, start: str, end: str, label: str = "y_icb"):
    return _store().series(_dyad(dyad), _date(start), _date(end), _label(label))


@app.get("/api/dyad/{dyad}/forecast")
def forecast(dyad: str, date: str, label: str = "y_icb"):
    return _store().forecast(_dyad(dyad), _date(date), _label(label))


@app.get("/api/dyad/{dyad}/analogs")
def analogs(dyad: str, date: str, k: Optional[int] = None):
    s = _store()
    if k is None:
        k = int(s.cfg["retrieval"]["k"])
    try:
        return s.analogs(_dyad(dyad), _date(date), min(max(k, 1), 10))
    except AssertionError:
        raise HTTPException(500, "retrieval invariant violated (end_date >= query_date)")


@app.get("/api/markets")
def markets():
    return _store().markets_view()


@app.get("/api/game/episodes")
def game(n: int = 8, seed: Optional[int] = None):
    return {"episodes": _store().game_episodes(min(max(n, 1), 20), seed)}


# ---- serve the built frontend if present (python-only demo mode)
DIST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "dist")


def mount_frontend(app: FastAPI, dist_dir: str) -> bool:
    """Serve `dist_dir` (a Vite build) with an SPA fallback to index.html; no-op if it does not exist."""
    root = os.path.realpath(dist_dir)
    if not os.path.isdir(root):
        return False
    if os.path.isdir(os.path.join(root, "assets")):
        app.mount("/assets", StaticFiles(directory=os.path.join(root, "assets")), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        f = os.path.realpath(os.path.join(root, path))
        if path and f.startswith(root + os.sep) and os.path.isfile(f):
            return FileResponse(f)
        return FileResponse(os.path.join(root, "index.html"))

    return True


mount_frontend(app, DIST)
