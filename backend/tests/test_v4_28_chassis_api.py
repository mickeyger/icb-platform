"""WO v4.28 §3 — chassis lifecycle service tests (chassis_records + VCL/DCL + photos) + Flag E.

Self-contained + portable (real local DB and mock-seeded CI alike). The chassis service COMMITS, so
rollback can't undo it — instead every record uses the ``ZZTESTV428`` VIN prefix and is hard-deleted
in ``finally`` (the FK ON DELETE CASCADE removes its lifecycle events + photos). Flag E's
mark/un-tick is exercised on a throwaway production_job that's deleted afterwards.
"""
import io
import shutil
import types

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.database import Branch, SessionLocal
from app.models.mes import ChassisRecord, ProductionJob
from app.schemas.chassis import ChassisEventCapture, ChassisRecordCreate, ChassisRecordUpdate
from app.services import chassis as svc
from app.services.chassis_integrity import ChassisIntegrityError
from app.services import file_store
from app.services import production_jobs as pj_svc

_VIN_PREFIX = "ZZTESTV428"
_WHO = "pytest_v428"
_USER = types.SimpleNamespace(username=_WHO, id=None)


def _branch_id(db):
    return db.execute(select(Branch.id).order_by(Branch.id)).scalars().first()


def _cleanup_chassis(db):
    """Hard-delete all test chassis (CASCADE clears their events + photos) and any photo files."""
    recs = db.execute(
        select(ChassisRecord).where(ChassisRecord.vin.like(f"{_VIN_PREFIX}%"))
    ).scalars().all()
    for r in recs:
        shutil.rmtree(file_store.chassis_photo_abspath(str(r.id)), ignore_errors=True)
        db.delete(r)
    db.commit()


class _FakeUpload:
    """Mimics Starlette's UploadFile shape (.filename / .content_type / .file) for add_photos."""
    def __init__(self, filename, data, content_type="image/png"):
        self.filename = filename
        self.content_type = content_type
        self.file = io.BytesIO(data)


def _vin(suffix=""):
    # WO v4.36a — these fixtures pre-dated strict-VIN enforcement; build a conformant 17-char ISO-3779 VIN
    # (no I/O/Q), keeping the ZZTESTV428 prefix for cleanup/search. Strip I/O/Q from the tag, pad to 17.
    s = "".join(ch for ch in suffix.upper() if ch not in "IOQ")
    return (f"{_VIN_PREFIX}{s}".ljust(17, "0"))[:17]


def _create(db, suffix, **kw):
    kw.setdefault("make", "HINO")   # WO v4.36a §0.7 — AC now requires make/model server-side
    return svc.create_chassis(db, ChassisRecordCreate(vin=_vin(suffix), **kw), _WHO)


# ── create / read ────────────────────────────────────────────────────────────
def test_create_sets_manual_source_and_received_status():
    with SessionLocal() as db:
        _cleanup_chassis(db)
        try:
            rec = _create(db, "A", customer_name="Test Cust", make="HINO")
            assert rec.source == "manual" and rec.status == "received"
            detail = svc.get_detail(db, rec.id)
            assert detail.vin == _vin("A")
            assert detail.event_count == 0 and detail.events == []
        finally:
            _cleanup_chassis(db)


def test_duplicate_vin_raises_409():
    with SessionLocal() as db:
        _cleanup_chassis(db)
        try:
            _create(db, "B")
            try:
                _create(db, "B")   # WO v4.36a — dup VIN with no job to adopt onto → 409 (no longer adoptable)
                raise AssertionError("expected 409 on duplicate VIN")
            except ChassisIntegrityError as e:
                assert e.status_code == 409
        finally:
            _cleanup_chassis(db)


def test_list_finds_by_vin_query():
    with SessionLocal() as db:
        _cleanup_chassis(db)
        try:
            rec = _create(db, "CLIST", customer_name="Findable Co")
            found = svc.list_chassis(db, q=_vin("CLIST"))
            assert any(r.id == rec.id for r in found)
        finally:
            _cleanup_chassis(db)


