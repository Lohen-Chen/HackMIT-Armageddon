"""Capture README screenshots from a running demo (uvicorn on :8000) via a Chrome CDP endpoint.

    python3 scripts/screenshots.py [--cdp http://localhost:29229] [--base http://localhost:8000]
"""
import argparse
import os
import sys
import time

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "screenshots")

SHOTS = [
    ("explorer_isr_lbn_2006", "#tab=explore&dyad=ISR_LBN&date=2006-07-09&label=y_icb"),
    ("explorer_ind_pak_2019", "#tab=explore&dyad=IND_PAK&date=2019-02-10&label=y_icb"),
    ("explorer_chn_twn_2024", "#tab=explore&dyad=CHN_TWN&date=2024-07-28&label=y_icb"),
    ("markets", "#tab=markets&dyad=IRN_ISR&date=2025-06-08&label=y_icb"),
    ("game", "#tab=game&dyad=IRN_ISR&date=2025-06-08&label=y_icb"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cdp", default="http://localhost:29229")
    ap.add_argument("--base", default="http://localhost:8000")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(a.cdp)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.new_page()
        page.set_viewport_size({"width": 1500, "height": 1000})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        for name, h in SHOTS:
            page.goto("about:blank")
            page.goto(a.base + "/" + h)
            page.wait_for_load_state("networkidle")
            time.sleep(2.5)
            page.screenshot(path=os.path.join(OUT, f"{name}.png"), full_page=True)
            print("saved", name, "skeletons:", page.locator(".skeleton").count(), "errors:", page.locator(".error").count())
        page.close()
        if errors:
            print("console/page errors:", *errors[:10], sep="\n  ")
            sys.exit(1)


if __name__ == "__main__":
    main()
