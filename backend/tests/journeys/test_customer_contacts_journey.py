"""WO v4.34.1 §3.6 — Customers admin Contacts panel (journey).

Admin searches the 2160-row list, opens a customer, adds a contact, makes it primary, then
soft-deletes it. Admin-only surface (the module gates on isAdmin). J341C marker customer — created
+ purged here, so no real icb_costings customer is touched.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from _common import admin_session, shot  # noqa: E402

T = 15_000
JOURNEY = "customer_contacts"


def _purge(db) -> None:
    from sqlalchemy import text
    db.execute(text("DELETE FROM icb_costings.customer_contacts cc USING icb_costings.customers c "
                    "WHERE cc.customer_id = c.id AND c.name LIKE 'J341C%'"))
    db.execute(text("DELETE FROM icb_costings.customers WHERE name LIKE 'J341C%'"))
    db.commit()


@pytest.fixture()
def test_customer():
    from app.database import Customer, SessionLocal
    with SessionLocal() as db:
        _purge(db)
        c = Customer(name="J341C Test Customer", bp_code="J341C001", is_active=True, is_dealer=False)
        db.add(c)
        db.commit()
        cid = c.id
    yield cid
    from app.database import SessionLocal as SL
    with SL() as db:
        _purge(db)


def test_admin_manages_contacts(page: Page, test_customer) -> None:
    admin_session(page)
    with page.expect_response(lambda r: "/api/customers" in r.url, timeout=30_000):
        page.goto("/mes-app/admin/customers")
    expect(page.get_by_test_id("admin-customers")).to_be_visible(timeout=T)
    # search → the marker customer
    page.get_by_test_id("customers-search").fill("J341C")
    row = page.locator(f"[data-testid=customer-row][data-id='{test_customer}']")
    expect(row).to_be_visible(timeout=T)
    row.click()
    expect(page.get_by_test_id("contacts-panel")).to_be_visible(timeout=T)
    shot(page, "01-customer-detail", journey=JOURNEY)

    # add a contact
    page.get_by_test_id("contact-add").click()
    page.get_by_test_id("contact-add-name").fill("Nadie (J341C)")
    page.get_by_test_id("contact-add-email").fill("nadie@j341c.co")
    with page.expect_response(lambda r: r.url.endswith(f"/customers/{test_customer}/contacts")
                              and r.request.method == "POST", timeout=T) as ri:
        page.get_by_test_id("contact-add-save").click()
    assert ri.value.status == 200, f"add contact returned {ri.value.status}"
    contact_row = page.get_by_test_id("contact-row").first
    expect(contact_row).to_contain_text("Nadie (J341C)", timeout=T)

    # make it the primary contact
    with page.expect_response(lambda r: "/set-primary" in r.url and r.request.method == "POST", timeout=T):
        page.get_by_test_id("contact-set-primary").first.click()
    expect(page.get_by_test_id("contact-primary-star").first).to_be_visible(timeout=T)
    shot(page, "02-contact-primary", journey=JOURNEY)

    # soft-delete → drops out of the active list
    with page.expect_response(lambda r: "/contacts/" in r.url and r.request.method == "DELETE", timeout=T):
        page.get_by_test_id("contact-delete").first.click()
    expect(page.get_by_test_id("contact-row")).to_have_count(0, timeout=T)
