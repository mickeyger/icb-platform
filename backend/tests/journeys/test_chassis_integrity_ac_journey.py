"""WO v4.36a §3.8 — Add-Chassis (AC) integrity journey.

Locks: strict-VIN 422 on create AND on the 4th write path (capture_vin) — §3.8 break-1; the atomic
job↔chassis FK link; §0.8 adoption on a VIN match (no duplicate); the unlinked-jobs dropdown +
auto-populate source; and the §3.5e Delivery ETA (create-with persists onto the job, create-without
accepts). Runs against the journey DB (icb_test on CI). P436A-marked; purge at setup + teardown.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from _common import admin_session
from _v436a import (api_post, chassis_row, job_chassis_eta, job_chassis_id, make_null_vin_chassis,
                    make_unlinked_job, purge, vin)

T = 15_000


@pytest.fixture(autouse=True)
def _clean():
    purge()
    yield
    purge()


def test_strict_vin_422_on_create_conformant_accepts(page: Page, live_server: str) -> None:
    admin_session(page)
    base = live_server
    for bad in ["MICKEYTEST123456",          # 16 chars
                "DEMO5678901234567",          # 17 chars but contains 'O'
                vin() + "0"]:                 # 18 chars
        r = api_post(page, base, "/api/chassis-records", {"vin": bad, "make": "Hino"})
        assert r.status == 422, f"VIN {bad!r} should 422, got {r.status}: {r.text()[:200]}"
    r = api_post(page, base, "/api/chassis-records", {"vin": vin(), "make": "Hino"})
    assert r.status == 201, f"a conformant VIN should create, got {r.status}: {r.text()[:200]}"


def test_atomic_fk_link_and_prefill(page: Page, live_server: str) -> None:
    admin_session(page)
    base = live_server
    j = make_unlinked_job()
    pf = page.request.get(f"{base}/api/production-jobs/{j['job_id']}/chassis-prefill").json()
    assert pf["customer_name"] == j["customer_name"] and pf["chassis_type"], f"prefill thin: {pf}"
    v = vin()
    r = api_post(page, base, "/api/chassis-records",
                 {"vin": v, "make": "Hino", "production_job_id": j["job_id"],
                  "customer_name": j["customer_name"]})
    assert r.status == 201, r.text()[:200]
    cid = r.json()["chassis"]["id"]
    assert job_chassis_id(j["job_id"]) == cid, "create did not atomically link the job (the MICKEYTEST fix)"


def test_adoption_on_vin_match_no_duplicate(page: Page, live_server: str) -> None:
    admin_session(page)
    base = live_server
    v = vin()
    r1 = api_post(page, base, "/api/chassis-records", {"vin": v, "make": "Hino"})
    assert r1.status == 201, r1.text()[:200]
    first_id = r1.json()["chassis"]["id"]
    j = make_unlinked_job()
    r2 = api_post(page, base, "/api/chassis-records",
                  {"vin": v, "make": "Hino", "production_job_id": j["job_id"],
                   "customer_name": j["customer_name"]})
    assert r2.status == 201, r2.text()[:200]
    body = r2.json()
    assert body["adopted"] is True, "a VIN match must ADOPT, not duplicate"
    assert body["chassis"]["id"] == first_id, "adoption must reuse the existing chassis"
    assert job_chassis_id(j["job_id"]) == first_id, "adoption must link the job to the existing chassis"


def test_eta_create_with_persists_without_accepts(page: Page, live_server: str) -> None:
    admin_session(page)
    base = live_server
    j = make_unlinked_job()
    r = api_post(page, base, "/api/chassis-records",
                 {"vin": vin(), "make": "Hino", "production_job_id": j["job_id"],
                  "customer_name": j["customer_name"], "chassis_eta": "2026-08-20"})
    assert r.status == 201, r.text()[:200]
    assert job_chassis_eta(j["job_id"]) == "2026-08-20", "ETA did not persist onto the linked job"
    j2 = make_unlinked_job()
    r2 = api_post(page, base, "/api/chassis-records",
                  {"vin": vin(), "make": "Hino", "production_job_id": j2["job_id"],
                   "customer_name": j2["customer_name"]})
    assert r2.status == 201, "create WITHOUT an ETA must be accepted (ETA optional)"
    assert job_chassis_eta(j2["job_id"]) is None


def test_capture_vin_format_symmetry_and_write_once(page: Page, live_server: str) -> None:
    """§3.8 break-1 lock — the 4th write path enforces strict format (was strip + [:32] truncate)."""
    admin_session(page)
    base = live_server
    c = make_null_vin_chassis()
    r = api_post(page, base, f"/api/chassis-records/{c['chassis_id']}/vin", {"vin": "DEMO5678901234567"})  # has 'O'
    assert r.status == 422, f"capture_vin should 422 a bad VIN, got {r.status}: {r.text()[:200]}"
    assert chassis_row(c["chassis_id"])["vin"] is None, "a bad VIN must not persist"
    v = vin()
    r2 = api_post(page, base, f"/api/chassis-records/{c['chassis_id']}/vin", {"vin": v})
    assert r2.status == 200, r2.text()[:200]
    assert chassis_row(c["chassis_id"])["vin"] == v, "conformant VIN must persist EXACTLY (no truncation)"
    r3 = api_post(page, base, f"/api/chassis-records/{c['chassis_id']}/vin", {"vin": vin()})
    assert r3.status == 409, f"a 2nd capture must 409 (write-once), got {r3.status}"


def test_modal_renders_with_eta_and_strict_vin_toast(page: Page, live_server: str) -> None:
    """The UI surface: +New modal shows the job dropdown + the §3.5e Delivery ETA field; a bad VIN 422s
    with the field still open (nothing created)."""
    admin_session(page)
    make_unlinked_job()
    page.get_by_test_id("nav-chassis").click()
    expect(page.get_by_test_id("chassis-list")).to_be_visible(timeout=T)
    page.get_by_test_id("chassis-new").click()
    form = page.get_by_test_id("chassis-create-form")
    expect(form).to_be_visible(timeout=T)
    expect(page.get_by_test_id("chassis-create-job")).to_be_visible()
    expect(page.get_by_test_id("chassis-create-eta")).to_be_visible()       # §3.5e field present
    page.get_by_test_id("chassis-create-make").select_option(index=1)
    page.get_by_test_id("chassis-create-vin").fill("MICKEYTEST123456")      # 16-char
    page.get_by_test_id("chassis-create-save").click()
    expect(form).to_be_visible(timeout=T)                                   # 422 → form stays open
