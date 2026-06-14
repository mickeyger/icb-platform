"""WO v4.33.1 §3.4 — seed the Medical Waste Pre-Job Card template (8th product class).

Nadie Q16: Medical Waste is the 8th body class — HazChem regulatory equipment, same equipment pack
as Explosive. No Word doc was provided, so this is created FROM the Explosive Body base: the
sections + header are copied with "Explosive" → "Medical Waste" text swaps, and the template is
seeded as a DRAFT (is_active=False) for Nadie to review the section copy before activation (admin
approve flips is_active). Idempotent on the unique name. Template count 22 → 23.

    python -m scripts.seed_medical_waste_template
"""
from __future__ import annotations

import copy
import sys

_NAME = "Medical Waste Body"
_BASE_NAME = "Explosive Body"


def _swap(s):
    """"Explosive" → "Medical Waste" across the three casings the templates use."""
    if not isinstance(s, str):
        return s
    return (s.replace("EXPLOSIVE", "MEDICAL WASTE")
             .replace("Explosive", "Medical Waste")
             .replace("explosive", "medical waste"))


def _swap_sections(sections):
    out = copy.deepcopy(sections or [])
    for sec in out:
        if not isinstance(sec, dict):
            continue
        sec["name"] = _swap(sec.get("name"))
        for item in sec.get("items", []):
            if not isinstance(item, dict):
                continue
            item["text"] = _swap(item.get("text"))
            if item.get("note"):
                item["note"] = _swap(item["note"])
            if item.get("sub_items"):
                item["sub_items"] = [_swap(s) for s in item["sub_items"]]
    return out


def seed() -> dict:
    from app.database import SessionLocal
    from app.models.mes import PrejobTemplate
    with SessionLocal() as db:
        if db.query(PrejobTemplate).filter_by(name=_NAME).first() is not None:
            return {"created": 0, "skipped": 1, "reason": "already exists"}
        base = (db.query(PrejobTemplate).filter_by(name=_BASE_NAME).first()
                or db.query(PrejobTemplate).filter_by(body_type="explosive").first())
        if base is None:
            return {"created": 0, "skipped": 0, "reason": "no base"}   # CI's fresh DB has no templates
        tpl = PrejobTemplate(
            name=_NAME,
            body_type="medical_waste",                     # the model's reserved 8th class
            size_category=base.size_category,
            product_line=base.product_line,
            header_format=_swap(base.header_format),
            sections=_swap_sections(base.sections),
            default_fridge_note=base.default_fridge_note,
            is_active=False,                               # DRAFT — Nadie reviews the copy before activation
            created_by="seed-medical-waste-v4331",
        )
        db.add(tpl)
        db.commit()
    return {"created": 1, "skipped": 0}


if __name__ == "__main__":
    print(seed())
    sys.exit(0)
