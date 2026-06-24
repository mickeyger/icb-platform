"""WO v4.34 §3.2 — auto-create 'expected' chassis at Pre-Job submit (idempotency-critical).

The four BA-mandated cases (re-submit no-dup / empty make-model no-op / make-model+NULL-vin
creates row / concurrency) + the adopt-the-job's-chassis and resubmit-after-reject paths, plus
the cross-touchpoint link (card AND job → same chassis, so §3.3's Planning auto-create can't
mint a third). Designed via the §3.2 design+risk workflow. P434A markers; self-healing purge;
uses an EXISTING job-free calculation (read-only on icb_costings — the v4.27/§0.20 rule)."""
import pytest


def _purge(db) -> None:
    from sqlalchemy import text
    db.execute(text("DELETE FROM icb_mes.prejob_cards WHERE body_description LIKE 'P434A%' "
                    "OR chassis_make_model LIKE 'P434A%'"))
    db.execute(text("DELETE FROM icb_mes.prejob_templates WHERE name LIKE 'P434A%'"))
    db.execute(text("DELETE FROM icb_mes.production_jobs WHERE job_number LIKE 'P434A%'"))
    db.execute(text("DELETE FROM icb_mes.chassis_records WHERE make LIKE 'P434A%' "
                    "OR vin LIKE 'P434A%' OR created_source_ref LIKE 'P434A%'"))
    db.commit()


@pytest.fixture(scope="module")
def app_mod():
    import app.main as m
    from starlette.testclient import TestClient
    with TestClient(m.app):
        yield m


@pytest.fixture
def api(app_mod):
    from app.database import SessionLocal, User
    from app.deps import require_user
    from starlette.testclient import TestClient
    with SessionLocal() as db:
        _purge(db)
        admin = db.query(User).filter_by(username="admin").first()
    app_mod.app.dependency_overrides[require_user] = lambda: admin
    with TestClient(app_mod.app) as c:
        yield c, admin
    app_mod.app.dependency_overrides.pop(require_user, None)
    with SessionLocal() as db:
        _purge(db)


@pytest.fixture
def staged(api):
    """A job-free, card-free calc + an active P434A template."""
    from app.database import CalculationRecord, SessionLocal
    from app.models.mes import PrejobCard, PrejobTemplate, ProductionJob
    sections = [{"name": "GRP SECTION", "items": [{"text": "Item"}]}]
    with SessionLocal() as db:
        taken = {j.calculation_record_id for j in db.query(ProductionJob)
                 .filter(ProductionJob.calculation_record_id.isnot(None)).all()}
        carded = {c.calculation_id for c in db.query(PrejobCard).all()}
        calc = (db.query(CalculationRecord)
                .filter(~CalculationRecord.id.in_((taken | carded) or {0}),
                        CalculationRecord.quote_number.isnot(None))
                .order_by(CalculationRecord.id.desc()).first())
        if calc is None:
            pytest.skip("no job-free, card-free calculation on this DB")
        tpl = PrejobTemplate(name="P434A Template", body_type="chiller", product_line="standard",
                             header_format="P434A header", sections=sections,
                             is_active=True, created_by="t")
        db.add(tpl)
        db.commit()
        return {"calc_id": calc.id, "tpl_id": tpl.id, "quote": calc.quote_number}


def _create_card(client, admin, staged, *, make_model=None, body_gap=100):
    r = client.post("/api/prejob-cards",
                    json={"calculation_id": staged["calc_id"], "template_id": staged["tpl_id"]})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    patch = {"sales_rep_user_id": admin.id, "planner_user_id": admin.id, "body_gap_mm": body_gap}
    if make_model is not None:
        patch["chassis_make_model"] = make_model
    r = client.patch(f"/api/prejob-cards/{cid}", json=patch)
    assert r.status_code == 200, r.text
    return cid


