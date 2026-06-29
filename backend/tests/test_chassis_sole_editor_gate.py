"""WO v4.36.5 §3.1 — the chassis sole-editor chokepoint: role-gate, optimistic lock, per-field audit.

Service-level (no TestClient): calls services.chassis.update_chassis directly. Self-purging via the
'V4365GATE' created_source_ref / edited_by_name marker — no real chassis touched. Runs on CI/icb_test
(migration 0029 applied → version column + chassis_records_audit table); collects green locally.
"""
import pytest
from fastapi import HTTPException

_MARK = "V4365GATE"


def _purge():
    from sqlalchemy import text
    from app.database import SessionLocal
    with SessionLocal() as db:
        # CASCADE handles audit rows when a chassis is deleted; the edited_by_name sweep is belt-and-braces.
        db.execute(text("DELETE FROM icb_mes.chassis_records_audit WHERE edited_by_name LIKE :m"), {"m": f"{_MARK}%"})
        db.execute(text("DELETE FROM icb_mes.prejob_cards WHERE body_description LIKE :m"), {"m": f"{_MARK}%"})  # §3.9 unlink test
        db.execute(text("DELETE FROM icb_mes.production_jobs WHERE job_number LIKE :m"), {"m": f"{_MARK}%"})    # §3.8 link-path tests
        db.execute(text("DELETE FROM icb_mes.chassis_records WHERE created_source_ref LIKE :m"), {"m": f"{_MARK}%"})
        db.execute(text("DELETE FROM icb_costings.calculations WHERE quote_number LIKE :m"), {"m": f"{_MARK}%"})
        db.commit()


@pytest.fixture(autouse=True)
def _clean():
    _purge()
    yield
    _purge()


def _make_chassis(**kw) -> int:
    from app.database import SessionLocal
    from app.models.mes import ChassisRecord
    with SessionLocal() as db:
        rec = ChassisRecord(vin=None, status="expected", source="manual",
                            created_via="manual_chassis_menu", created_source_ref=f"{_MARK} ref", **kw)
        db.add(rec)
        db.commit()
        return rec.id


def test_production_role_blocked_403():
    """Q1 — production is read-only on chassis attributes; admin/planner edit."""
    from app.database import SessionLocal
    from app.services.chassis import update_chassis
    from app.schemas.chassis import ChassisRecordUpdate
    rid = _make_chassis(make="Isuzu FTR")
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as ei:
            update_chassis(db, rid, ChassisRecordUpdate(notes="x"), who=f"{_MARK}_prod", actor_role="production")
    assert ei.value.status_code == 403


def test_planner_edit_allowed_and_audited():
    """admin/planner edits apply, bump version, and write a per-field chassis_records_audit row."""
    from app.database import SessionLocal
    from app.services.chassis import update_chassis
    from app.schemas.chassis import ChassisRecordUpdate
    from app.models.mes import ChassisRecordAudit
    rid = _make_chassis(make="Hino 300")
    with SessionLocal() as db:
        rec = update_chassis(db, rid, ChassisRecordUpdate(notes="checked", make="Hino 500"),
                             who=f"{_MARK}_plan", actor_role="planner")
        assert rec.notes == "checked" and rec.make == "Hino 500"
        assert rec.version == 1                                   # bumped on a real change
        by_field = {r.field_name: r for r in db.query(ChassisRecordAudit).filter_by(chassis_id=rid).all()}
        assert "make" in by_field and "notes" in by_field
        assert by_field["make"].old_value == "Hino 300" and by_field["make"].new_value == "Hino 500"
        assert by_field["make"].source == "chassis_page"
        assert by_field["make"].edited_by_name == f"{_MARK}_plan"
        assert by_field["notes"].old_value is None and by_field["notes"].new_value == "checked"


