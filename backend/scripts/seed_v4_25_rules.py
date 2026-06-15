"""WO v4.25 §3.4 — seed the rules engine from the v4.24 spike's geometry + lookup map.

9 bom_rules (the Freezer Vacuum-Materials panel-count formulas, ported 1:1 from the spike's
geometry.py, panel labels carrying the foam/skin layer) + 6 bom_rule_lookups
(spec_to_sap_code: '<material>|<thickness>' → SAP ItemCode, human description in notes). 0
price overrides (intentionally empty). Idempotent: clears the Freezer/Vacuum rows then inserts.

Importable (`seed_rules(db)`) so seed_from_mockup runs it in CI/dev; also runnable:
    python -m backend.scripts.seed_v4_25_rules
"""
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.database import SessionLocal  # noqa: E402
from app.models.mes import BomRule, BomRuleLookup  # noqa: E402

BODY, SECTION = "Freezer", "Vacuum Materials"

# (panel label, formula_expression, priority, notes) — ported from spike geometry.py.
_RULES = [
    ("Roof (foam)",  "ceil((length_mm - 275) / 1220)", 10,
     "Roof EPS foam panel count (VACUUM ORDERS F5). 275mm front+rear frame allowance; 1220mm panel width."),
    ("Floor (foam)", "ceil((length_mm - 275) / 1220)", 20,
     "Floor foam panel count (F7, Freezer path = roof count; dryfreight branch resolved out)."),
    ("Sides (foam)", "ceil((length_mm - 275) / 1220) * 2", 30,
     "Both side walls' foam count (F8, Freezer = roof count x 2; icecream x4 resolved out)."),
    ("Front (foam)", "ceil((width_mm - reveal_side_mm * 2 - 100) / 1220)", 40,
     "Front wall foam count (F9). 100mm clearance; x1 for Freezer."),
    ("Rear (foam)",  "ceil((width_mm - reveal_side_mm * 2 - 99) / 1220)", 50,
     "Rear wall foam count (F11). 99mm clearance (workbook quirk vs front's 100); x1 for Freezer."),
    ("Floor (skin)", "ceil(((length_mm + 50) / 1000 * ((width_mm + 50) / 1000)) "
                     "/ ((1220 / 1000) * (panel_length_mm / 1000)))", 60,
     "Floor plywood skin count (F16, area/sheet). +50mm per-edge overlap."),
    ("Sides (skin)", "ceil(((length_mm + 50) / 1000 * ((height_mm - reveal_top_mm "
                     "- (reveal_top_mm if floor_present else 0) + 50) / 1000)) "
                     "/ ((1220 / 1000) * (panel_length_mm / 1000))) * 2", 70,
     "Both side walls' plywood skin count (F17, area/sheet x2). Inner height less top reveal(s)."),
    ("Front (skin)", "ceil((((width_mm - reveal_side_mm * 2) + 50) / 1000 * ((height_mm - reveal_top_mm "
                     "- (reveal_top_mm if floor_present else 0) + 50) / 1000)) "
                     "/ ((1220 / 1000) * (panel_length_mm / 1000)))", 80,
     "Front wall plywood skin count (F18, area/sheet). Inner width less both side reveals."),
    ("Rear (skin)",  "ceil((width_mm - reveal_side_mm * 2 - 99) / 1220)", 90,
     "Rear wall plywood skin count (F19, panel-width based)."),
]

# (lookup_key '<material>|<thickness>', sap_code, description) — the spike's 6-entry map.
_LOOKUPS = [
    ("EPS 24DV|76", "GRP-MPS-A-0077", "076mm EPS 2440x1220mm 24 DV"),
    ("PU 32DV|56",  "GRP-POL-A-0158", "056mm PU 2440x1220mm 32DV"),
    ("PU 32DV|60",  "GRP-PUS-A-0031", "060mm PU 2440x1220mm 32DV"),
    ("FINN PLY|12", "GRP-TIM-A-0005", "Birch Plywood Uncoated 12mm 2440x1220mm S/BB"),
    ("PLY|4",       "GRP-TIM-A-0007", "Pine Plywood BC 2440x1220x04mm"),
    ("PLY|6",       "GRP-TIM-A-0008", "Pine Plywood BC 2440x1220x06mm"),
]


def seed_rules(db, *, who: str = "seed_v4.25") -> dict:
    """Idempotent: clear Freezer/Vacuum rules + lookups, then insert the 9 + 6."""
    db.query(BomRule).filter_by(body_type=BODY, section=SECTION).delete()
    db.query(BomRuleLookup).filter_by(body_type=BODY, section=SECTION).delete()
    db.flush()
    for panel, expr, prio, notes in _RULES:
        db.add(BomRule(body_type=BODY, section=SECTION, panel=panel, output_field="qty",
                       formula_expression=expr, priority=prio, notes=notes,
                       created_by=who, updated_by=who))
    for key, code, desc in _LOOKUPS:
        db.add(BomRuleLookup(body_type=BODY, section=SECTION, lookup_type="spec_to_sap_code",
                             lookup_key=key, lookup_value=code, notes=desc))
    db.flush()
    return {"bom_rules": len(_RULES), "bom_rule_lookups": len(_LOOKUPS)}


def main():
    from scripts._environment_guard import confirm_if_shared_db
    confirm_if_shared_db("seed_v4_25_rules",
                         destroys="DELETE the Freezer/Vacuum BOM rules + lookups for this section, then re-insert.")
    db = SessionLocal()
    try:
        counts = seed_rules(db)
        db.commit()
        print(f"[seed_v4_25_rules] {counts['bom_rules']} rules + {counts['bom_rule_lookups']} lookups seeded.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
