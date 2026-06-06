"""WO v4.26 §3.4 — seed icb_mes.bom_spec_options for Vacuum Materials × all body types.

The DDM options are field-scoped and largely body-agnostic (the v4.26 pre-flight finding), so they
seed as body_type='*' (the resolver falls back to '*'); body_type itself is the one field whose
options ARE the 8 body types. `sap_code` is NULL throughout: the panel SAP code early-binds at the
(material × thickness) COMBINATION via bom_rule_lookups in the engine, not per single dropdown (ADR
0014) — so there are no per-option codes to orphan-check. Option values extracted once from the
COSTING MODULE 2026 'DDM's & Functions' sheet (hardcoded → CI-safe, no workbook dependency).

Importable (`seed_spec_options(db)`) so seed_from_mockup runs it in CI/dev; also runnable:
    python -m backend.scripts.seed_v4_26_spec_options
"""
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.database import SessionLocal  # noqa: E402
from app.models.mes import BomSpecOption  # noqa: E402

SECTION = "Vacuum Materials"
CROSS = "*"

# spec_field_type -> distinct dropdown option values (from the DDM's & Functions sheet).
_OPTIONS = {
    "roof_material_thickness": ["42", "45", "61", "76", "78", "96", "100", "120"],
    "roof_material": ["EPS 24DV", "PU 32DV", "PU 80DV", "PU 50DV 4G", "MACHINE"],
    "roof_reinforcement": ["None", "4mm Plywood", "6mm Plywood", "9mm Plywood"],
    "roof_recess": ["No", "25", "30", "50"],
    "side_material_thickness": ["16", "18", "20", "21", "42", "45", "51", "56", "60", "61", "91", "100", "120"],
    "side_material": ["EPS 24DV", "PU 32DV", "PU 80DV", "PU 50DV 4G", "MACHINE"],
    "side_reinforcement": ["None", "4mm Plywood", "6mm Plywood", "4mm FINN Plywood", "6mm FINN Plywood"],
    "floor_material_thickness": ["None", "51", "76", "100", "125", "127", "133"],
    "floor_material": ["EPS 24DV", "PU 32DV", "PU 80DV", "PU 50DV 4G", "MACHINE",
                       "N/A - Existing Floor", "3CR12", "3 MSP", "4 MSP", "5 MSP"],
    "floor_plywood": ["None", "6mm Plywood", "9mm Plywood", "12mm Plywood", "18mm Plywood",
                      "9mm Finn", "12mm Finn", "18mm Finn", "21mm Finn", "18mm Wisa", "24mm Wisa", "30mm Wisa"],
    "rear_material_thickness": ["16", "18", "20", "21", "42", "45", "51", "60", "66", "91", "100", "120"],
    "rear_material": ["EPS 24DV", "PU 32DV", "PU 80DV", "PU 50DV 4G", "MACHINE"],
    "rear_reinforcement": ["None", "4mm Plywood", "6mm Plywood", "4mm FINN Plywood", "6mm FINN Plywood"],
    "partition_material_thickness": ["No", "32", "45", "60"],
    "partition_material": ["No", "EPS 24DV", "PU 50DV 4G", "PU 32DV"],
    "body_spec": ["Standard", "Machine Build", "Rhinorange", "Ultralight"],
}

# body_type field — its options ARE the 8 body types. Explosive is "NOT AVAILABLE" → active=False.
_BODY_TYPES = ["Freezer", "Chiller", "Dryfreight", "Insulated Trailer", "Carcass", "Hatchery", "Icecream"]
_BODY_TYPES_INACTIVE = ["Explosive"]


def seed_spec_options(db, *, who: str = "seed_v4.26") -> dict:
    """Idempotent: clear the Vacuum Materials spec options, then insert the catalogue."""
    db.query(BomSpecOption).filter_by(section=SECTION).delete()
    db.flush()
    n = 0
    for field, values in _OPTIONS.items():
        for i, val in enumerate(values):
            db.add(BomSpecOption(spec_field_type=field, body_type=CROSS, section=SECTION,
                                 option_label=val, spec_value=val, sap_code=None,
                                 is_default=(i == 0), priority=100 + i, active=True,
                                 created_by=who, updated_by=who))
            n += 1
    for i, bt in enumerate(_BODY_TYPES):
        db.add(BomSpecOption(spec_field_type="body_type", body_type=CROSS, section=SECTION,
                             option_label=bt, spec_value=bt, is_default=(bt == "Freezer"),
                             priority=100 + i, active=True, created_by=who, updated_by=who))
        n += 1
    for bt in _BODY_TYPES_INACTIVE:
        db.add(BomSpecOption(spec_field_type="body_type", body_type=CROSS, section=SECTION,
                             option_label=f"{bt} (NOT AVAILABLE)", spec_value=bt, active=False,
                             priority=900, notes="Marked NOT AVAILABLE in the Costing Module DDM.",
                             created_by=who, updated_by=who))
        n += 1
    db.flush()
    by_field = {f: len(v) for f, v in _OPTIONS.items()}
    by_field["body_type"] = len(_BODY_TYPES) + len(_BODY_TYPES_INACTIVE)
    return {"total": n, "by_field": by_field}


def main():
    db = SessionLocal()
    try:
        rep = seed_spec_options(db)
        db.commit()
        print(f"[seed_v4_26_spec_options] {rep['total']} options seeded across "
              f"{len(rep['by_field'])} spec_field_types.")
        for f, c in rep["by_field"].items():
            print(f"  {f:<30} {c}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