def _chassis_of(card_id):
    """Detached-safe snapshot of the card's linked chassis (plain dict / None)."""
    from app.database import SessionLocal
    from app.models.mes import ChassisRecord, PrejobCard
    with SessionLocal() as db:
        card = db.get(PrejobCard, card_id)
        ch = db.get(ChassisRecord, card.chassis_record_id) if card.chassis_record_id else None
        snap = None if ch is None else {
            "id": ch.id, "vin": ch.vin, "status": ch.status, "source": ch.source,
            "created_via": ch.created_via, "make": ch.make,
            "created_source_ref": ch.created_source_ref, "body_gap_mm": ch.body_gap_mm}
        return card.chassis_record_id, snap


def _count_make(make):
    from app.database import SessionLocal
    from app.models.mes import ChassisRecord
    with SessionLocal() as db:
        return db.query(ChassisRecord).filter(ChassisRecord.make == make).count()


def test_make_model_null_vin_creates_expected_row(api, staged):   # BA case 3
    client, admin = api
    cid = _create_card(client, admin, staged, make_model="P434A Iveco Daily")
    r = client.post(f"/api/prejob-cards/{cid}/submit-for-check", json={})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "sent_for_check"
    crid, ch = _chassis_of(cid)
    assert crid is not None and ch is not None
    assert ch["vin"] is None                                      # case 3 — NULL vin
    assert ch["status"] == "expected"
    assert ch["source"] == "pre_job_card"
    assert ch["created_via"] == "pre_job_card"
    assert ch["make"] == "P434A Iveco Daily"
    assert ch["created_source_ref"] == staged["quote"]           # quote branch — exact value pinned
    assert ch["body_gap_mm"] == 100                              # §0.8 gap carried from the card


def test_submit_stamps_customer_on_stub(api, staged):            # WO v4.36b (Inv 1) — costing customer → stub
    """At Pre-Job submit the auto-created 'expected' stub now carries the costing's customer (was NULL —
    the empty-Customer screenshot): _auto_create_chassis resolves calc.customer_id -> Customer.name and
    passes it to create_expected_chassis. Skips when the staged calc has no customer on this DB."""
    client, admin = api
    from app.database import CalculationRecord, Customer, SessionLocal
    from app.models.mes import ChassisRecord
    with SessionLocal() as db:
        calc = db.get(CalculationRecord, staged["calc_id"])
        cust = db.get(Customer, calc.customer_id) if calc.customer_id else None
        expected = cust.name if cust else None
    if not expected:
        pytest.skip("staged calc has no customer on this DB")
    cid = _create_card(client, admin, staged, make_model="P434A Cust Stamp")
    assert client.post(f"/api/prejob-cards/{cid}/submit-for-check", json={}).status_code == 200
    crid, _ = _chassis_of(cid)
    with SessionLocal() as db:
        assert db.get(ChassisRecord, crid).customer_name == expected   # costing customer stamped on the stub


def test_empty_make_model_creates_expected_stub(api, staged):     # BA case 2 — REVERSED in v4.36a.4
    """Reverses §3.2 case 2 (v4.34) deliberately. With v4.36a chassis_integrity
    + v4.36b visual integrity + v4.36.5 single-editor direction, silent deferral
    on empty make_model is an H6-class UX defect. Pre-Job submission MUST
    anchor a chassis stub regardless of make_model state; the stub becomes a
    v4.36b RED flag for operator attention. ADR 0026 H6."""
    client, admin = api
    cid = _create_card(client, admin, staged, make_model=None)    # never set → stays None
    r = client.post(f"/api/prejob-cards/{cid}/submit-for-check", json={})
    assert r.status_code == 200, r.text
    crid, ch = _chassis_of(cid)
    assert crid is not None and ch is not None                    # stub anchored (was: graceful no-op)
    assert ch["make"] is None and ch["vin"] is None               # NULL make + VIN — a true stub
    assert ch["status"] == "expected" and ch["created_via"] == "pre_job_card"


def test_double_submit_no_duplicate_chassis(api, staged):         # BA case 1
    client, admin = api
    cid = _create_card(client, admin, staged, make_model="P434A Hino 300")
    assert client.post(f"/api/prejob-cards/{cid}/submit-for-check", json={}).status_code == 200
    crid1, _ = _chassis_of(cid)
    assert crid1 is not None
    r2 = client.post(f"/api/prejob-cards/{cid}/submit-for-check", json={})
    assert r2.status_code == 409                                  # already sent_for_check
    crid2, _ = _chassis_of(cid)
    assert crid2 == crid1                                         # unchanged
    assert _count_make("P434A Hino 300") == 1                     # exactly one


