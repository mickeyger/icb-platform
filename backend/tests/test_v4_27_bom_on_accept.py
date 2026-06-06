"""WO v4.27 §3.5/§3.9 — BOM-on-accept hook.

Self-contained + portable: each test creates a temp trailer_type / calculation / production_job,
exercises generate_and_persist_bom, asserts, and ROLLS BACK (no commit → no DB pollution, works on
the real local DB and the mock-seeded CI DB alike). Relies only on seeded bom_rules / bom_spec_options
(present in both via seed_from_mockup).
"""
import json

from sqlalchemy import select

from app.database import Branch, CalculationRecord, SessionLocal, TrailerType
from app.models.mes import BomLine, GeneratedBom, ProductionJob
from app.services.bom_on_accept import generate_and_persist_bom

_DIMS = json.dumps({"length": 7.5, "width": 2.6, "height": 2.6})   # metres → 7500/2600/2600 mm


def _branch_id(db):
    return db.execute(select(Branch.id).order_by(Branch.id)).scalars().first()


def _make_job(db, trailer_name=None, dims=_DIMS):
    """Create a temp production_job (+ temp trailer_type/calc when trailer_name given). Not committed."""
    calc_id = None
    if trailer_name is not None:
        tt = TrailerType(name=trailer_name)
        db.add(tt)
        db.flush()
        calc = CalculationRecord(trailer_type_id=tt.id, branch_id=_branch_id(db),
                                 dimensions_json=dims, status="accepted")
        db.add(calc)
        db.flush()
        calc_id = calc.id
    job = ProductionJob(calculation_record_id=calc_id, branch_id=_branch_id(db),
                        status="accepted", bom_status="pending")
    db.add(job)
    db.flush()
    return job


def _lines(db, gb):
    return db.query(BomLine).filter_by(generated_bom_id=gb.id).count()


def test_accept_persists_versioned_current_bom():
    """A mapped body type (Chiller) generates + persists a current v1 BOM with structure."""
    with SessionLocal() as db:
        try:
            job = _make_job(db, "4.9 & UP CHILLER AND 2.5 WIDE")
            gb = generate_and_persist_bom(db, job)
            assert gb.id is not None and gb.current is True and gb.version == 1
            assert job.current_bom_id == gb.id
            assert gb.metadata_json.get("spec_source") == "defaults"
            assert gb.metadata_json.get("body_type") == "Chiller"
            assert _lines(db, gb) > 0   # Chiller Vacuum geometry produced panel lines
        finally:
            db.rollback()


def test_reaccept_creates_new_version_and_flips_current():
    """Re-accepting versions the BOM: v2 becomes current, v1 is flipped off, job points to v2."""
    with SessionLocal() as db:
        try:
            job = _make_job(db, "4.9 & UP CHILLER AND 2.5 WIDE")
            gb1 = generate_and_persist_bom(db, job)
            db.flush()
            gb2 = generate_and_persist_bom(db, job)
            db.flush()
            db.refresh(gb1)
            assert gb2.version == gb1.version + 1
            assert gb1.current is False and gb2.current is True
            assert job.current_bom_id == gb2.id
            assert db.query(GeneratedBom).filter_by(production_job_id=job.id, current=True).count() == 1
        finally:
            db.rollback()


def test_unmapped_body_type_is_incomplete_and_empty():
    """An unmapped trailer_type (MANNI) persists an incomplete, empty BOM — never blocks accept."""
    with SessionLocal() as db:
        try:
            job = _make_job(db, "MANNI RIGIDS CB")
            gb = generate_and_persist_bom(db, job)
            assert gb.bom_status == "incomplete"
            assert gb.metadata_json.get("reason") == "body_type_unmapped"
            assert gb.current is True and job.current_bom_id == gb.id
            assert _lines(db, gb) == 0
        finally:
            db.rollback()


def test_no_calculation_is_incomplete():
    """A job with no originating calculation (e.g. workbook-imported) → incomplete, empty."""
    with SessionLocal() as db:
        try:
            job = _make_job(db, trailer_name=None)
            gb = generate_and_persist_bom(db, job)
            assert gb.bom_status == "incomplete"
            assert gb.metadata_json.get("reason") == "no_calculation"
            assert _lines(db, gb) == 0
        finally:
            db.rollback()
