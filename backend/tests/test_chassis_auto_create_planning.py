"""WO v4.34 §3.3 — auto-create 'expected' chassis at Planning-Board ack (§0.5b).

Idempotency mirrors §3.2 but keyed on the JOB FK: a card-driven job is already linked via §3.2's
card+job cross-link, so the ack no-ops; jobs that reached Planning WITHOUT a card chassis get the
anchor from the ack's chassis info. Adopts an existing VIN match instead of colliding. P434B
markers; service-level (record_planning_ack); uses an EXISTING job-free calc (v4.27 rule)."""
from datetime import date

import pytest


def _purge(db) -> None:
    from sqlalchemy import text
    # Order matters for the FKs: jobs first (production_jobs.chassis_record_id is ON DELETE
    # RESTRICT), then cards before templates (prejob_cards.template_id is RESTRICT), then chassis.
    db.execute(text("DELETE FROM icb_mes.production_jobs WHERE job_number LIKE 'P434B%'"))
    db.execute(text("DELETE FROM icb_mes.prejob_cards WHERE chassis_make_model LIKE 'P434B%' "
                    "OR body_description LIKE 'P434B%'"))
    db.execute(text("DELETE FROM icb_mes.prejob_templates WHERE name LIKE 'P434B%'"))
    db.execute(text("DELETE FROM icb_mes.chassis_records WHERE make LIKE 'P434B%' "
                    "OR vin LIKE 'P434B%' OR created_source_ref LIKE 'Planning · Job P434B%'"))
    db.commit()


@pytest.fixture
def staged_job():
    """A fresh pre_job_confirmed, chassis-UNLINKED job on a free calc (each ack flips it to
    'planning', so function-scoped)."""
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
                            status="pre_job_confirmed", job_number="P434B01")
        db.add(job)
        db.commit()
        jid = job.id
    yield jid
    from app.database import SessionLocal as SL
    with SL() as db:
        _purge(db)


def _ack(jid, chassis_data, eta=None):
    from app.database import SessionLocal, User
    from app.services import production_jobs as svc
    with SessionLocal() as db:
        admin = db.query(User).filter_by(username="admin").first()
        svc.record_planning_ack(db, jid, chassis_eta=eta, notes=None, user=admin,
                                chassis_data=chassis_data)


def _job_chassis(jid):
    from app.database import SessionLocal
    from app.models.mes import ChassisRecord, ProductionJob
    with SessionLocal() as db:
        job = db.get(ProductionJob, jid)
        ch = db.get(ChassisRecord, job.chassis_record_id) if job.chassis_record_id else None
        snap = None if ch is None else {
            "status": ch.status, "source": ch.source, "created_via": ch.created_via,
            "make": ch.make, "vin": ch.vin, "created_source_ref": ch.created_source_ref}
        return job.chassis_record_id, snap


def _count_make(make):
    from app.database import SessionLocal
    from app.models.mes import ChassisRecord
    with SessionLocal() as db:
        return db.query(ChassisRecord).filter(ChassisRecord.make == make).count()


def test_ack_creates_expected_chassis_when_unlinked(staged_job):
    _ack(staged_job, {"chassis_model": "P434B Volvo FH"}, eta=date(2026, 7, 1))
    crid, ch = _job_chassis(staged_job)
    assert crid is not None and ch is not None
    assert ch["status"] == "expected"
    assert ch["created_via"] == "planning_job_create"
    assert ch["source"] == "planning_ack"                 # legacy VARCHAR(16) short token
    assert ch["make"] == "P434B Volvo FH"
    assert ch["vin"] is None                              # mirrors §3.2 — VIN unknown until VCL receive
    assert ch["created_source_ref"] == "Planning · Job P434B01"


def test_ack_no_chassis_info_anchors_stub(staged_job):    # WO v4.36b.1 — REVERSED (was no-op)
    """Symmetric with v4.36a.4 (§3.2 case 2): a bare ack on an UNLINKED job no longer silently no-ops —
    it anchors a NULL-make 'expected' stub (RED-flagged chassis_no_make_model in v4.36b) so the pipeline
    always has a chassis. Silent deferral on a workflow-critical path was the defect."""
    _ack(staged_job, {"chassis_model": None, "chassis_vin": None})
    crid, ch = _job_chassis(staged_job)
    assert crid is not None and ch is not None            # stub anchored (was: graceful no-op)
    assert ch["make"] is None and ch["vin"] is None       # NULL-make / NULL-vin — a true stub
    assert ch["status"] == "expected" and ch["created_via"] == "planning_job_create"