def test_resubmit_after_reject_readopts_via_job(api, staged):     # §3.4 — release + re-adopt, no dup
    """With a production job, §3.4 reject drops the CARD link but the job keeps the chassis (not
    orphaned), so re-submit re-adopts it via the job — one chassis across the reject cycle."""
    client, admin = api
    from app.database import Branch, SessionLocal
    from app.models.mes import ProductionJob
    with SessionLocal() as db:
        branch = db.query(Branch).order_by(Branch.id).first()
        db.add(ProductionJob(calculation_record_id=staged["calc_id"], branch_id=branch.id,
                             source="quote", status="accepted", job_number="P434AJOB3"))
        db.commit()
    cid = _create_card(client, admin, staged, make_model="P434A Fuso Canter")
    assert client.post(f"/api/prejob-cards/{cid}/submit-for-check", json={}).status_code == 200
    crid1, _ = _chassis_of(cid)
    assert crid1 is not None
    rj = client.post(f"/api/prejob-cards/{cid}/reject/planner", json={"reason": "P434A test reject"})
    assert rj.status_code == 200 and rj.json()["status"] == "draft"
    crid_mid, _ = _chassis_of(cid)
    assert crid_mid is None                                       # §3.4 released the card link
    assert client.post(f"/api/prejob-cards/{cid}/submit-for-check", json={}).status_code == 200
    crid2, ch2 = _chassis_of(cid)
    assert crid2 == crid1                                         # re-adopted the job's chassis
    assert ch2["status"] == "expected"                            # job kept it — never orphaned
    assert _count_make("P434A Fuso Canter") == 1


def test_reject_orphans_jobless_auto_created_chassis(api, staged):    # §3.4 (§0.6) — orphan path
    """A jobless card's auto-created chassis has no other links, so reject releases the card link
    AND orphans the chassis (status → expected_orphaned, available for re-linking)."""
    client, admin = api
    cid = _create_card(client, admin, staged, make_model="P434A Orphan Me")
    assert client.post(f"/api/prejob-cards/{cid}/submit-for-check", json={}).status_code == 200
    crid1, _ = _chassis_of(cid)
    assert crid1 is not None
    rj = client.post(f"/api/prejob-cards/{cid}/reject/sales", json={"reason": "P434A orphan test"})
    assert rj.status_code == 200
    crid_after, _ = _chassis_of(cid)
    assert crid_after is None                                     # card link released
    from app.database import SessionLocal
    from app.models.mes import ChassisRecord
    with SessionLocal() as db:
        ch = db.get(ChassisRecord, crid1)
        assert ch is not None and ch.status == "expected_orphaned"   # orphaned, not deleted


def test_reject_does_not_release_foreign_chassis(api, staged):       # §3.4 — only THIS card's auto-created
    """A chassis NOT auto-created for this card (e.g. a register/VCL row manually linked) is left
    untouched by reject — the created_via/ref guard protects it."""
    client, admin = api
    from app.database import SessionLocal
    from app.models.mes import ChassisRecord, PrejobCard
    cid = _create_card(client, admin, staged, make_model="P434A Card Make")
    with SessionLocal() as db:
        foreign = ChassisRecord(vin="P434BFOREIGN1", status="received", source="register",
                                make="P434A Foreign", created_by="t", updated_by="t")
        db.add(foreign)
        db.flush()
        foreign_id = foreign.id
        db.get(PrejobCard, cid).chassis_record_id = foreign.id    # manual link to a non-auto chassis
        db.commit()
    assert client.post(f"/api/prejob-cards/{cid}/submit-for-check", json={}).status_code == 200
    rj = client.post(f"/api/prejob-cards/{cid}/reject/planner", json={"reason": "P434A foreign test"})
    assert rj.status_code == 200
    crid_after, _ = _chassis_of(cid)
    assert crid_after == foreign_id                              # link untouched (not auto-created here)
    with SessionLocal() as db:
        assert db.get(ChassisRecord, foreign_id).status == "received"   # status untouched


