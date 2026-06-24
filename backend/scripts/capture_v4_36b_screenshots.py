"""WO v4.36b §6 — capture the 7 click-to-verify screenshots against a running dev server.

Drives headless Chromium (Playwright) against MES at http://localhost:8000 (the curated v4.36b demo
DB; autologins as admin) and saves full-page PNGs to docs/screenshots/v4.36b/. Re-runnable. Run AFTER
the §3.7 reseed + an `npm run build`, with the dev server up.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.sync_api import sync_playwright  # noqa: E402

BASE = "http://localhost:8000"
OUT = Path(__file__).resolve().parents[2] / "docs" / "screenshots" / "v4.36b"
T = 15_000


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(base_url=BASE, viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.set_default_timeout(T)

        page.goto(f"{BASE}/mes-app/")                               # autologin as admin
        page.wait_for_selector("[data-testid='top-nav']", timeout=30_000)

        def snap(name):
            page.screenshot(path=str(OUT / name), full_page=True)
            print("  saved", name)

        # (a) nav badge cluster
        page.goto(f"{BASE}/mes-app/chassis"); page.wait_for_selector("[data-testid='top-nav']")
        time.sleep(0.8)
        page.locator("[data-testid='top-nav']").screenshot(path=str(OUT / "a-nav-attention-badge.png"))
        print("  saved a-nav-attention-badge.png")

        # (b) Health Check dashboard — 5-group overview
        page.goto(f"{BASE}/mes-app/admin/health-check"); page.wait_for_selector("[data-testid='health-check']")
        time.sleep(0.6); snap("b-health-check-dashboard.png")

        # (c) Chassis flagged rows (chassis_no_vin red, etc.) — filter to Expected to surface them
        page.goto(f"{BASE}/mes-app/chassis"); page.wait_for_selector("[data-testid='chassis-table']")
        time.sleep(1.0); snap("c-chassis-flagged-rows.png")

        # (d) Planning bay flag (+ tooltip)
        page.goto(f"{BASE}/mes-app/planning"); page.wait_for_selector("[data-testid='assembly-bay']")
        time.sleep(1.2)
        fb = page.locator("[data-testid='flag-bay_post_attached_stale']").first
        if fb.count():
            fb.hover(); time.sleep(0.6)
        snap("d-planning-bay-flag.png")

        # (e) Costings row with a job flag
        page.goto(f"{BASE}/mes-app/costings"); page.wait_for_selector("[data-testid='costings-table']")
        time.sleep(1.0); snap("e-costings-job-flag.png")

        # (f) Drill-through deep-link landing on a chassis record
        page.goto(f"{BASE}/mes-app/admin/health-check"); page.wait_for_selector("[data-testid='health-check']")
        page.locator("[data-testid='health-flag-chassis_no_vin']").click(); time.sleep(0.5)
        page.locator("[data-testid='health-drill-open']").first.click()
        page.wait_for_url("**/chassis/**", timeout=T); time.sleep(1.0); snap("f-drill-deeplink-chassis.png")

        # (g) AgeingPill colour bands on the Planning day-counters
        page.goto(f"{BASE}/mes-app/planning"); page.wait_for_selector("[data-testid='day-counter']")
        time.sleep(1.2); snap("g-ageing-pill-bands.png")

        browser.close()
        print("DONE ->", OUT)


if __name__ == "__main__":
    main()