def test_optimistic_lock_stale_version_409():
    """A stale `version` (someone saved in between) → 409; the correct version applies + re-bumps."""
    from app.database import SessionLocal
    from app.services.chassis import update_chassis
    from app.schemas.chassis import ChassisRecordUpdate
    rid = _make_chassis(make="UD Croner")
    with SessionLocal() as db:                                    # first edit → version 0→1
        update_chassis(db, rid, ChassisRecordUpdate(notes="v1"), who=f"{_MARK}_a", actor_role="admin")
    with SessionLocal() as db:                                    # stale version 0 → 409
        with pytest.raises(HTTPException) as ei:
            update_chassis(db, rid, ChassisRecordUpdate(notes="v2", version=0), who=f"{_MARK}_b", actor_role="admin")
        assert ei.value.status_code == 409
    with SessionLocal() as db:                                    # correct version 1 → applies → 2
        rec = update_chassis(db, rid, ChassisRecordUpdate(notes="v2", version=1), who=f"{_MARK}_c", actor_role="admin")
        assert rec.notes == "v2" and rec.version == 2


def test_no_op_edit_does_not_bump_version_or_audit():
    """Setting a field to its current value is a no-op — no audit row, no version bump (avoids false conflicts)."""
    from app.database import SessionLocal
    from app.services.chassis import update_chassis
    from app.schemas.chassis import ChassisRecordUpdate
    from app.models.mes import ChassisRecordAudit
    rid = _make_chassis(make="Fuso FA")
    with SessionLocal() as db:
        rec = update_chassis(db, rid, ChassisRecordUpdate(make="Fuso FA"), who=f"{_MARK}_n", actor_role="admin")
        assert rec.version == 0
        assert db.query(ChassisRecordAudit).filter_by(chassis_id=rid).count() == 0


def test_soft_delete_and_restore_are_audited():
    """WO §3.2 — structural ops are trailed too (source='soft_delete'/'restore'): 'who deleted/restored this?'."""
    from app.database import SessionLocal
    from app.services.chassis import soft_delete_chassis
    from app.services.chassis_merge import restore_chassis
    from app.models.mes import ChassisRecordAudit
    rid = _make_chassis(make="Tata LPT")
    with SessionLocal() as db:
        soft_delete_chassis(db, rid, who=f"{_MARK}_del", reason="junk dupe")
        rows = {r.field_name: r for r in db.query(ChassisRecordAudit).filter_by(chassis_id=rid, source="soft_delete").all()}
        assert "deleted_at" in rows and "deletion_reason" in rows         # §3.8 — real timestamp + a separate reason row
        assert rows["deletion_reason"].new_value == "junk dupe" and rows["deletion_reason"].edited_by_name == f"{_MARK}_del"
    with SessionLocal() as db:
        restore_chassis(db, rid, who=f"{_MARK}_res")
        assert db.query(ChassisRecordAudit).filter_by(chassis_id=rid, source="restore").count() == 1


def test_merge_is_audited():
    """WO §3.2 — a merge trails source='merge' on the loser, pointing at the winner."""
    from app.database import SessionLocal
    from app.services.chassis_merge import merge_chassis
    from app.models.mes import ChassisRecordAudit
    loser = _make_chassis(make="Loser FTR")
    winner = _make_chassis(make="Winner FTR")
    with SessionLocal() as db:
        merge_chassis(db, loser_id=loser, winner_id=winner, who=f"{_MARK}_mrg")
        rows = db.query(ChassisRecordAudit).filter_by(chassis_id=loser, source="merge").all()
        assert len(rows) == 1
        assert rows[0].field_name == "merged_into_id" and rows[0].new_value == str(winner)


def test_list_chassis_audit_returns_trail_recent_first():
    """WO §3.4 — list_chassis_audit returns the chassis's audit rows, most-recent-first (created_at/id desc)."""
    from app.database import SessionLocal
    from app.services.chassis import update_chassis, list_chassis_audit
    from app.schemas.chassis import ChassisRecordUpdate
    rid = _make_chassis(make="Scania P")
    with SessionLocal() as db:
        update_chassis(db, rid, ChassisRecordUpdate(make="Scania R", notes="n1"), who=f"{_MARK}_a", actor_role="planner")
    with SessionLocal() as db:
        rows = list_chassis_audit(db, rid)
        assert len(rows) >= 2 and all(r.chassis_id == rid for r in rows)
        assert rows[0].id > rows[-1].id                          # most-recent-first (desc)
        assert {r.field_name for r in rows} >= {"make", "notes"}