def test_submit_adopts_preexisting_job_chassis(api, staged):      # review A4
    client, admin = api
    from app.database import Branch, SessionLocal
    from app.models.mes import ChassisRecord, ProductionJob
    with SessionLocal() as db:
        branch = db.query(Branch).order_by(Branch.id).first()
        ch = ChassisRecord(vin="P434APREEXIST1", status="received", source="register",
                           make="P434A Preexisting", created_by="t", updated_by="t")
        db.add(ch)
        db.flush()
        seeded_id = ch.id
        db.add(ProductionJob(calculation_record_id=staged["calc_id"], branch_id=branch.id,
                             source="quote", status="accepted", job_number="P434AJOB1",
                             chassis_record_id=ch.id))
        db.commit()
    cid = _create_card(client, admin, staged, make_model="P434A Should Adopt Not Create")
    assert client.post(f"/api/prejob-cards/{cid}/submit-for-check", json={}).status_code == 200
    crid, _ = _chassis_of(cid)
    assert crid == seeded_id                                      # adopted the job's chassis
    from app.database import SessionLocal as SL
    from app.models.mes import ProductionJob as PJ
    with SL() as db:
        minted = db.query(ChassisRecord).filter(
            ChassisRecord.created_via == "pre_job_card",
            ChassisRecord.make.like("P434A%")).count()
        assert minted == 0                                       # nothing new minted (no pre_job_card row)
        assert db.query(ChassisRecord).filter(ChassisRecord.make.like("P434A%")).count() == 1  # total backstop
        job = db.query(PJ).filter_by(job_number="P434AJOB1").first()
        assert job.chassis_record_id == seeded_id                # adopt path never clobbers the job FK


def test_create_links_both_card_and_job(api, staged):             # CA1 addition — cross-touchpoint
    client, admin = api
    from app.database import Branch, SessionLocal
    from app.models.mes import ProductionJob
    with SessionLocal() as db:
        branch = db.query(Branch).order_by(Branch.id).first()
        db.add(ProductionJob(calculation_record_id=staged["calc_id"], branch_id=branch.id,
                             source="quote", status="accepted", job_number="P434AJOB2"))  # job, NO chassis
        db.commit()
    cid = _create_card(client, admin, staged, make_model="P434A MAN TGS")
    assert client.post(f"/api/prejob-cards/{cid}/submit-for-check", json={}).status_code == 200
    crid, ch = _chassis_of(cid)
    assert crid is not None and ch["created_via"] == "pre_job_card"
    from app.database import SessionLocal as SL
    from app.models.mes import ProductionJob as PJ
    with SL() as db:
        job = db.query(PJ).filter_by(job_number="P434AJOB2").first()
        assert job.chassis_record_id == crid                      # job now points at the SAME chassis


def test_concurrent_submit_serialized_by_row_lock(api, staged):   # BA case 4 (documented)
    """Concurrency is enforced by the FOR UPDATE row-lock on the card in submit_for_check: under
    READ COMMITTED a second concurrent submit blocks on the lock, then re-reads
    status='sent_for_check' and 409s BEFORE _auto_create_chassis — so exactly one 'expected'
    chassis is ever minted. A true two-thread race isn't deterministically reproducible via the
    single-threaded TestClient; this asserts the invariant the lock guarantees (one row). The
    lock itself is exercised by every submit in this suite."""
    client, admin = api
    cid = _create_card(client, admin, staged, make_model="P434A Isuzu NPR")
    assert client.post(f"/api/prejob-cards/{cid}/submit-for-check", json={}).status_code == 200
    assert _count_make("P434A Isuzu NPR") == 1


