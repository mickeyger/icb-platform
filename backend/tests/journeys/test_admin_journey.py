"""WO v4.26.1 — Admin master-data journey (the first concrete end-to-end test).

This is the ONE worked example the WO asks for (§0.10): it exercises the admin
UAT path end-to-end through a real browser —

    autologin as admin
      -> Admin entry visible in the top nav
      -> visit all four master-data sub-screens (spec-options / rules / lookups /
         price-overrides), each renders its table
      -> full lifecycle on a BOM rule: create (with live formula validation),
         edit, delete — driven purely through the UI (so CSRF + toast + refetch
         all go through the real SPA plumbing)

plus a deterministic auth-gate assertion: an unauthenticated caller hitting an
admin API is rejected.

The CRUD row uses a panel name no seed row uses, so it is unique on the
bom_rules (body_type, section, panel, output_field) constraint and trivial to
find. The journey self-cleans any leftover test row first, so it is idempotent —
a half-failed prior run never wedges the next one.

Run locally (after `npm run build` in frontend/ + `playwright install chromium`):

    pytest backend/tests/journeys/test_admin_journey.py -v
"""
from __future__ import annotations

from playwright.sync_api import Page, expect

from _common import admin_session, shot  # noqa: E402  (sys.path set in conftest)

# Auto-retry budget for assertions. The default is 5s; CI runners are slow and
# the create/edit cycle waits on a network round-trip + a table refetch, so we
# pass this explicitly to the assertions that follow a mutation.
T = 15_000

TEST_PANEL = "JOURNEY_TEST_PANEL"            # no seed row uses this panel name
ADMIN_SUBSCREENS = ["spec-options", "rules", "lookups", "price-overrides"]
CREATE_FORMULA = "ceil(length_mm / 1000)"
EDIT_FORMULA = "ceil(length_mm / 1220)"


def _rules_test_rows(page: Page):
    """Locator for the BOM-rules table row(s) carrying our test panel name."""
    return page.locator("[data-testid='admin-row']", has_text=TEST_PANEL)


def _clean_test_rows(page: Page) -> None:
    """Delete any leftover test rows from a prior interrupted run (idempotency)."""
    while _rules_test_rows(page).count() > 0:
        row = _rules_test_rows(page).first
        row.get_by_test_id("admin-delete").click()   # window.confirm auto-accepted
        row.wait_for(state="detached", timeout=T)


def test_admin_journey(page: Page) -> None:
    # Delete uses window.confirm — without a handler Playwright auto-DISMISSES
    # (i.e. cancels) the dialog, so register an accept handler up front.
    page.on("dialog", lambda dialog: dialog.accept())

    # 1) Autologin as admin and land on the authenticated shell.
    admin_session(page)
    shot(page, "01-dashboard")

    # 2) The Admin entry is present in the nav for an admin session; open it.
    admin_nav = page.get_by_test_id("nav-admin")
    expect(admin_nav).to_be_visible(timeout=T)
    admin_nav.click()

    # 3) Walk all four master-data sub-screens; each must render its table.
    for key in ADMIN_SUBSCREENS:
        page.get_by_test_id(f"admin-nav-{key}").click()
        expect(page.get_by_test_id("admin-table")).to_be_visible(timeout=T)
        shot(page, f"02-subscreen-{key}")

    # 4) Full CRUD lifecycle on a BOM rule. Re-select the rules sub-screen
    #    explicitly so this block doesn't depend on the loop's final state.
    page.get_by_test_id("admin-nav-rules").click()
    expect(page.get_by_test_id("admin-table")).to_be_visible(timeout=T)
    _clean_test_rows(page)

    # 4a) Create — open the form, fill it, live-validate the formula, save.
    page.get_by_test_id("admin-new").click()
    expect(page.get_by_test_id("admin-form")).to_be_visible(timeout=T)
    page.get_by_test_id("field-body_type").fill("Freezer")
    page.get_by_test_id("field-panel").fill(TEST_PANEL)
    page.get_by_test_id("field-formula_expression").fill(CREATE_FORMULA)

    page.get_by_test_id("admin-validate-formula").click()
    expect(page.get_by_test_id("admin-formula-check")).to_contain_text("valid", timeout=T)
    shot(page, "03-create-form-validated")

    page.get_by_test_id("admin-save").click()
    expect(page.get_by_test_id("admin-form")).to_be_hidden(timeout=T)
    expect(_rules_test_rows(page)).to_have_count(1, timeout=T)
    expect(_rules_test_rows(page)).to_contain_text("1000", timeout=T)
    shot(page, "04-rule-created")

    # 4b) Edit — change the formula, save, confirm the table reflects it.
    _rules_test_rows(page).get_by_test_id("admin-edit").click()
    expect(page.get_by_test_id("admin-form")).to_be_visible(timeout=T)
    page.get_by_test_id("field-formula_expression").fill(EDIT_FORMULA)
    page.get_by_test_id("admin-save").click()
    expect(page.get_by_test_id("admin-form")).to_be_hidden(timeout=T)
    expect(_rules_test_rows(page)).to_contain_text("1220", timeout=T)
    shot(page, "05-rule-edited")

    # 4c) Delete — remove the row; the table must drop it.
    _rules_test_rows(page).get_by_test_id("admin-delete").click()
    expect(_rules_test_rows(page)).to_have_count(0, timeout=T)
    shot(page, "06-rule-deleted")


def test_admin_api_rejects_unauthenticated(live_server: str, playwright_instance) -> None:
    """The admin gate the UI relies on is real: a session-less caller is refused.

    Uses a fresh APIRequestContext (no cookies) so there is no autologin session;
    GET needs no CSRF token, so a 401/403 here is a clean authorization signal.
    """
    api = playwright_instance.request.new_context(base_url=live_server)
    try:
        resp = api.get("/api/admin/bom-rules")
        assert resp.status in (401, 403), (
            f"expected the admin API to reject an unauthenticated caller, got {resp.status}"
        )
    finally:
        api.dispose()