# ── WO v4.36.5 §3.8 — the chokepoint-leak closures + the fail-closed gate ──────────────────────────────
_VIN_OK = "V4365VN0000000000"   # 17-char ISO-3779-conformant marker VIN (no I/O/Q)


def _make_job() -> int:
    """A minimal marker ProductionJob (+ its marker calc) for the link-path tests; purged via _MARK."""
    import json
    import uuid
    from app.database import SessionLocal, Branch, CalculationRecord
    from app.models.mes import ProductionJob
    with SessionLocal() as db:
        jhb = db.query(Branch).filter_by(code="JHB").first()
        c = CalculationRecord(quote_number=f"{_MARK}{uuid.uuid4().hex[:8]}", status="accepted", branch_id=jhb.id,
                              dimensions_json=json.dumps({"body_type": "Test"}), result_json=json.dumps({"selling_zar": 1.0}))
        db.add(c)
        db.commit()
        db.refresh(c)
        pj = ProductionJob(calculation_record_id=c.id, branch_id=jhb.id, job_number=f"{_MARK}J{c.id}", status="planning")
        db.add(pj)
        db.commit()
        return pj.id


def test_capture_vin_audited():
    """§3.8 finding 1 — late VIN capture now flows through the chokepoint: vin + vin_source audited."""
    from app.database import SessionLocal
    from app.services.chassis import capture_vin
    from app.models.mes import ChassisRecordAudit
    rid = _make_chassis(make="Isuzu FVR")                    # vin=None stub
    with SessionLocal() as db:
        capture_vin(db, rid, _VIN_OK, who=f"{_MARK}_vin")
        by = {r.field_name: r for r in db.query(ChassisRecordAudit).filter_by(chassis_id=rid).all()}
        assert "vin" in by and "vin_source" in by
        assert by["vin"].old_value is None and by["vin"].new_value == _VIN_OK and by["vin"].source == "chassis_page"
        assert by["vin_source"].new_value == "chassis_page_manual"


def test_status_transition_audited():
    """§3.8 finding 2 (+ the body_gap 5th leak) — a VCL transition trails status + the Body-Gap lift, source per-event."""
    from datetime import date
    from app.database import SessionLocal
    from app.services.chassis import capture_event
    from app.schemas.chassis import ChassisEventCapture
    from app.models.mes import ChassisRecordAudit
    rid = _make_chassis(make="Hino FVR")
    with SessionLocal() as db:
        capture_event(db, rid, "VCL",
                      ChassisEventCapture(event_date=date.today(), checklist_json={"body_gap_mm": "50"}),
                      who=f"{_MARK}_vcl")
        by = {r.field_name: r for r in db.query(ChassisRecordAudit).filter_by(chassis_id=rid).all()}
        assert "status" in by and by["status"].source == "vcl"
        assert "body_gap_mm" in by and by["body_gap_mm"].new_value == "50"


def test_role_gate_fail_closed():
    """§3.8 finding 7 — the role-gate is FAIL-CLOSED: a None actor_role is refused (403), not waved through."""
    from app.database import SessionLocal
    from app.services.chassis import update_chassis
    from app.schemas.chassis import ChassisRecordUpdate
    rid = _make_chassis(make="UD Quon")
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as ei:
            update_chassis(db, rid, ChassisRecordUpdate(notes="x"), who=f"{_MARK}_none", actor_role=None)
        assert ei.value.status_code == 403


def test_soft_delete_audit_shape():
    """§3.8 finding 5 — soft-delete trails the REAL deleted_at timestamp (parseable) + a separate deletion_reason row."""
    from datetime import datetime
    from app.database import SessionLocal
    from app.services.chassis import soft_delete_chassis
    from app.models.mes import ChassisRecordAudit
    rid = _make_chassis(make="FAW Junk")
    with SessionLocal() as db:
        soft_delete_chassis(db, rid, who=f"{_MARK}_del", reason="junk dupe")
        rows = {r.field_name: r for r in db.query(ChassisRecordAudit).filter_by(chassis_id=rid, source="soft_delete").all()}
        assert "deleted_at" in rows and "deletion_reason" in rows
        datetime.fromisoformat(rows["deleted_at"].new_value)         # the value is a real timestamp, not a sentinel string
        assert rows["deletion_reason"].new_value == "junk dupe"