def test_expected_chassis_serializes_in_list_and_detail(api, staged):   # review HIGH — NULL-vin read
    """A NULL-vin 'expected' row must not 500 the Chassis screens: the read schema's vin is
    Optional. GET the UNFILTERED list (the default UI view) + the detail after auto-create."""
    client, admin = api
    cid = _create_card(client, admin, staged, make_model="P434A Scania R")
    assert client.post(f"/api/prejob-cards/{cid}/submit-for-check", json={}).status_code == 200
    crid, _ = _chassis_of(cid)
    lst = client.get("/api/chassis-records?limit=200")
    assert lst.status_code == 200, lst.text                       # whole list must not 500
    row = next((r for r in lst.json() if r["id"] == crid), None)
    assert row is not None and row["vin"] is None and row["status"] == "expected"
    det = client.get(f"/api/chassis-records/{crid}")
    assert det.status_code == 200 and det.json()["vin"] is None


def test_make_model_overflow_truncated_not_500(api, staged):      # review HIGH — String(64) make
    """chassis_make_model is String(128) but chassis.make is VARCHAR(64): a 65-128 char value
    must be truncated, not raise StringDataRightTruncation (which would 500 + roll the submit back)."""
    client, admin = api
    long_mm = "P434A " + ("X" * 90)                               # 96 chars — fits the card, overflows make
    cid = _create_card(client, admin, staged, make_model=long_mm)
    assert client.post(f"/api/prejob-cards/{cid}/submit-for-check", json={}).status_code == 200
    _, ch = _chassis_of(cid)
    assert ch is not None and len(ch["make"]) == 64 and ch["make"] == long_mm[:64]


def test_resubmit_syncs_corrected_make(api, staged):              # review MED — reject→fix→resubmit staleness
    """reject→fix make/model→resubmit must propagate the correction onto the linked 'expected'
    chassis (same row, no duplicate). With a job, §3.4 reject keeps the chassis on the job and
    re-submit re-adopts + syncs the corrected make."""
    client, admin = api
    from app.database import Branch, SessionLocal
    from app.models.mes import ProductionJob
    with SessionLocal() as db:
        branch = db.query(Branch).order_by(Branch.id).first()
        db.add(ProductionJob(calculation_record_id=staged["calc_id"], branch_id=branch.id,
                             source="quote", status="accepted", job_number="P434AJOB4"))
        db.commit()
    cid = _create_card(client, admin, staged, make_model="P434A Wrong Make")
    assert client.post(f"/api/prejob-cards/{cid}/submit-for-check", json={}).status_code == 200
    crid1, ch1 = _chassis_of(cid)
    assert ch1["make"] == "P434A Wrong Make"
    assert client.post(f"/api/prejob-cards/{cid}/reject/planner",
                       json={"reason": "wrong chassis"}).status_code == 200
    assert client.patch(f"/api/prejob-cards/{cid}",
                        json={"chassis_make_model": "P434A Corrected Make"}).status_code == 200
    assert client.post(f"/api/prejob-cards/{cid}/submit-for-check", json={}).status_code == 200
    crid2, ch2 = _chassis_of(cid)
    assert crid2 == crid1                                         # same chassis (no dup)
    assert ch2["make"] == "P434A Corrected Make"                  # correction synced through


def test_whitespace_make_model_creates_expected_stub(api, staged):   # REVERSED in v4.36a.4
    """Same reasoning as test_empty_make_model_creates_expected_stub. Whitespace
    collapsed to empty is functionally identical; both must anchor a stub."""
    client, admin = api
    cid = _create_card(client, admin, staged, make_model="   ")
    assert client.post(f"/api/prejob-cards/{cid}/submit-for-check", json={}).status_code == 200
    crid, ch = _chassis_of(cid)
    assert crid is not None and ch is not None                    # whitespace → empty → still anchors a stub
    assert ch["make"] is None and ch["status"] == "expected"


def test_source_ref_quote_then_card_fallback():                  # review MED — unreachable fallback branch
    from app.services.prejob_cards import _source_ref

    class _Obj:
        pass
    calc = _Obj(); calc.quote_number = "A99999/06/2026"
    card = _Obj(); card.id = 7
    assert _source_ref(calc, card) == "A99999/06/2026"           # quote branch
    blank = _Obj(); blank.quote_number = None
    assert _source_ref(blank, card) == "card 7"                  # NULL-quote fallback
    assert _source_ref(None, card) == "card 7"                   # missing-calc fallback
