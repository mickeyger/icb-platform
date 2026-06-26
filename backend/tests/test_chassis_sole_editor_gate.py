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
        db.execute(text("DELETE FROM icb_mes.chassis_records WHERE created_source_ref LIKE :m"), {"m": f"{_MARK}%"})
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
        rows = db.query(ChassisRecordAudit).filter_by(chassis_id=rid, source="soft_delete").all()
        assert len(rows) == 1
        assert rows[0].new_value == "junk dupe" and rows[0].edited_by_name == f"{_MARK}_del"
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
