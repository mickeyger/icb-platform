"""WO v4.38 — Feedback Portal journey: submit a report → it lands in the admin inbox.

The feedback_submissions migration (0027) is HELD pending CA1's v4.36b 0026 (WO v4.38 §3.0),
so this test create_all's the one table itself (checkfirst — idempotent with the future
migration, which is inspector-guarded). Runs in CI's "Journey tests" step against icb_test
(per ADR 0011); collects green locally even where icb_test isn't provisionable.

Deterministic across AI states: when ANTHROPIC_API_KEY is unset (the CI default) the classifier
no-ops and the widget goes straight to the thank-you; when it's set, clarifying questions appear
first and the test skips them. Either way the verbatim report must reach the inbox.
"""
import pytest

from _common import admin_session, shot

JOURNEY = "feedback_portal"
REPORT = "Journey test — the planning board did not refresh after I merged a job."


@pytest.fixture(scope="module", autouse=True)
def _feedback_table(live_server):
    """Create the held-migration table so the journey can run end-to-end, then drop it IFF we
    created it. The conditional teardown keeps isolation clean while 0027 is held — no residue to
    skew the icb_mes table-count smoke test (test_smoke.py) regardless of CI step order — AND is a
    no-op once 0027 is applied (the migration owns the table then; we must not drop it).
    See WO v4.38 §3.0 + ci-test-isolation-teardown."""
    from sqlalchemy import inspect as sa_inspect
    from app.database import engine
    from app.models.mes import FeedbackSubmission
    created_here = "feedback_submissions" not in sa_inspect(engine).get_table_names(schema="icb_mes")
    if created_here:
        FeedbackSubmission.__table__.create(engine, checkfirst=True)
    yield
    if created_here:
        FeedbackSubmission.__table__.drop(engine, checkfirst=True)


def test_feedback_submit_to_admin_triage_audit(page):
    admin_session(page)

    # 1. Open the global widget (it's mounted in Layout, so present on every /mes-app screen).
    page.click("[data-testid='feedback-launcher']")
    page.wait_for_selector("[data-testid='feedback-modal']")
    page.fill("[data-testid='feedback-text']", REPORT)
    shot(page, "01-report-form", JOURNEY)
    page.click("[data-testid='feedback-submit']")

    # 2. Resolve to either the clarifying-questions step (AI on) or the thank-you (AI off).
    page.wait_for_selector(
        "[data-testid='feedback-clarify'], [data-testid='feedback-done']", timeout=30_000
    )
    if page.locator("[data-testid='feedback-clarify']").count():
        page.click("[data-testid='feedback-skip']")
    page.wait_for_selector("[data-testid='feedback-done']")
    shot(page, "02-thank-you", JOURNEY)

    # 3. The ticket is now in the admin inbox; the most-recent row carries our verbatim report.
    page.goto("/mes-app/admin/feedback")
    page.wait_for_selector("[data-testid='feedback-inbox']")
    page.wait_for_selector("[data-testid^='feedback-row-']", timeout=15_000)
    page.locator("[data-testid^='feedback-row-']").first.click()
    page.wait_for_selector("[data-testid='feedback-detail']")
    detail_text = page.locator("[data-testid='feedback-detail']").inner_text()
    assert "planning board did not refresh" in detail_text
    shot(page, "03-admin-inbox", JOURNEY)

    # 4. The audit timeline shows the initial 'submitted' entry (WO v4.38 W2 lifecycle).
    page.wait_for_selector("[data-testid='feedback-history']")
    assert "Submitted" in page.locator("[data-testid='feedback-history']").inner_text()

    # 5. An admin triaging the ticket (status -> in_progress) records the transition in the audit trail.
    page.select_option("[data-testid='feedback-status-select']", "in_progress")
    page.wait_for_selector(
        "[data-testid='feedback-history']:has-text('In progress')", timeout=15_000
    )
    shot(page, "04-lifecycle-audit", JOURNEY)
