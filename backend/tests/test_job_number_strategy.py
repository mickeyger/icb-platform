"""WO v4.34 §3.5 — quote-derived numeric job_number (§0.7) + Planning-ack override (§0.8) gated by
SAP_RETIRED / job_number_locked (§0.9). Extraction is unit-tested; the override + gating run through
record_planning_ack on a staged pre_job_confirmed job. P434C markers; SAP_RETIRED toggles restored."""
import pytest


def _purge(db) -> None:
    from sqlalchemy import text
    db.execute(text("DELETE FROM icb_mes.production_jobs WHERE job_number LIKE 'P434C%'"))  # jobs first (FK)
    db.execute(text("DELETE FROM icb_mes.chassis_records WHERE created_by='p434c'"))
    db.commit()


def test_numeric_extraction_across_prefixes():            # §0.7
    from app.services.production_jobs import _job_number_from_quote as core
    assert core("A32744/06/2026") == "32744"              # the BA's canonical example
    assert core("N12345/01/2025") == "12345"              # other letter prefix
    assert core("Q-32891") == "32891"                     # legacy dash form
    assert core("32744/06/2026") == "32744"               # no letter prefix
    assert core(None) is None
    assert core("no-digits") is None


@pytest.fixture
def staged_job():
    """A pre_job_confirmed job with a quote-derived numeric job_number, ready for ack."""
    from app.database import Branch, CalculationRecord, SessionLocal
    from app.models.mes import ProductionJob
    with SessionLocal() as db:
        _purge(db)
        taken = {j.calculation_record_id for j in db.query(ProductionJob)
                 .filter(ProductionJob.calculation_record_id.isnot(None)).all()}
        calc = (db.query(CalculationRecord)
                .filter(~CalculationRecord.id.in_(taken or {0}),
                        CalculationRecord.quote_number.isnot(None))
                .order_by(CalculationRecord.id.desc()).first())
        if calc is None:
            pytest.skip("no job-free calculation on this DB")
        branch = db.query(Branch).order_by(Branch.id).first()
        job = ProductionJob(calculation_record_id=calc.id, branch_id=branch.id, source="quote",
                            status="pre_job_confirmed", job_number="P434C01",
                            job_number_source="quote_derived")
        db.add(job)
        db.commit()
        jid = job.id
    yield jid
    from app.database import SessionLocal as SL
    with SL() as db:
        _purge(db)


def _ack(jid, job_number=None):
    from app.database import SessionLocal, User
    from app.services import production_jobs as svc
    with SessionLocal() as db:
        admin = db.query(User).filter_by(username="admin").first()
        svc.record_planning_ack(db, jid, chassis_eta=None, notes=None, user=admin,
                                chassis_data=None, job_number=job_number)


def _job(jid):
    from app.database import SessionLocal
    from app.models.mes import ProductionJob
    with SessionLocal() as db:
        j = db.get(ProductionJob, jid)
        return j.job_number, j.job_number_source, bool(j.job_number_locked)


def _set_sap_retired(value: bool):
    from sqlalchemy import text
    from app.database import SessionLocal
    with SessionLocal() as db:
        db.execute(text("UPDATE icb_costings.admin_settings SET value=:v WHERE key='SAP_RETIRED'"),
                   {"v": "true" if value else "false"})
        db.commit()


def test_ack_override_sets_sap_assigned(staged_job):      # §0.8
    _ack(staged_job, job_number="P434C99999")
    jn, src, _ = _job(staged_job)
    assert jn == "P434C99999" and src == "sap_assigned"


def test_ack_no_override_keeps_quote_derived(staged_job):
    _ack(staged_job, job_number=None)
    jn, src, _ = _job(staged_job)
    assert jn == "P434C01" and src == "quote_derived"     # field absent → unchanged


def test_ack_blank_override_keeps_quote_derived(staged_job):
    _ack(staged_job, job_number="   ")                    # whitespace → no change
    jn, src, _ = _job(staged_job)
    assert jn == "P434C01" and src == "quote_derived"


def test_ack_override_refused_when_locked(staged_job):    # §0.9
    from app.database import SessionLocal
    from app.models.mes import ProductionJob
    with SessionLocal() as db:
        db.get(ProductionJob, staged_job).job_number_locked = True
        db.commit()
    _ack(staged_job, job_number="P434C88888")
    jn, src, locked = _job(staged_job)
    assert jn == "P434C01" and src == "quote_derived" and locked is True   # override ignored


def test_ack_override_refused_when_sap_retired(staged_job):   # §0.9
    _set_sap_retired(True)
    try:
        _ack(staged_job, job_number="P434C77777")
        jn, src, _ = _job(staged_job)
        assert jn == "P434C01" and src == "quote_derived"  # refused — SAP_RETIRED forces quote-derived
    finally:
        _set_sap_retired(False)


def test_ack_propagates_job_number_and_vin_to_chassis():
    """BA 2026-06-14 — at Planning ack, the job's final number + the VIN (attested at pre-job, or
    captured here when blank) land on the LINKED chassis so the Chassis page reflects the ack."""
    from app.database import Branch, CalculationRecord, SessionLocal, User
    from app.models.mes import ChassisRecord, ProductionJob
    from app.services import production_jobs as svc
    vin = "P434CACKVN0000001"   # WO v4.36a — conformant 17-char ISO-3779 (was 'P434CACKVIN01')
    with SessionLocal() as db:
        _purge(db)
        taken = {j.calculation_record_id for j in db.query(ProductionJob)
                 .filter(ProductionJob.calculation_record_id.isnot(None)).all()}
        calc = (db.query(CalculationRecord)
                .filter(~CalculationRecord.id.in_(taken or {0}), CalculationRecord.quote_number.isnot(None))
                .order_by(CalculationRecord.id.desc()).first())
        if calc is None:
            pytest.skip("no job-free calculation on this DB")
        branch = db.query(Branch).order_by(Branch.id).first()
        chassis = ChassisRecord(make="P434C Make", vin=None, status="expected", source="pre_job_card",
                                created_via="pre_job_card", created_source_ref="P434C",
                                created_by="p434c", updated_by="p434c")
        db.add(chassis)
        db.flush()
        job = ProductionJob(calculation_record_id=calc.id, branch_id=branch.id, source="quote",
                            status="pre_job_confirmed", job_number="P434C01",
                            job_number_source="quote_derived", chassis_record_id=chassis.id)
        db.add(job)
        db.commit()
        jid, chid = job.id, chassis.id
    with SessionLocal() as db:
        admin = db.query(User).filter_by(username="admin").first()
        svc.record_planning_ack(db, jid, chassis_eta=None, notes=None, user=admin,
                                chassis_data={"chassis_vin": vin})   # VIN captured at ack
    with SessionLocal() as db:
        ch = db.get(ChassisRecord, chid)
        assert ch.job_number == "P434C01"                  # job number → Chassis page
        assert ch.vin == vin                               # captured VIN → chassis record
    with SessionLocal() as db:
        _purge(db)


def test_sap_retired_helper():
    from app.database import SessionLocal
    from app.services.production_jobs import sap_retired
    with SessionLocal() as db:
        assert sap_retired(db) is False                    # seeded default (0020)
    _set_sap_retired(True)
    try:
        with SessionLocal() as db:
            assert sap_retired(db) is True
    finally:
        _set_sap_retired(False)
    with SessionLocal() as db:
        assert sap_retired(db) is False                    # restored
