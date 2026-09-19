---
name: test-signal-demo
description: Browser runtime testing of the Signal in the Noise demo with its local API and Elasticsearch retrieval.
---

# Local runtime
- Check `http://localhost:8000/api/health` before starting another backend; reuse a healthy instance.
- From the repository root, start with `PYTHONPATH=. python3 -m uvicorn app.api.main:app --port 8000` when needed. Allow startup time for data and model loading.
- The API serves the built React app at `/`; no local login is required.
- Before frontend npm commands, run `source ~/.nvm/nvm.sh`. Build from `app/frontend` only when needed.

## Devin Secrets Needed
- `ES_URL`
- `ES_API_KEY`
- Verify Elasticsearch mode in the health response and visible header; never log credential values.

## Browser checks
- Deep-link Explore using `#tab=explore&dyad=ISR_LBN&date=2006-07-09&label=y_icb`; use `markets` and `game` for the other tabs.
- Check search-dropdown stacking at 1280px, not just presence in the DOM.
- Distinguish analog end-date eligibility from start/end chronological correctness.
- For forecasts near the ICB completeness boundary, check whether the entire 30-day outcome horizon is covered.
- Complete eight game episodes with 50% guesses: the user's Brier should stay 0.250, while market counts should include only market episodes.
- Verify URL seed support before claiming reproducible browser sessions; backend seeded requests alone do not prove URL restoration.
- Capture API response and browser-error events passively through CDP to supplement visible assertions.