def test_ack_vin_lands_on_chassis_row(staged_job):
    """WO v4.34 (ack follow-up, BA 2026-06-14) — a VIN typed at ack now LANDS on the linked chassis
    row (the Chassis page reflects the ack), and is still preserved in job.chassis_data_json. The
    row is created vin=NULL (collision-safe) then stamped by record_planning_ack's propagation."""
    import json
    from app.database import SessionLocal
    from app.models.mes import ProductionJob
    _ack(staged_job, {"chassis_model": "P434B Scania", "chassis_vin": "P434BVN0000000001"})
    crid, ch = _job_chassis(staged_job)
    assert crid is not None
    assert ch["vin"] == "P434BVN0000000001" and ch["make"] == "P434B Scania"   # VIN → chassis row
    with SessionLocal() as db:
        cd = json.loads(db.get(ProductionJob, staged_job).chassis_data_json or "{}")
    assert cd.get("chassis_vin") == "P434BVN0000000001"        # still preserved in the job's data


def test_ack_vin_only_anchors_stub_and_stamps_vin(staged_job):   # WO v4.36b.1 — REVERSED (was no-op)
    """A VIN-only ack (no model) on an unlinked job now anchors a NULL-make stub (symmetric with
    v4.36a.4); record_planning_ack's propagation then stamps the conformant VIN onto it. (Was: no-op,
    VIN dropped.) Uses a conformant VIN so the VIN-format gate passes."""
    _ack(staged_job, {"chassis_vin": "P434BVN0000000002"})
    crid, ch = _job_chassis(staged_job)
    assert crid is not None
    assert ch["make"] is None and ch["vin"] == "P434BVN0000000002"   # NULL-make stub + VIN stamped
    assert ch["status"] == "expected"


def test_ack_skips_when_already_linked(staged_job):       # idempotency vs §3.2 cross-link
    from app.database import SessionLocal
    from app.models.mes import ChassisRecord, ProductionJob
    with SessionLocal() as db:
        ch = ChassisRecord(vin="P434BLINKED1", status="expected", source="pre_job_card",
                           created_via="pre_job_card", make="P434B Already Linked",
                           created_by="t", updated_by="t")
        db.add(ch)
        db.flush()
        seeded = ch.id
        db.get(ProductionJob, staged_job).chassis_record_id = ch.id   # simulate §3.2 cross-link
        db.commit()
    _ack(staged_job, {"chassis_model": "P434B Different Make"})        # ack tries to enter info
    crid, _ = _job_chassis(staged_job)
    assert crid == seeded                                 # unchanged — no second row minted
    assert _count_make("P434B Different Make") == 0


def _a_dealer_id(db):
    """An existing is_dealer=true customer id (read-only); skip when the DB has no dealer."""
    from sqlalchemy import select
    from app.database import Customer
    return db.execute(
        select(Customer.id).where(Customer.is_dealer.is_(True)).order_by(Customer.id)).scalars().first()


def test_ack_persists_chassis_fields_to_record(staged_job):
    """WO v4.36b — chassis-field unification: the Planning ack writes the unified chassis fields onto the
    LINKED chassis_records row (single source of truth), not only the costing chassis_data blob. dealer_id
    is validated (is_dealer); customer/contact/telephone/description/notes + tail_lift_code land on the row.
    (Service-level chassis_data keys — the router maps PlanningAckRequest.chassis_notes -> 'notes'.)"""
    from app.database import SessionLocal
    from app.models.mes import ChassisRecord, ProductionJob
    with SessionLocal() as db:
        dealer_id = _a_dealer_id(db)
    if dealer_id is None:
        pytest.skip("no is_dealer customer on this DB")
    _ack(staged_job, {
        "chassis_model": "P434B Iveco Stralis", "dealer_id": dealer_id, "tail_lift_code": "TL-2000",
        "customer_name": "P434B Ack Customer", "contact_person": "P434B Contact",
        "telephone": "011-555-0100", "description": "P434B body desc", "notes": "P434B note"})
    with SessionLocal() as db:
        job = db.get(ProductionJob, staged_job)
        ch = db.get(ChassisRecord, job.chassis_record_id)
    assert ch is not None
    assert ch.make == "P434B Iveco Stralis"               # auto-created from chassis_model
    assert ch.dealer_id == dealer_id                      # validated dealer landed on the row
    assert ch.tail_lift_code == "TL-2000"
    assert ch.customer_name == "P434B Ack Customer"
    assert ch.contact_person == "P434B Contact"
    assert ch.telephone == "011-555-0100"
    assert ch.description == "P434B body desc"
    assert ch.notes == "P434B note"                       # chassis_data 'notes' -> chassis_records.notes


def test_planning_ref_branches():                         # review §0.4 — both ref branches
    from app.services.production_jobs import _planning_ref

    class _J:
        pass
    j = _J(); j.job_number = "32744"; j.id = 5
    assert _planning_ref(j) == "Planning · Job 32744"
    j2 = _J(); j2.job_number = None; j2.id = 9
    assert _planning_ref(j2) == "Planning · job 9"        # workbook edge: NULL job_number


