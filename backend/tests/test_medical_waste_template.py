"""WO v4.33.1 §3.4 — the Medical Waste Pre-Job Card template seed (from the Explosive base, draft)."""
import json

import pytest


def test_medical_waste_template_seed():
    from app.database import SessionLocal
    from app.models.mes import PrejobTemplate
    from scripts.seed_medical_waste_template import seed
    r = seed()                                             # idempotent — skips if it already exists
    if r.get("reason") == "no base":
        pytest.skip("no Explosive base template on this DB (CI's fresh DB has no templates)")
    with SessionLocal() as db:
        tpl = db.query(PrejobTemplate).filter_by(name="Medical Waste Body").first()
        assert tpl is not None
        assert tpl.body_type == "medical_waste"            # the 8th class
        assert tpl.is_active is False                      # DRAFT — Nadie reviews before activation
        assert tpl.sections                                # sections copied from the Explosive base
        blob = json.dumps(tpl.sections) + (tpl.header_format or "")
        assert "Explosive" not in blob and "Medical Waste" in blob   # "Explosive" → "Medical Waste" swap
