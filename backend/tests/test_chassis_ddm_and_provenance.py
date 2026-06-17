"""WO v4.34 §3.7 — chassis-type DDM endpoint + manual-create provenance (the provenance pill data).
P437 markers where a DB row is made."""


def test_chassis_models_endpoint_returns_ddm():
    import app.main as m
    from app.database import SessionLocal, User
    from app.deps import require_user
    from starlette.testclient import TestClient
    with SessionLocal() as db:
        admin = db.query(User).filter_by(username="admin").first()
    m.app.dependency_overrides[require_user] = lambda: admin
    try:
        with TestClient(m.app) as c:
            rows = c.get("/api/chassis-records/models").json()
            assert isinstance(rows, list) and len(rows) >= 10
            by_code = {r["code"]: r for r in rows}
            assert "ISUZU-FTR-850-AMT" in by_code               # seeded starter vocabulary
            isuzu = by_code["ISUZU-FTR-850-AMT"]
            assert isuzu["make"] == "Isuzu" and isuzu["model"] == "FTR 850 AMT (MY22)"
            assert isuzu["category"] == "truck"
    finally:
        m.app.dependency_overrides.pop(require_user, None)


def test_manual_create_sets_provenance():
    from app.database import SessionLocal, User
    from app.models.mes import ChassisRecord
    from app.schemas.chassis import ChassisRecordCreate
    from app.services import chassis as svc
    vin = "P437TESTVN0000001"   # WO v4.36a — conformant 17-char ISO-3779 (was 'P437TESTVIN0001')
    with SessionLocal() as db:
        db.query(ChassisRecord).filter(ChassisRecord.vin == vin).delete()
        db.commit()
        rec = svc.create_chassis(
            db, ChassisRecordCreate(vin=vin, make="Isuzu", model="FTR 850 AMT (MY22)"), who="admin")
        rid = rec.id
        try:
            detail = svc.get_detail(db, rid)
            assert detail.created_via == "manual_chassis_menu"   # §0.4 provenance
            assert detail.source == "manual"
            assert detail.status == "received"
            assert detail.make == "Isuzu"
        finally:
            db.query(ChassisRecord).filter(ChassisRecord.id == rid).delete()
            db.commit()


def test_provenance_serialises_in_list():
    """ChassisRecordOut carries created_via/created_source_ref so the list can render the pill."""
    from app.database import SessionLocal, User
    from app.models.mes import ChassisRecord
    from app.schemas.chassis import ChassisRecordCreate
    from app.services import chassis as svc
    vin = "P437TESTVN0000002"   # WO v4.36a — conformant 17-char ISO-3779 (was 'P437TESTVIN0002')
    with SessionLocal() as db:
        db.query(ChassisRecord).filter(ChassisRecord.vin == vin).delete()
        db.commit()
        rid = svc.create_chassis(db, ChassisRecordCreate(vin=vin, make="Isuzu"), who="admin").id
        try:
            rows = svc.list_chassis(db, q=vin)
            assert rows and rows[0].created_via == "manual_chassis_menu"
        finally:
            db.query(ChassisRecord).filter(ChassisRecord.id == rid).delete()
            db.commit()
