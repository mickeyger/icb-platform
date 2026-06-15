"""WO v4.33 scope addition — seed icb_mes.fridge_units from Standard Drawing FRIDGE MOUNTING A.

30 rows / 8 manufacturers, transcribed from the Drawing-A cutout table (Front Mount — the
most common style; drawings B/D/F/G/H are the v4.33.1 enhancement). Data oddities kept
verbatim for fidelity: Thermoking V300 height 50, Corunclima width-only (height NULL).
The drawing's "Carier" spelling is normalized to Carrier. Idempotent: existing
(manufacturer, model) rows are skipped.

    python -m scripts.seed_fridge_units [--deactivate-missing]
"""
from __future__ import annotations

import sys

# (manufacturer, model, cutout_width_mm, cutout_height_mm) — Drawing A, sheet 17/132.
DRAWING_A_ROWS = [
    ("Transfrig", "KV 560", 780, 320),
    ("Transfrig", "KV 660i", 780, 320),
    ("Transfrig", "KV 760i", 1250, 325),
    ("Transfrig", "KV 860i", 1250, 325),
    ("Transfrig", "MT 300/310i", 1250, 325),
    ("Transfrig", "MT 450/460i", 1250, 350),
    ("Transfrig", "MT 650/660i", 1420, 350),
    ("Thermoking", "MD 100 / 200 / 300", 1240, 312),
    ("Thermoking", "T500/T560", 1240, 312),
    ("Thermoking", "T600", 1240, 350),
    ("Thermoking", "T800", 1240, 350),
    ("Thermoking", "T1000", 1240, 350),
    ("Thermoking", "T1200", 1240, 350),
    ("Thermoking", "V300", 905, 50),
    ("Mitsubishi", "TNW 8/7 EA", 1230, 335),
    ("Mitsubishi", "TNW 6 EA", 1230, 335),
    ("Mitsubishi", "TNW5EA", 1240, 310),
    ("Carrier", "Oasis 150", 1245, 310),
    ("Carrier", "Oasis 250", 1245, 310),
    ("Carrier", "Supra 550", 1245, 310),
    ("Carrier", "Supra 750", 1245, 310),
    ("Carrier", "Supra 850", 1245, 350),
    ("Carrier", "Supra 950", 1245, 350),
    ("Carrier", "Supra 1050", 1245, 350),
    ("Carrier", "Supra 1150", 1245, 350),
    ("Carrier", "Supra 1250", 1245, 350),
    ("Hatchery ICB", "Adjustable", 1610, 605),
    ("Tundra", "SKD 1000", 1245, 350),
    ("Unknown", "", 1255, 355),
    ("Corunclima", "", 770, None),
]


def seed() -> dict:
    from app.database import SessionLocal
    from app.models.mes import FridgeUnit
    created = skipped = 0
    with SessionLocal() as db:
        for manufacturer, model, w, h in DRAWING_A_ROWS:
            exists = db.query(FridgeUnit).filter_by(manufacturer=manufacturer,
                                                    model=model).first()
            if exists is not None:
                skipped += 1
                continue
            display = f"{manufacturer} {model}".strip() if model else (
                f"{manufacturer} (generic)" if manufacturer == "Unknown" else manufacturer)
            db.add(FridgeUnit(manufacturer=manufacturer, model=model, display_name=display,
                              mounting_drawing="A", cutout_width_mm=w, cutout_height_mm=h,
                              created_by="seed-drawing-a"))
            created += 1
        db.commit()
    return {"created": created, "skipped": skipped, "total": len(DRAWING_A_ROWS)}


if __name__ == "__main__":
    from scripts._environment_guard import announce_target   # additive: insert-when-(manufacturer,model)-absent
    announce_target("seed_fridge_units")
    print(seed())
    sys.exit(0)
