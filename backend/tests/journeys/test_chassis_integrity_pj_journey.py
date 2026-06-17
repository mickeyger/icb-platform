"""WO v4.36a §3.8 — Pre-Job (PJ) chassis-integrity journey.

Locks the §3.3/§3.0 D-VIN rule: strict VIN is enforced at the INTERACTIVE card edit (update_card → 422 on
a bad VIN; a conformant VIN persists). (Propagation + adoption + customer-consistency on the create side
are covered by the AC suite, which shares the chassis_integrity chokepoint.) icb_test (CI); P436A-marked.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import Page

from _common import admin_session
from _v436a import MARK, api_patch, purge, vin


@pytest.fixture(autouse=True)
def _clean():
    purge()
    yield
    purge()


def _draft_card() -> int:
    from app.database import Branch, CalculationRecord, Customer, SessionLocal
    from app.models.mes import PrejobCard, PrejobTemplate
    tag = uuid.uuid4().hex[:6]
    with SessionLocal() as db:
        branch = db.query(Branch).order_by(Branch.id).first()
        cust = db.query(Customer).order_by(Customer.id).first()
        tpl = db.query(PrejobTemplate).filter_by(is_active=True).first()
        calc = CalculationRecord(quote_number=f"{MARK}-{tag}", status="pre_job_sent", branch_id=branch.id,
                                 customer_id=cust.id, dimensions_json='{"body_type": "Chiller"}',
                                 result_json='{"selling_zar": 1000.0}')
        db.add(calc); db.flush()
        card = PrejobCard(calculation_id=calc.id, template_id=(tpl.id if tpl else None),
                          body_description=f"{MARK} card", sections=[{"name": "S", "items": [{"text": "x"}]}],
                          status="draft")
        db.add(card); db.flush()
        cid = card.id
        db.commit()
        return cid


def test_strict_vin_at_interactive_card_edit(page: Page, live_server: str) -> None:
    admin_session(page)
    base = live_server
    cid = _draft_card()
    for bad in ["MICKEYTEST123456", "DEMO5678901234567"]:        # 16-char; 17 with 'O'
        r = api_patch(page, base, f"/api/prejob-cards/{cid}", {"vin_number": bad})
        assert r.status == 422, f"a bad VIN at the card edit must 422, got {r.status}: {r.text()[:200]}"
    r = api_patch(page, base, f"/api/prejob-cards/{cid}", {"vin_number": vin()})
    assert r.status == 200, f"a conformant VIN must persist, got {r.status}: {r.text()[:200]}"
