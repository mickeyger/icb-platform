"""WO v4.34.1 §3.4b (Gap A) — late VIN capture: the backend NULL-state guard.

Covers: NULL->value accepted + vin_source='chassis_page_manual'; second write 409 (write-once —
the first real backend enforcement of sign-off integrity, ADR 0022 footnote); duplicate VIN 409
(uq_chassis_records_vin); empty 422. Marker VINs 'V4341VIN*'; self-purge, no real chassis touched.
"""
import pytest

_MARK = "V4341VIN"


def _purge(db):
    from sqlalchemy import text
    db.execute(text("DELETE FROM icb_mes.chassis_records WHERE created_source_ref LIKE :m OR vin LIKE :m"),
               {"m": f"{_MARK}%"})
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
        yield c
    app_mod.app.dependency_overrides.pop(require_user, None)
    with SessionLocal() as db:
        _purge(db)


def _expected_chassis(make: str) -> int:
    """An 'expected' chassis with vin=NULL — the Gap A precondition."""
    from app.database import SessionLocal
    from app.models.mes import ChassisRecord
    with SessionLocal() as db:
        rec = ChassisRecord(vin=None, status="expected", source="manual",
                            created_via="manual_chassis_menu", created_source_ref=f"{_MARK} ref",
                            make=make)
        db.add(rec)
        db.commit()
        return rec.id


def test_vin_capture_null_to_value_and_write_once(api):
    rid = _expected_chassis("Isuzu FTR")
    # NULL -> value: accepted, provenance stamped
    r = api.post(f"/api/chassis-records/{rid}/vin", json={"vin": f"{_MARK}001"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["vin"] == f"{_MARK}001"
    assert body["vin_source"] == "chassis_page_manual"
    # write-once: a second capture is refused (the NULL-state guard)
    r2 = api.post(f"/api/chassis-records/{rid}/vin", json={"vin": f"{_MARK}999"})
    assert r2.status_code == 409
    assert api.get(f"/api/chassis-records/{rid}").json()["vin"] == f"{_MARK}001"   # unchanged


def test_vin_capture_rejects_duplicate(api):
    r1 = _expected_chassis("Hino 500")
    r2 = _expected_chassis("UD Croner")
    assert api.post(f"/api/chassis-records/{r1}/vin", json={"vin": f"{_MARK}DUP"}).status_code == 200
    # same VIN on another record -> 409 clash (uq_chassis_records_vin)
    assert api.post(f"/api/chassis-records/{r2}/vin", json={"vin": f"{_MARK}DUP"}).status_code == 409


def test_vin_capture_empty_422(api):
    rid = _expected_chassis("Fuso FA")
    assert api.post(f"/api/chassis-records/{rid}/vin", json={"vin": "  "}).status_code == 422
