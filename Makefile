.PHONY: setup lock demo serve frontend test lint pipeline features labels train score cases index-es retrieval-eval markets pack screenshots

PY ?= python3
GDELT_OUT ?= data/processed/gdelt
THREADS ?= 8
MEM ?= 24GB
export PYTHONPATH := .

## ---- one-command demo (uses the git-tracked demo pack + cases.jsonl; no data rebuild) ----
setup:
	@test -n "$$VIRTUAL_ENV$$CONDA_PREFIX" || echo "warning: installing into the global interpreter; consider python3 -m venv .venv"
	$(PY) -m pip install -r requirements.txt
	cd app/frontend && npm ci

lock:                ## regenerate the pinned requirements.txt from requirements.in (Python 3.11 / Linux)
	$(PY) -m piptools compile --strip-extras --no-header --output-file requirements.txt requirements.in

demo: setup frontend serve

serve:
	$(PY) -m uvicorn app.api.main:app --host 0.0.0.0 --port 8000

frontend:
	cd app/frontend && npm run build

dev-frontend:
	cd app/frontend && npm run dev

test:
	$(PY) -m pytest -q tests

lint:
	$(PY) -m pyflakes app/api pipeline labels models retrieval markets scripts tests
	cd app/frontend && npm run typecheck && npm run lint

## ---- full pipeline (hours; needs ~40 GB disk for GDELT zips, or run on the compute box) ----
pipeline: icb ingest features labels train score cases index-es retrieval-eval markets pack

icb:
	$(PY) pipeline/icb_prepare.py

ingest:
	$(PY) pipeline/gdelt_ingest.py --workdir data/raw/gdelt --outdir $(GDELT_OUT) --workers 4 --threads 3

features:
	$(PY) pipeline/features.py --gdelt-out $(GDELT_OUT) --threads $(THREADS) --mem $(MEM)

labels:
	$(PY) labels/build_labels.py --threads $(THREADS)

train:
	$(PY) models/train.py --label y_icb
	$(PY) models/train.py --label y_thresh

score:
	$(PY) models/score.py --label y_icb
	$(PY) models/score.py --label y_thresh

cases:
	$(PY) retrieval/vectors.py
	$(PY) retrieval/build_cases.py

index-es:            ## needs ES_URL + ES_API_KEY
	$(PY) retrieval/index_es.py

retrieval-eval:
	$(PY) retrieval/eval.py

markets:
	$(PY) markets/collect.py
	$(PY) markets/compare.py

pack:
	$(PY) scripts/pack_demo.py

screenshots:         ## API on :8000 + Chrome with --remote-debugging-port=29229
	$(PY) scripts/screenshots.py