def test_ack_serialized_invariant(staged_job):
    """Concurrency is enforced by the FOR UPDATE lock on the job row in record_planning_ack: a
    second concurrent ack blocks, then re-reads status='planning' and 422s before the auto-create
    — so exactly one 'expected' chassis is minted. A true two-session race isn't deterministically
    reproducible here; this asserts the invariant the lock guarantees (one row)."""
    _ack(staged_job, {"chassis_model": "P434B Single Row"})
    assert _count_make("P434B Single Row") == 1


def test_ack_noops_after_real_prejob_submit():            # review §7 — cross-touchpoint contract, E2E
    """The card-driven §3.2 chassis (with the job linked via the cross-link) makes the §3.3 ack a
    TRUE no-op — no second chassis, the job keeps the pre_job_card row. Drives the real
    submit→sign-off→ack chain rather than a manual seed."""
    from app.database import Branch, CalculationRecord, SessionLocal, User
    from app.models.mes import ChassisRecord, PrejobCard, PrejobTemplate, ProductionJob
    from app.services import prejob_cards as pjc, production_jobs as pjs
    with SessionLocal() as db:
        _purge(db)
        taken = {j.calculation_record_id for j in db.query(ProductionJob)
                 .filter(ProductionJob.calculation_record_id.isnot(None)).all()}
        carded = {c.calculation_id for c in db.query(PrejobCard).all()}
        calc = (db.query(CalculationRecord)
                .filter(~CalculationRecord.id.in_((taken | carded) or {0}),
                        CalculationRecord.quote_number.isnot(None),
                        CalculationRecord.is_repair.is_(False))
                .order_by(CalculationRecord.id.desc()).first())
        if calc is None:
            pytest.skip("no free non-repair calculation on this DB")
        branch = db.query(Branch).order_by(Branch.id).first()
        db.add(ProductionJob(calculation_record_id=calc.id, branch_id=branch.id, source="quote",
                             status="accepted", job_number="P434B90"))
        tpl = PrejobTemplate(name="P434B XMod Template", body_type="chiller",
                             product_line="standard", header_format="P434B header",
                             sections=[{"name": "GRP", "items": [{"text": "x"}]}],
                             is_active=True, created_by="t")
        db.add(tpl)
        db.commit()
        calc_id, tpl_id = calc.id, tpl.id
    try:
        with SessionLocal() as db:
            admin = db.query(User).filter_by(username="admin").first()
            card = pjc.create_card(db, calc_id, tpl_id, admin)
            pjc.update_card(db, card.id, {"chassis_make_model": "P434B XMod Card",
                                          "planner_user_id": admin.id,
                                          "sales_rep_user_id": admin.id, "body_gap_mm": 100}, admin)
            pjc.submit_for_check(db, card.id, admin)       # §3.2 creates chassis + links job
            pjc.sign_off(db, card.id, "sales", "ok", admin)
            pjc.sign_off(db, card.id, "planner", "ok", admin)   # → pre_job_confirmed
            card_id = card.id
        with SessionLocal() as db:
            job = db.query(ProductionJob).filter_by(job_number="P434B90").first()
            job_id, s32 = job.id, db.get(PrejobCard, card_id).chassis_record_id
            assert s32 is not None and job.chassis_record_id == s32   # §3.2 cross-link
        with SessionLocal() as db:
            admin = db.query(User).filter_by(username="admin").first()
            pjs.record_planning_ack(db, job_id, chassis_eta=None, notes=None, user=admin,
                                    chassis_data={"chassis_model": "P434B Different At Ack"})
        with SessionLocal() as db:
            assert db.get(ProductionJob, job_id).chassis_record_id == s32          # unchanged
            assert db.get(ChassisRecord, s32).created_via == "pre_job_card"        # still §3.2 row
            assert db.query(ChassisRecord).filter(
                ChassisRecord.make == "P434B Different At Ack").count() == 0        # no §3.3 row
    finally:
        with SessionLocal() as db:
            _purge(db)


def test_ack_twice_is_status_guarded(staged_job):
    from app.services import production_jobs as svc
    _ack(staged_job, {"chassis_model": "P434B First Ack"})            # → status 'planning'
    crid1, _ = _job_chassis(staged_job)
    assert crid1 is not None
    with pytest.raises(svc.WrongStatusForTransitionError):            # second ack: not pre_job_confirmed
        _ack(staged_job, {"chassis_model": "P434B Second Ack"})
    crid2, _ = _job_chassis(staged_job)
    assert crid2 == crid1                                 # no second chassis
    assert _count_make("P434B Second Ack") == 0
