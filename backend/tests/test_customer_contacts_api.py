"""WO v4.34.1 §3.2 — customers `is_dealer` filter + customer_contacts CRUD.

Covers: is_dealer exposed/filterable on GET /api/customers (§0.2/§3.3 dealer typeahead source);
contacts list/create/update/soft-delete; set-primary atomic swap; the DB partial-unique guarantee
(one is_primary per customer) surfaced through the API; soft-delete frees the primary slot.

Uses an EXISTING customer (read-mostly on icb_costings; we only add/remove our own marker contacts
and a transient is_dealer flag, restored on teardown). Marker: contacts named 'V4341TEST*'.
"""
import pytest

_MARK = "V4341TEST"


def _purge(db) -> None:
    from sqlalchemy import text
    db.execute(text("DELETE FROM icb_costings.customer_contacts WHERE name LIKE :m"),
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
    """Admin via dependency override (no session cookie → CSRF middleware self-skips, per main.py)."""
    from app.database import SessionLocal, User
    from app.deps import require_admin, require_user
    from starlette.testclient import TestClient
    with SessionLocal() as db:
        _purge(db)
        admin = db.query(User).filter_by(username="admin").first()
    # require_admin calls require_user as a plain function (not a dependency), so override BOTH:
    # require_user for the GET reads, require_admin for the writes.
    app_mod.app.dependency_overrides[require_user] = lambda: admin
    app_mod.app.dependency_overrides[require_admin] = lambda: admin
    with TestClient(app_mod.app) as c:
        yield c
    app_mod.app.dependency_overrides.pop(require_user, None)
    app_mod.app.dependency_overrides.pop(require_admin, None)
    with SessionLocal() as db:
        _purge(db)


@pytest.fixture
def cust_id():
    """An arbitrary existing customer; restore its is_dealer flag after the test."""
    from app.database import Customer, SessionLocal
    with SessionLocal() as db:
        c = db.query(Customer).order_by(Customer.id).first()
        if c is None:
            pytest.skip("no customers on this DB")
        cid, was_dealer = c.id, bool(c.is_dealer)
    yield cid
    with SessionLocal() as db:
        c = db.query(Customer).filter_by(id=cid).first()
        if c is not None:
            c.is_dealer = was_dealer
            db.commit()


def test_is_dealer_exposed_and_filterable(api, cust_id):
    # Flag the customer as a dealer, then confirm ?is_dealer=true includes it and =false excludes it.
    assert api.put(f"/api/customers/{cust_id}", json={"is_dealer": True}).status_code == 200
    dealers = api.get("/api/customers", params={"is_dealer": "true"}).json()
    assert any(c["id"] == cust_id and c["is_dealer"] is True for c in dealers)
    non = api.get("/api/customers", params={"is_dealer": "false"}).json()
    assert all(c["id"] != cust_id for c in non)


def test_contacts_crud_and_single_primary(api, cust_id):
    base = f"/api/customers/{cust_id}/contacts"
    # Create primary contact A
    a = api.post(base, json={"name": f"{_MARK} Alice", "role": "Buyer",
                             "email": "alice@x.co", "is_primary": True}).json()
    assert a["is_primary"] is True
    # Create second contact B as primary → A must be demoted (partial-unique would block two primaries)
    b = api.post(base, json={"name": f"{_MARK} Bob", "is_primary": True}).json()
    listed = api.get(base).json()
    primaries = [c for c in listed if c["is_primary"]]
    assert len(primaries) == 1 and primaries[0]["id"] == b["id"]
    # set-primary back to A (atomic swap)
    r = api.post(f"{base}/{a['id']}/set-primary", json={})
    assert r.status_code == 200
    listed = api.get(base).json()
    assert [c["id"] for c in listed if c["is_primary"]] == [a["id"]]
    # Update B's details
    api.put(f"{base}/{b['id']}", json={"telephone": "011-555"})
    b2 = next(c for c in api.get(base).json() if c["id"] == b["id"])
    assert b2["telephone"] == "011-555"
    # Soft-delete A → it leaves the active list AND frees the primary slot
    assert api.delete(f"{base}/{a['id']}").status_code == 200
    after = api.get(base).json()
    assert all(c["id"] != a["id"] for c in after)          # gone from active list
    assert all(not c["is_primary"] for c in after)         # primary slot freed
    # Now B can be made primary again with no collision
    assert api.post(f"{base}/{b['id']}/set-primary", json={}).status_code == 200


def test_set_primary_rejects_inactive(api, cust_id):
    base = f"/api/customers/{cust_id}/contacts"
    c = api.post(base, json={"name": f"{_MARK} Carol"}).json()
    api.delete(f"{base}/{c['id']}")                         # soft-delete
    r = api.post(f"{base}/{c['id']}/set-primary", json={})
    assert r.status_code == 422