def test_chokepoint_stamps_updated_by_and_actor_id():
    """§3.8 finding 8 mechanism — the chokepoint OWNS updated_by, and a passed actor_id lands on edited_by_user_id
    (the planning-ack path now passes it; this proves the row the ack writes carries the actor FK)."""
    from app.database import SessionLocal, User
    from app.services.chassis import _apply_chassis_fields
    from app.models.mes import ChassisRecord, ChassisRecordAudit
    rid = _make_chassis(make="Scania R")
    with SessionLocal() as db:
        uid = db.query(User).filter_by(username="admin").first().id     # a REAL user — the cross-schema FK is enforced (SET NULL)
        rec = db.get(ChassisRecord, rid)
        _apply_chassis_fields(db, rec, {"notes": "via chokepoint"}, who=f"{_MARK}_ck", source="planning_ack", actor_id=uid)
        db.commit()
        assert rec.updated_by == f"{_MARK}_ck"                       # chokepoint stamped updated_by
        row = db.query(ChassisRecordAudit).filter_by(chassis_id=rid, field_name="notes").first()
        assert row is not None and row.edited_by_user_id == uid and row.source == "planning_ack"


def test_create_chassis_stub_adoption_audited():
    """§3.8 finding 3 — stub→real adoption (a job's live placeholder gets the real VIN/make stamped) is audited."""
    from app.database import SessionLocal
    from app.services.chassis import create_chassis
    from app.schemas.chassis import ChassisRecordCreate
    from app.models.mes import ChassisRecordAudit, ProductionJob
    ph = _make_chassis(make="")                                  # a live placeholder stub (status defaults to 'expected')
    jid = _make_job()
    with SessionLocal() as db:                                   # link the job to the placeholder
        db.get(ProductionJob, jid).chassis_record_id = ph
        db.commit()
    with SessionLocal() as db:
        create_chassis(db, ChassisRecordCreate(vin=_VIN_OK[:-1] + "1", production_job_id=jid, make="Isuzu FVR"),
                       who=f"{_MARK}_adopt")
        by = {r.field_name: r for r in db.query(ChassisRecordAudit).filter_by(chassis_id=ph).all()}
        assert "vin" in by and "make" in by                      # the adoption stamped + audited the real values
        assert by["vin"].source == "stub_adoption"               # §3.9 tightening — pin the source label


def test_retrofit_link_audited_with_actor():
    """§3.8 finding 6 — admin Find-Orphan retrofit_link routes through update_chassis WITH the actor, so the gate
    runs and the audit row carries edited_by_user_id."""
    from app.database import SessionLocal, User
    from app.services.chassis import retrofit_link
    from app.models.mes import ChassisRecordAudit
    rid = _make_chassis(make="MAN Orphan", customer_name=None)   # an orphan (no job link)
    jid = _make_job()
    with SessionLocal() as db:
        uid = db.query(User).filter_by(username="admin").first().id
        retrofit_link(db, rid, jid, who=f"{_MARK}_admin", actor_role="admin", actor_id=uid)
        rows = db.query(ChassisRecordAudit).filter_by(chassis_id=rid).all()
        assert rows and any(r.edited_by_user_id == uid for r in rows)


# ── WO v4.36.5 §3.9 — the 3 status-transition leaks the §3.8 close-verify sweep found (qc.signoff +
#    2 orphaning sites) + the fail-closed retrofit variant ──────────────────────────────────────────────
def test_retrofit_link_fail_closed():
    """§3.9 tightening — retrofit_link inherits the fail-closed gate: a non-edit actor_role → 403."""
    from app.database import SessionLocal
    from app.services.chassis import retrofit_link
    rid = _make_chassis(make="MAN Orphan2", customer_name=None)
    jid = _make_job()
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as ei:
            retrofit_link(db, rid, jid, who=f"{_MARK}_prod", actor_role="production", actor_id=None)
        assert ei.value.status_code == 403


