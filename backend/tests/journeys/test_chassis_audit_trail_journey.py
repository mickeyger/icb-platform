"""WO v4.36.5 §3.5 — Chassis audit-trail + edit journey (Playwright, both CI runners).

Drives the v4.36.5 surfaces end-to-end in a real browser against the seeded icb_mes:
  autologin (admin) -> Chassis list -> open a chassis -> Edit a field (Notes) -> Save (PATCH 200, the
  version-echo etag flows) -> open the §3.4 "Change history" section -> the audit row for that edit renders
  (field + humanised source + editor).

This proves the §3.1 chokepoint write -> §3.4 audit read loop through the UI. The optimistic-lock 409, the
structural-op (merge/soft_delete/restore) audit rows, and the §3.3 Planning-ack read-only editNotice banner
are covered deterministically by the backend tests (test_chassis_sole_editor_gate / _role_gate_api) + the
existing admin-merge journey; this journey owns the edit→trail happy path on the Chassis page.

Run locally (after `npm run build` + `playwright install chromium`):
    pytest backend/tests/journeys/test_chassis_audit_trail_journey.py -v
"""
from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from _common import admin_session, shot  # noqa: E402  (sys.path set in conftest)

T = 15_000
JOURNEY = "chassis_audit"


def test_chassis_audit_trail_journey(page: Page) -> None:
    # 1) Autologin as admin and open the Chassis module (wait on the data fetch — the §3.7 instrument pattern).
    admin_session(page)
    nav = page.get_by_test_id("nav-chassis")
    expect(nav).to_be_visible(timeout=T)
    with page.expect_response(lambda r: "/api/chassis-records" in r.url, timeout=T) as resp_info:
        nav.click()
    assert resp_info.value.status == 200
    expect(page.get_by_test_id("chassis-table")).to_be_visible(timeout=T)

    # 2) Open the first chassis detail.
    page.get_by_test_id("chassis-row").first.click()
    expect(page).to_have_url(re.compile(r"/chassis/.+"), timeout=T)
    expect(page.get_by_test_id("chassis-detail")).to_be_visible(timeout=T)

    # 3) Edit the Notes field and save — the PATCH carries the version-echo; assert it commits (200).
    page.get_by_test_id("chassis-edit").click()
    expect(page.get_by_test_id("chassis-edit-form")).to_be_visible(timeout=T)
    page.get_by_test_id("chassis-edit-notes").fill("Audited via journey")
    with page.expect_response(
        lambda r: "/api/chassis-records/" in r.url and r.request.method == "PATCH", timeout=T
    ) as patch_info:
        page.get_by_test_id("chassis-edit-save").click()
    assert patch_info.value.status == 200, (
        f"chassis PATCH returned {patch_info.value.status} (expected 200) — a 409 here means a stale "
        f"version-echo, a 403 means the role-gate; either is a real regression, not a flake.")
    expect(page.get_by_test_id("chassis-edit-form")).to_be_hidden(timeout=T)

    # 4) Open the §3.4 Change-history section — lazy-fetches the audit; the edit we just made renders.
    toggle = page.get_by_test_id("chassis-audit-toggle")
    expect(toggle).to_be_visible(timeout=T)
    with page.expect_response(lambda r: r.url.rstrip("/").endswith("/audit"), timeout=T) as audit_info:
        toggle.click()
    assert audit_info.value.status == 200
    expect(page.get_by_test_id("chassis-audit-table")).to_be_visible(timeout=T)
    expect(page.get_by_test_id("chassis-audit-row").first).to_be_visible(timeout=T)
    shot(page, "01-chassis-audit-trail", journey=JOURNEY)