def test_update_persists_fields():
    with SessionLocal() as db:
        _cleanup_chassis(db)
        try:
            rec = _create(db, "U")
            svc.update_chassis(db, rec.id, ChassisRecordUpdate(customer_name="Renamed", make="FAW"), _WHO)
            again = svc.get_detail(db, rec.id)
            assert again.customer_name == "Renamed" and again.make == "FAW"
        finally:
            _cleanup_chassis(db)


# ── WO v4.36b — chassis-field unification: dealer + tail-lift on the edit chokepoint ──
def _a_dealer_id(db):
    """An existing is_dealer=true customer id (read-only — customers live in the costings/SAP DB);
    skip when the DB carries no dealer (e.g. a minimal mock seed)."""
    from app.database import Customer
    return db.execute(
        select(Customer.id).where(Customer.is_dealer.is_(True)).order_by(Customer.id)).scalars().first()


def test_update_persists_dealer_and_tail_lift():
    """update_chassis writes dealer_id (validated is_dealer) + tail_lift_code onto chassis_records —
    the two columns the v4.36b shared form added so the Edit modal + Planning-ack share one truth."""
    with SessionLocal() as db:
        _cleanup_chassis(db)
        try:
            dealer_id = _a_dealer_id(db)
            if dealer_id is None:
                pytest.skip("no is_dealer customer on this DB")
            rec = _create(db, "DLR")
            out = svc.update_chassis(
                db, rec.id, ChassisRecordUpdate(dealer_id=dealer_id, tail_lift_code="TL-500"), _WHO)
            assert out.dealer_id == dealer_id and out.tail_lift_code == "TL-500"
            with SessionLocal() as db2:                       # committed → visible to a fresh session
                again = db2.get(ChassisRecord, rec.id)
                assert again.dealer_id == dealer_id and again.tail_lift_code == "TL-500"
        finally:
            _cleanup_chassis(db)


def test_update_rejects_non_dealer_422():
    """dealer_id must reference a customer flagged is_dealer — an unknown/non-dealer id 422s
    (chassis_integrity.validate_dealer), so the edit door can't smuggle a bad supplier link."""
    with SessionLocal() as db:
        _cleanup_chassis(db)
        try:
            rec = _create(db, "NDLR")
            try:
                svc.update_chassis(db, rec.id, ChassisRecordUpdate(dealer_id=999_999_999), _WHO)
                raise AssertionError("expected 422 on a non-dealer dealer_id")
            except ChassisIntegrityError as e:
                assert e.status_code == 422
        finally:
            _cleanup_chassis(db)


# ── VCL / DCL cycle logic ─────────────────────────────────────────────────────
def test_vcl_opens_cycle_and_dcl_closes_it():
    with SessionLocal() as db:
        _cleanup_chassis(db)
        try:
            rec = _create(db, "CYC")
            vcl = svc.capture_event(db, rec.id, "VCL", ChassisEventCapture(), _WHO)
            assert vcl.cycle_number == 1
            db.refresh(rec)
            assert rec.status == "in_workshop"
            dcl = svc.capture_event(db, rec.id, "DCL", ChassisEventCapture(), _WHO)
            assert dcl.cycle_number == 1            # DCL closes the open cycle
            db.refresh(rec)
            assert rec.status == "dispatched"
            detail = svc.get_detail(db, rec.id)
            assert detail.event_count == 2
        finally:
            _cleanup_chassis(db)


def test_second_vcl_opens_cycle_two():
    with SessionLocal() as db:
        _cleanup_chassis(db)
        try:
            rec = _create(db, "MULTI")
            svc.capture_event(db, rec.id, "VCL", ChassisEventCapture(), _WHO)
            svc.capture_event(db, rec.id, "DCL", ChassisEventCapture(), _WHO)
            vcl2 = svc.capture_event(db, rec.id, "VCL", ChassisEventCapture(), _WHO)
            assert vcl2.cycle_number == 2           # re-book-in opens a fresh cycle
        finally:
            _cleanup_chassis(db)


