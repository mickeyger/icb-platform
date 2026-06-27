"""WO v4.36c §3.6 — Kenny's QC inspection + dispatch JOURNEY (the UI flow, end-to-end).

Drives the /admin/qc screen as the REAL qc_inspector role (the migration-0028 grant matrix, exercised
through the browser — not the admin code-wildcard): the inbox lists a chassis awaiting QA, the inspection
form records a verdict per category, and sign-off either PASSES (→ status 'dispatched', the collection PDF
regenerates on demand, the chassis leaves the inbox) or FAILS (→ stays 'awaiting_qa', the QC cycle
increments, the re-inspection badge shows on re-open).

Driving as qc_inspector (via role_session) also proves the AdminModule QC_ROLES carve-out — a NON-admin
QC role can reach /admin/qc. The precise per-role permission matrix (inspect vs sign-off ×
qc_inspector/planner/production/sales) lives at the API level in tests/test_qc_api.py (the
dependency_overrides mechanism, §3.6); this journey proves the UI wiring + the real role drives it end to
end. Runs on icb_test (CI). P435-marked data (shared make_assembly_job factory + purge).
"""
from __future__ import annotations

from datetime import date

import pytest
from playwright.sync_api import Page, expect

from _common import role_session, shot  # noqa: E402  (sys.path set in conftest)
import _v435 as h  # noqa: E402

T = 15_000
JOURNEY = "qc_dispatch"


@pytest.fixture(autouse=True)
def _clean():
    h.purge()
    yield
    h.purge()


def _awaiting_qa_chassis() -> dict:
    """A P435 chassis promoted to awaiting_qa (the only QC precondition). Direct-DB so the setup needs no
    chassis-move permission; adds the moved_to_awaiting_qa event so the inbox ageing pill has a since-date."""
    s = h.make_assembly_job(attached=True)
    from app.database import SessionLocal
    from app.models.mes import ChassisLifecycleEvent, ChassisRecord
    with SessionLocal() as db:
        db.get(ChassisRecord, s["chassis_id"]).status = "awaiting_qa"
        db.add(ChassisLifecycleEvent(chassis_record_id=s["chassis_id"], cycle_number=1,
                                     event_type="moved_to_awaiting_qa", event_date=date.today(), created_by="t"))
        db.commit()
    return s


def _open_qc_inbox(page: "Page", base: str, username: str) -> None:
    """qc_inspector session → deep-link /admin/qc, gating on the autologin round-trip so the inbox fetch
    doesn't race the auth guard (the v4.26 deep-link lesson). role_session keeps the qc session across the
    SPA's re-fired autologin; the QC_ROLES gate then renders the screen for the non-admin role."""
    role_session(page, username, base=base)
    with page.expect_response(lambda r: "/api/mes/autologin" in r.url, timeout=30_000):
        page.goto("/mes-app/admin/qc")
    page.wait_for_selector("[data-testid='qc-inbox']", timeout=30_000)


def _record_all(page: "Page", *, fail_first: bool = False) -> None:
    """Click a verdict on every category, gating each on its POST so the server holds the full set before
    sign-off (the form fires verdict POSTs fire-and-forget; sign-off reads server state, so an un-awaited
    click would race into a 422-incomplete)."""
    passes = page.locator('[data-testid^="qc-pass-"]')
    fails = page.locator('[data-testid^="qc-fail-"]')
    n = passes.count()
    assert n >= 5, f"expected at least the 5 seeded categories, got {n}"
    for i in range(n):
        target = fails.nth(i) if (fail_first and i == 0) else passes.nth(i)
        with page.expect_response(lambda r: "/category/" in r.url and r.request.method == "POST"):
            target.click()


# ── the pass flow: inbox → inspect → sign-off → dispatched + collection PDF ────
def test_qc_pass_flow_dispatches_and_pdf(page: Page, live_server: str, role_users) -> None:
    s = _awaiting_qa_chassis()
    base = live_server
    _open_qc_inbox(page, base, role_users["qc_inspector"])
    cid = s["chassis_id"]
    expect(page.get_by_test_id(f"qc-row-{cid}")).to_be_visible(timeout=T)
    shot(page, "01-inbox", journey=JOURNEY)

    page.get_by_test_id(f"qc-inspect-{cid}").click()
    expect(page.get_by_test_id("qc-form")).to_be_visible(timeout=T)
    _record_all(page)                                   # all categories pass
    shot(page, "02-inspection-all-pass", journey=JOURNEY)

    with page.expect_response(lambda r: "/signoff/" in r.url):
        page.get_by_test_id("qc-signoff").click()

    # outcome: dispatched (DB) + it leaves the inbox + the collection PDF regenerates on demand
    expect(page.get_by_test_id("qc-inbox")).to_be_visible(timeout=T)            # back on the inbox
    expect(page.get_by_test_id(f"qc-row-{cid}")).to_have_count(0)
    assert h.chassis_status(cid) == "dispatched"
    pdf = page.request.get(f"{base}/api/qc/collection-note/{cid}")
    assert pdf.status == 200 and pdf.headers["content-type"].startswith("application/pdf"), pdf.status
    assert pdf.body()[:5] == b"%PDF-"                                           # reportlab really rendered it
    shot(page, "03-dispatched-inbox-clear", journey=JOURNEY)


# ── the fail loop: sign-off FAIL → stays awaiting_qa, the cycle increments ─────
def test_qc_fail_returns_and_increments_cycle(page: Page, live_server: str, role_users) -> None:
    s = _awaiting_qa_chassis()
    base = live_server
    _open_qc_inbox(page, base, role_users["qc_inspector"])
    cid = s["chassis_id"]
    page.get_by_test_id(f"qc-inspect-{cid}").click()
    expect(page.get_by_test_id("qc-form")).to_be_visible(timeout=T)
    _record_all(page, fail_first=True)                  # cat0 fail, the rest pass → overall fail
    with page.expect_response(lambda r: "/signoff/" in r.url):
        page.get_by_test_id("qc-signoff").click()

    # it returns to the inbox (still awaiting_qa) carrying a failed-Nx badge
    expect(page.get_by_test_id(f"qc-row-{cid}")).to_be_visible(timeout=T)
    expect(page.get_by_test_id(f"qc-failed-badge-{cid}")).to_be_visible(timeout=T)
    assert h.chassis_status(cid) == "awaiting_qa"
    shot(page, "04-fail-back-in-inbox", journey=JOURNEY)

    # re-inspection opens cycle 2 — the re-inspection badge shows and the categories reset
    page.get_by_test_id(f"qc-inspect-{cid}").click()
    expect(page.get_by_test_id("qc-reinspection")).to_be_visible(timeout=T)
    shot(page, "05-reinspection-cycle-2", journey=JOURNEY)
