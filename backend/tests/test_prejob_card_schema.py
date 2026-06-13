"""WO v4.33 §3.1 — migration 0017 artifacts: prejob tables + FKs, sales_rep_user_id on
calculations, chassis body_gap_mm (+ the VCL write-through), and the permission seeds.

Inspector-based artifact checks (the migration ran via alembic; CI's round-trip covers
up/down/up) + an ORM round-trip exercising the §0.5 JSONB shape (sections with notes,
sub_items, and the §0.10 sap_item_code stub). P433* marker rows with the self-healing purge
at setup AND teardown (ADR 0019 footnote 1/4).
"""
from datetime import date

import pytest
from sqlalchemy import inspect as sa_inspect


def _purge(db) -> None:
    from sqlalchemy import text
    db.execute(text("DELETE FROM icb_mes.prejob_cards WHERE body_description LIKE 'P433%'"))
    db.execute(text("DELETE FROM icb_mes.prejob_templates WHERE name LIKE 'P433%'"))
    db.execute(text("DELETE FROM icb_mes.chassis_lifecycle_events WHERE chassis_record_id IN "
                    "(SELECT id FROM icb_mes.chassis_records WHERE vin LIKE 'P433%')"))
    db.execute(text("DELETE FROM icb_mes.chassis_records WHERE vin LIKE 'P433%'"))
    db.commit()


@pytest.fixture
def db():
    from app.database import SessionLocal
    with SessionLocal() as session:
        _purge(session)
        try:
            yield session
        finally:
            _purge(session)


def test_migration_0017_artifacts(db):
    bind = db.get_bind()
    insp = sa_inspect(bind)
    mes_tables = set(insp.get_table_names(schema="icb_mes"))
    assert {"prejob_templates", "prejob_cards"} <= mes_tables

    tpl_cols = {c["name"] for c in insp.get_columns("prejob_templates", schema="icb_mes")}
    assert {"body_type", "size_category", "name", "product_line", "header_format",
            "sections", "default_fridge_note", "is_active", "version"} <= tpl_cols

    card_cols = {c["name"] for c in insp.get_columns("prejob_cards", schema="icb_mes")}
    assert {"calculation_id", "template_id", "body_description", "chassis_make_model",
            "vin_number", "body_gap_mm", "body_gap_pending", "sections",
            "fridge_ordering_mode", "fridge_model", "customer_notes",
            "created_by_user_id", "sales_rep_user_id", "sales_rep_signoff_at",
            "sales_rep_attestation", "planner_user_id", "planner_signoff_at",
            "planner_attestation", "status", "sent_for_check_at", "reject_reason",
            "pdf_file_id", "version"} <= card_cols

    # Cross-schema FKs created by name (the 0003/0012/0016 idiom).
    card_fks = {fk["name"] for fk in insp.get_foreign_keys("prejob_cards", schema="icb_mes")}
    assert {"fk_prejob_cards_calculation", "fk_prejob_cards_created_by",
            "fk_prejob_cards_sales_rep", "fk_prejob_cards_planner"} <= card_fks

    # §0.13 — calculations.sales_rep_user_id + its FK.
    calc_cols = {c["name"] for c in insp.get_columns("calculations", schema="icb_costings")}
    assert "sales_rep_user_id" in calc_cols
    calc_fks = {fk["name"] for fk in insp.get_foreign_keys("calculations", schema="icb_costings")}
    assert "fk_calculations_sales_rep_user" in calc_fks

    # §0.8 — chassis_records.body_gap_mm.
    ch_cols = {c["name"] for c in insp.get_columns("chassis_records", schema="icb_mes")}
    assert "body_gap_mm" in ch_cols


