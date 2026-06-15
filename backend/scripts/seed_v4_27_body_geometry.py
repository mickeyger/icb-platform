"""WO v4.27 §3.2 — seed per-body-type Vacuum-Materials geometry for the 7 non-Freezer bodies.

Derived 1:1 from the Freezer rules (seed_v4_25_rules._RULES) per the COSTING MODULE 2026.xlsx
VACUUM ORDERS formula evidence. In the foam (rows 5-12) + plywood-skin (rows 15-20) scope, the
ONLY body-type branches are:
  * Dryfreight  — no insulated floor foam   (F7: IF(body="dryfreight","- -",F5))
  * Icecream    — double walls: side foam x4, front/rear foam x2  (F8/F9/F11 icecream branch)
Chiller / Carcass / Insulated Trailer / Hatchery have NO branch in that scope → identical to
Freezer geometry (their differences live in the LVL-beam section, which is not Vacuum Materials).
Explosive is "NOT AVAILABLE" (§0.1) → structural-only, no geometry rules.

Lookups: each body type gets the same baseline (material|thickness)->SAP-code combos as Freezer
(the body-agnostic default panel combos). These are refined per body type when Nadie's oracle
snapshots arrive (v4.27.1). Explosive gets none.

Idempotent (clears each body_type+section then inserts). Importable (`seed_body_geometry(db)`) so
seed_from_mockup runs it in CI/dev; also runnable:
    python -m backend.scripts.seed_v4_27_body_geometry
"""
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.database import SessionLocal  # noqa: E402
from app.models.mes import BomRule, BomRuleLookup  # noqa: E402
from scripts.seed_v4_25_rules import (  # noqa: E402  (single source of truth for the Freezer base)
    _LOOKUPS as _FREEZER_LOOKUPS,
    _RULES as _FREEZER_RULES,
    SECTION,
)


def _icecream_rules():
    """Freezer rules with the icecream double-wall multipliers (VACUUM ORDERS F8/F9/F11)."""
    out = []
    for panel, expr, prio, notes in _FREEZER_RULES:
        if panel == "Sides (foam)":
            expr = "ceil((length_mm - 275) / 1220) * 4"
            notes = "Icecream double-wall — side foam x4 (VACUUM ORDERS F8 icecream branch)."
        elif panel == "Front (foam)":
            expr = "ceil((width_mm - reveal_side_mm * 2 - 100) / 1220) * 2"
            notes = "Icecream double-wall — front foam x2 (F9 icecream branch)."
        elif panel == "Rear (foam)":
            expr = "ceil((width_mm - reveal_side_mm * 2 - 99) / 1220) * 2"
            notes = "Icecream double-wall — rear foam x2 (F11 icecream branch)."
        out.append((panel, expr, prio, notes))
    return out


def _dryfreight_rules():
    """Freezer rules minus Floor (foam) — dryfreight has no insulated floor (F7 -> "- -")."""
    return [r for r in _FREEZER_RULES if r[0] != "Floor (foam)"]


# body_type -> its Vacuum-Materials geometry rules
_BODY_RULES = {
    "Chiller":            list(_FREEZER_RULES),
    "Carcass":            list(_FREEZER_RULES),
    "Insulated Trailer":  list(_FREEZER_RULES),
    "Hatchery":           list(_FREEZER_RULES),
    "Dryfreight":         _dryfreight_rules(),
    "Icecream":           _icecream_rules(),
    "Explosive":          [],   # NOT AVAILABLE (§0.1) — structural-only, intentionally empty
}


def seed_body_geometry(db, *, who: str = "seed_v4.27") -> dict:
    """Idempotent per body type: clear its Vacuum rules + lookups, then insert the derived set."""
    counts = {}
    for body, rules in _BODY_RULES.items():
        db.query(BomRule).filter_by(body_type=body, section=SECTION).delete()
        db.query(BomRuleLookup).filter_by(body_type=body, section=SECTION).delete()
        db.flush()
        for panel, expr, prio, notes in rules:
            db.add(BomRule(body_type=body, section=SECTION, panel=panel, output_field="qty",
                           formula_expression=expr, priority=prio, notes=notes,
                           created_by=who, updated_by=who))
        if rules:   # baseline default combos (refined per body type when oracles land); none for Explosive
            for key, code, desc in _FREEZER_LOOKUPS:
                db.add(BomRuleLookup(body_type=body, section=SECTION, lookup_type="spec_to_sap_code",
                                     lookup_key=key, lookup_value=code, notes=desc))
        db.flush()
        counts[body] = len(rules)
    return counts


def main():
    from scripts._environment_guard import confirm_if_shared_db
    confirm_if_shared_db("seed_v4_27_body_geometry",
                         destroys="DELETE each body type's Vacuum BOM rules + lookups, then re-insert the derived set.")
    db = SessionLocal()
    try:
        counts = seed_body_geometry(db)
        db.commit()
        total = sum(counts.values())
        print(f"[seed_v4_27_body_geometry] {total} rules across {len(counts)} body types: {counts}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