def test_dcl_without_open_cycle_raises_422():
    with SessionLocal() as db:
        _cleanup_chassis(db)
        try:
            rec = _create(db, "NODCL")
            try:
                svc.capture_event(db, rec.id, "DCL", ChassisEventCapture(), _WHO)
                raise AssertionError("expected 422 — no open cycle to dispatch")
            except HTTPException as e:
                assert e.status_code == 422
        finally:
            _cleanup_chassis(db)


def test_duplicate_event_in_cycle_raises_409():
    with SessionLocal() as db:
        _cleanup_chassis(db)
        try:
            rec = _create(db, "DUP")
            svc.capture_event(db, rec.id, "VCL", ChassisEventCapture(cycle_number=1), _WHO)
            try:
                svc.capture_event(db, rec.id, "VCL", ChassisEventCapture(cycle_number=1), _WHO)
                raise AssertionError("expected 409 — VCL already captured for cycle 1")
            except HTTPException as e:
                assert e.status_code == 409
        finally:
            _cleanup_chassis(db)


def test_capture_on_missing_record_raises_404():
    with SessionLocal() as db:
        try:
            svc.capture_event(db, 999_000_111, "VCL", ChassisEventCapture(), _WHO)
            raise AssertionError("expected 404 — chassis record not found")
        except HTTPException as e:
            assert e.status_code == 404


# ── photo upload (file-store seam) ─────────────────────────────────────────────
def test_photo_upload_attaches_and_resolves():
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32            # tiny fake image payload
    with SessionLocal() as db:
        _cleanup_chassis(db)
        try:
            rec = _create(db, "PHOTO")
            evt = svc.capture_event(db, rec.id, "VCL", ChassisEventCapture(), _WHO)
            out = svc.add_photos(db, rec.id, evt.id, [_FakeUpload("front.png", png)], _WHO)
            assert len(out) == 1
            assert out[0].url == f"/api/chassis-records/photos/{out[0].id}"
            assert out[0].size_bytes == len(png)
            photo, path = svc.get_photo_file(db, out[0].id)   # resolves on disk
            assert path.endswith("front.png")
            # the photo shows up under the event in the detail read
            detail = svc.get_detail(db, rec.id)
            assert detail.events[0].photos[0].id == out[0].id
        finally:
            _cleanup_chassis(db)


def test_photo_upload_wrong_event_raises_404():
    with SessionLocal() as db:
        _cleanup_chassis(db)
        try:
            rec = _create(db, "PWRONG")
            try:
                svc.add_photos(db, rec.id, 999_000_222, [_FakeUpload("x.png", b"x")], _WHO)
                raise AssertionError("expected 404 — event not found for this chassis")
            except HTTPException as e:
                assert e.status_code == 404
        finally:
            _cleanup_chassis(db)


# ── Flag E — chassis-received tick / un-tick (production_jobs) ─────────────────
def test_mark_then_unmark_chassis_received():
    """Flag E: marking sets the receipt (bypasses the planning chassis-ETA gate); un-ticking
    clears it (re-enables the gate)."""
    with SessionLocal() as db:
        job = ProductionJob(branch_id=_branch_id(db), status="planning", bom_status="manual")
        db.add(job)
        db.commit()
        job_id = job.id
        try:
            row = pj_svc.mark_chassis_received(db, job_id, _USER)
            assert row[0].chassis_received_at is not None
            assert row[0].chassis_received_by == _WHO
            row = pj_svc.unmark_chassis_received(db, job_id, _USER)
            assert row[0].chassis_received_at is None
            assert row[0].chassis_received_by is None
        finally:
            db.delete(db.get(ProductionJob, job_id))
            db.commit()