def test_permission_seeds_and_grants(db):
    from sqlalchemy import text
    perms = {r[0] for r in db.execute(text(
        "SELECT name FROM icb_costings.permissions WHERE name LIKE 'prejob.%'")).all()}
    assert perms == {"prejob.create", "prejob.signoff_sales", "prejob.signoff_planner"}
    grants = {(r[0], r[1]) for r in db.execute(text(
        "SELECT rp.role, p.name FROM icb_costings.role_permissions rp "
        "JOIN icb_costings.permissions p ON p.id = rp.permission_id "
        "WHERE p.name LIKE 'prejob.%'")).all()}
    assert ("sales", "prejob.create") in grants
    assert ("sales", "prejob.signoff_sales") in grants
    assert ("planner", "prejob.signoff_planner") in grants
    # §0.3 — production deliberately has NO prejob grant (separation of duties).
    assert not any(role == "production" for role, _ in grants)


def test_template_and_card_jsonb_roundtrip(db):
    """The §0.5 shape survives an ORM round-trip: sections with items carrying note,
    sub_items (the HazChem pack pattern), and the §0.10 sap_item_code stub."""
    from app.database import CalculationRecord
    from app.models.mes import PrejobCard, PrejobTemplate

    sections = [
        {"name": "GRP SECTION", "items": [
            {"text": "External dimensions: 5 500mm o/a (l) x 2 300mm (w) x 2 300mm (h)"},
            {"text": "Sides, front, rear + roof 50mm - 1 x Rhinotex ext.",
             "note": "Rear will be solid panel"},
        ]},
        {"name": "SUB FRAME SECTION", "items": [
            {"text": "Body Gap - 120mm", "sap_item_code": None},
        ]},
        {"name": "FINISHING SECTION", "items": [
            {"text": "Fit complete Hazchem with extra 2.5kg Fire Extinguisher.",
             "sub_items": ["Orange warning diamond metal plate", "Orange document box",
                           "2 x 9kg DCP STP Fire Extinguisher"]},
        ]},
    ]
    tpl = PrejobTemplate(body_type="explosive", size_category="std", name="P433 TEST TEMPLATE",
                         product_line="standard", header_format="{size}mm GRP Explosive Body",
                         sections=sections)
    db.add(tpl)
    db.flush()

    calc = db.query(CalculationRecord).order_by(CalculationRecord.id).first()
    if calc is None:
        pytest.skip("no calculations on this DB to FK against")
    card = PrejobCard(calculation_id=calc.id, template_id=tpl.id,
                      body_description="P433 TEST CARD", sections=sections,
                      fridge_ordering_mode="none")
    db.add(card)
    db.commit()
    db.refresh(card)

    assert card.status == "draft" and card.body_gap_pending is True
    got = card.sections
    assert got[0]["items"][1]["note"] == "Rear will be solid panel"
    assert got[2]["items"][0]["sub_items"][0].startswith("Orange warning diamond")
    assert "sap_item_code" in got[1]["items"][0]          # §0.10 stub field survives


def test_vcl_checklist_lifts_body_gap(db):
    """§0.8 write-through: a numeric body_gap_mm in the VCL checklist lands on the record
    column; non-numeric ('Pending') leaves it NULL."""
    from app.models.mes import ChassisRecord
    from app.schemas.chassis import ChassisEventCapture
    from app.services.chassis import capture_event

    rec = ChassisRecord(vin="P433VINBG1", source="manual", status="received",
                        customer_name="P433 Body Gap Ltd")
    db.add(rec)
    db.commit()
    db.refresh(rec)

    capture_event(db, rec.id, "VCL",
                  ChassisEventCapture(event_date=date.today(),
                                      checklist_json={"body_gap_mm": "120 mm", "keys": True}),
                  who="p433-test")
    db.refresh(rec)
    assert rec.body_gap_mm == 120 and rec.status == "in_workshop"

    rec2 = ChassisRecord(vin="P433VINBG2", source="manual", status="received")
    db.add(rec2)
    db.commit()
    db.refresh(rec2)
    capture_event(db, rec2.id, "VCL",
                  ChassisEventCapture(event_date=date.today(),
                                      checklist_json={"body_gap_mm": "Pending"}),
                  who="p433-test")
    db.refresh(rec2)
    assert rec2.body_gap_mm is None