def test_reconcile_orphan_audited():
    """§3.9 leak 3 — reconcile_anchorless_chassis(apply=True) routes the orphaning transition through the chokepoint
    (system actor). Isolation-safe: asserts in-session then rolls back (the sweep marks every anchorless row)."""
    from app.database import SessionLocal
    from app.services.integrity import reconcile_anchorless_chassis
    from app.models.mes import ChassisRecord, ChassisRecordAudit
    rid = _make_chassis(make="Anchorless")        # 'expected', no job, no card → anchorless
    with SessionLocal() as db:
        reconcile_anchorless_chassis(db, apply=True)
        db.flush()                                 # autoflush=False — surface the in-session writes; NO commit
        assert db.get(ChassisRecord, rid).status == "expected_orphaned"
        row = db.query(ChassisRecordAudit).filter_by(chassis_id=rid, field_name="status",
                                                     source="reconcile_orphaned").first()
        assert row is not None and row.new_value == "expected_orphaned" and row.edited_by_name == "system"


def test_qc_signoff_dispatch_audited():
    """§3.9 leak 1 — a PASS QC sign-off routes the dispatch transition through the chokepoint (source='qc_passed')."""
    from sqlalchemy import select
    from app.database import SessionLocal, User
    from app.services.qc import signoff
    from app.models.mes import ChassisRecord, ChassisRecordAudit, DefectCategory, QcInspection
    rid = _make_chassis(make="Hino QC")
    with SessionLocal() as db:
        admin = db.query(User).filter_by(username="admin").first()
        aid = admin.id
        db.get(ChassisRecord, rid).status = "awaiting_qa"            # precondition (setup, not the path under test)
        cats = db.execute(select(DefectCategory).where(DefectCategory.is_active.is_(True))).scalars().all()
        for c in cats:
            db.add(QcInspection(chassis_record_id=rid, cycle_number=1, category_id=c.id,
                                category_name=c.name, verdict="pass", created_by=f"{_MARK}_qc"))
        db.commit()
        out = signoff(db, rid, notes=None, user=admin)
        assert out["overall_verdict"] == "pass" and out["new_status"] == "dispatched"
    with SessionLocal() as db:
        row = db.query(ChassisRecordAudit).filter_by(chassis_id=rid, field_name="status", source="qc_passed").first()
        assert row is not None and row.new_value == "dispatched" and row.edited_by_user_id == aid


def test_unlink_card_orphan_audited():
    """§3.9 leak 2 — releasing a card's auto-created, now-unreferenced chassis orphans it through the chokepoint."""
    import json
    import uuid
    from app.database import SessionLocal, Branch, CalculationRecord, User
    from app.models.mes import ChassisRecord, ChassisRecordAudit, PrejobCard
    from app.services.prejob_cards import _release_auto_created_chassis, _source_ref
    with SessionLocal() as db:
        jhb = db.query(Branch).filter_by(code="JHB").first()
        admin = db.query(User).filter_by(username="admin").first()
        aid = admin.id
        calc = CalculationRecord(quote_number=f"{_MARK}{uuid.uuid4().hex[:8]}", status="accepted", branch_id=jhb.id,
                                 dimensions_json=json.dumps({}), result_json=json.dumps({}))
        db.add(calc)
        db.commit()
        card = PrejobCard(calculation_id=calc.id, status="draft", body_description=f"{_MARK} card", sections=[])
        db.add(card)
        db.commit()
        ch = ChassisRecord(vin=None, status="expected", source="auto", created_via="pre_job_card",
                           created_source_ref=_source_ref(calc, card), make="Stub")
        db.add(ch)
        db.commit()
        card.chassis_record_id = ch.id
        db.commit()
        cid = ch.id
        _release_auto_created_chassis(db, card, who=admin.username, actor_id=aid)
        db.commit()
    with SessionLocal() as db:
        assert db.get(ChassisRecord, cid).status == "expected_orphaned"
        row = db.query(ChassisRecordAudit).filter_by(chassis_id=cid, field_name="status", source="unlink_card").first()
        assert row is not None and row.new_value == "expected_orphaned" and row.edited_by_user_id == aid
