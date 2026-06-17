"""WO v4.36a §3.8 — Planning-Ack (AJ) chassis-integrity journey.

Locks the §3.4 fixes: a VIN that CLASHES with the linked chassis's existing VIN at ack → 409 (the
silent-swallow is gone); a bad-format VIN at ack → 422; a non-dealer dealer_id → 422. icb_test (CI);
P436A-marked.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import Page

from _common import admin_session
from _v436a import MARK, api_post, purge, vin


@pytest.fixture(autouse=True)
def _clean():
    purge()
    yield
    purge()


def _confirmed_job(*, chassis_vin: "str | None") -> int:
    """A pre_job_confirmed job whose linked chassis carries `chassis_vin` (or NULL). Returns job_id."""
    from app.database import Branch, CalculationRecord, Customer, SessionLocal
    from app.models.mes import ChassisRecord, ProductionJob
    tag = uuid.uuid4().hex[:6]
    with SessionLocal() as db:
        branch = db.query(Branch).order_by(Branch.id).first()
        cust = db.query(Customer).order_by(Customer.id).first()
        calc = CalculationRecord(quote_number=f"{MARK}-{tag}", status="pre_job_confirmed", branch_id=branch.id,
                                 customer_id=cust.id, dimensions_json='{"body_type": "Chiller"}',
                                 result_json='{"selling_zar": 1000.0}')
        db.add(calc); db.flush()
        ch = ChassisRecord(make=f"{MARK} Test", model="X", vin=chassis_vin, status="expected", source="manual",
                           created_via="pre_job_card", created_by="t")
        db.add(ch); db.flush()
        job = ProductionJob(calculation_record_id=calc.id, branch_id=branch.id, status="pre_job_confirmed",
                            job_number=f"{MARK}{tag}", chassis_record_id=ch.id, source="quote")
        db.add(job); db.flush()
        jid = job.id
        db.commit()
        return jid


def test_ack_vin_clash_409_no_silent_swallow(page: Page, live_server: str) -> None:
    admin_session(page)
    base = live_server
    job_id = _confirmed_job(chassis_vin=vin())                # chassis already has a (different) VIN
    r = api_post(page, base, f"/api/production-jobs/{job_id}/planning-ack", {"chassis_vin": vin()})
    assert r.status == 409, f"a VIN clash at ack must 409 (no silent swallow), got {r.status}: {r.text()[:200]}"


def test_ack_vin_format_422(page: Page, live_server: str) -> None:
    admin_session(page)
    base = live_server
    job_id = _confirmed_job(chassis_vin=None)                 # NULL VIN → ack would set it
    r = api_post(page, base, f"/api/production-jobs/{job_id}/planning-ack", {"chassis_vin": "MICKEYTEST123456"})
    assert r.status == 422, f"a bad-format VIN at ack must 422, got {r.status}: {r.text()[:200]}"


def test_ack_dealer_validation_422(page: Page, live_server: str) -> None:
    admin_session(page)
    base = live_server
    job_id = _confirmed_job(chassis_vin=None)
    r = api_post(page, base, f"/api/production-jobs/{job_id}/planning-ack", {"dealer_id": 999999999})
    assert r.status == 422, f"a non-dealer dealer_id at ack must 422, got {r.status}: {r.text()[:200]}"
