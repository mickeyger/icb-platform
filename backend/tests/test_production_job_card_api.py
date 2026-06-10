"""WO v4.31 §3.2 — job-card modal enrichment: GET /api/production-jobs/{id} read-only enrichment.

Asserts the endpoint nests (a) the current generated_bom + its lines, (b) the chassis with its
lifecycle events (latest VCL carries checklist + condition notes), and (c) bay context (resolved bay
code + assembly-assigned timestamp) — plus the two no-data placeholder paths (no BOM, no chassis).
All read-only; no write paths. Fixtures build a self-contained job and clean up (FK-safe order:
delete the job first — cascades the BOM + lines + frees the chassis ref — then the chassis).
"""
import uuid
from datetime import date

import pytest


@pytest.fixture(scope="module")
def app_mod():
    import app.main as m
    from starlette.testclient import TestClient
    with TestClient(m.app) as _c:
        yield m


@pytest.fixture
def admin():
    from app.database import SessionLocal, User
    with SessionLocal() as db:
        return db.query(User).filter_by(username="admin").first()


@pytest.fixture
def api(app_mod, admin):
    from app.deps import require_user
    from starlette.testclient import TestClient
    app_mod.app.dependency_overrides[require_user] = lambda: admin
    with TestClient(app_mod.app) as c:
        yield c
    app_mod.app.dependency_overrides.pop(require_user, None)


@pytest.fixture
def jobcard(app_mod):
    """Factory -> id of a production job, optionally with a current generated_bom (+2 lines) and a
    booked-in chassis assigned to an assembly bay (VCL + assembly_assigned events). Cleaned up."""
    from app.database import Branch, SessionLocal
    from app.models.mes import (
        AssemblyBay, BomLine, ChassisLifecycleEvent, ChassisRecord, GeneratedBom, ProductionJob,
    )
    jobs, chassis = [], []

    def _make(with_chassis=True, with_bom=True):
        with SessionLocal() as db:
            jhb = db.query(Branch).filter_by(code="JHB").first()
            ch_id = None
            if with_chassis:
                bay = db.query(AssemblyBay).order_by(AssemblyBay.sort_order).first()
                # No denormalised bay column (§0.12) — status='in_assembly' + the assembly_assigned
                # event below carry the bay; get_detail derives current_assembly_bay_id from the event.
                rec = ChassisRecord(vin=f"JC{uuid.uuid4().hex[:12].upper()}", source="manual",
                                    status="in_assembly")
                db.add(rec)
                db.commit()
                db.refresh(rec)
                db.add(ChassisLifecycleEvent(
                    chassis_record_id=rec.id, cycle_number=1, event_type="VCL", event_date=date.today(),
                    checklist_json={"tyres": True, "mileage": "12000"}, notes="minor scratch on door"))
                db.add(ChassisLifecycleEvent(
                    chassis_record_id=rec.id, cycle_number=1, event_type="assembly_assigned",
                    assembly_bay_id=bay.id, event_date=date.today()))
                db.commit()
                ch_id = rec.id
                chassis.append(rec.id)
            job = ProductionJob(branch_id=jhb.id, source="workbook", status="in_production",
                                job_number=f"JC{uuid.uuid4().hex[:6]}", chassis_record_id=ch_id)
            db.add(job)
            db.commit()
            db.refresh(job)
            jobs.append(job.id)
            if with_bom:
                gb = GeneratedBom(production_job_id=job.id, version=1, bom_status="complete",
                                  grand_total=1500, current=True)
                db.add(gb)
                db.commit()
                db.refresh(gb)
                db.add(BomLine(generated_bom_id=gb.id, sap_code="INS-PUR-50", description="PUR panel 50mm",
                               qty=4, unit_price=250, line_total=1000, section="Walls", line_order=1))
                db.add(BomLine(generated_bom_id=gb.id, sap_code="DOOR-STD", description="Std door",
                               qty=1, unit_price=500, line_total=500, section="Doors", line_order=2))
                job.current_bom_id = gb.id
                db.commit()
            return job.id

    yield _make
    with SessionLocal() as db:
        for jid in jobs:                       # delete job first -> cascades BOM+lines, frees chassis ref
            j = db.get(ProductionJob, jid)
            if j:
                db.delete(j)
        db.commit()
        for cid in chassis:                    # then the chassis -> cascades its lifecycle events
            r = db.get(ChassisRecord, cid)
            if r:
                db.delete(r)
        db.commit()


def test_jobcard_enrichment_full(api, jobcard):
    d = api.get(f"/api/production-jobs/{jobcard(with_chassis=True, with_bom=True)}").json()
    # (a) current BOM + lines
    cb = d["current_bom"]
    assert cb and cb["bom_status"] == "complete" and len(cb["lines"]) == 2
    line = cb["lines"][0]
    assert line["sap_code"] == "INS-PUR-50" and line["qty"] == 4.0
    assert line["unit_price"] == 250.0 and line["line_total"] == 1000.0 and line["section"] == "Walls"
    # (b) chassis + latest VCL (checklist + condition notes)
    ch = d["chassis"]
    assert ch and ch["status"] == "in_assembly"
    vcl = [e for e in ch["events"] if e["event_type"] == "VCL"]
    assert vcl and vcl[-1]["checklist_json"] and vcl[-1]["notes"] == "minor scratch on door"
    # (c) bay context — resolved code + assigned-at (duration)
    assert d["current_assembly_bay_code"] and d["current_assembly_bay_code"].startswith("AssemblyBay-")
    assert d["assembly_assigned_at"] is not None


def test_jobcard_no_chassis_no_bom_placeholders(api, jobcard):
    d = api.get(f"/api/production-jobs/{jobcard(with_chassis=False, with_bom=False)}").json()
    assert d["current_bom"] is None              # frontend -> "BOM not yet generated"
    assert d["chassis"] is None                  # frontend -> "Chassis pending — not yet received"
    assert d["current_assembly_bay_code"] is None and d["assembly_assigned_at"] is None
