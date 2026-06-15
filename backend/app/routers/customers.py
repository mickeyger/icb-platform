from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..database import Customer, CustomerContact, User, get_db
from ..deps import require_admin, require_user

router = APIRouter()


def _cust_dict(c: Customer) -> dict:
    return {"id": c.id, "bp_code": c.bp_code or "", "name": c.name,
            "email": c.email or "", "telephone": c.telephone or "",
            "is_active": c.is_active, "is_dealer": bool(c.is_dealer)}


def _contact_dict(c: CustomerContact) -> dict:
    return {"id": c.id, "customer_id": c.customer_id, "name": c.name or "",
            "role": c.role or "", "email": c.email or "", "telephone": c.telephone or "",
            "is_primary": bool(c.is_primary), "is_active": bool(c.is_active)}


@router.get("/api/customers")
async def get_customers(db: Session = Depends(get_db), user: User = Depends(require_user),
                        q: str | None = None, is_dealer: bool | None = None,
                        limit: int | None = None):
    """List customers. WO v4.34.1 §3.2 — `is_dealer` exposed + filterable (drives the Planning-ack
    dealer typeahead, §3.3) and a `q` name/bp_code search (drives the Customers admin list, §3.5)."""
    query = db.query(Customer)
    if is_dealer is not None:
        query = query.filter(Customer.is_dealer.is_(bool(is_dealer)))
    if q:
        like = f"%{q.strip()}%"
        query = query.filter((Customer.name.ilike(like)) | (Customer.bp_code.ilike(like)))
    query = query.order_by(Customer.name)
    if limit is not None and limit > 0:
        query = query.limit(limit)
    return [_cust_dict(c) for c in query.all()]


@router.post("/api/customers")
async def create_customer(request: Request, db: Session = Depends(get_db),
                          _admin: User = Depends(require_admin)):
    body = await request.json()
    name = str(body.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="Customer name is required")
    c = Customer(
        bp_code=str(body.get("bp_code", "")).strip() or None,
        name=name,
        email=str(body.get("email", "")).strip() or None,
        telephone=str(body.get("telephone", "")).strip() or None,
        is_active=bool(body.get("is_active", True)),
        is_dealer=bool(body.get("is_dealer", False)),
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return _cust_dict(c)


@router.put("/api/customers/{cust_id}")
async def update_customer(cust_id: int, request: Request, db: Session = Depends(get_db),
                          _admin: User = Depends(require_admin)):
    body = await request.json()
    c = db.query(Customer).filter_by(id=cust_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")
    if "name" in body:
        c.name = str(body["name"]).strip()
    if "bp_code" in body:
        c.bp_code = str(body["bp_code"]).strip() or None
    if "email" in body:
        c.email = str(body["email"]).strip() or None
    if "telephone" in body:
        c.telephone = str(body["telephone"]).strip() or None
    if "is_active" in body:
        c.is_active = bool(body["is_active"])
    if "is_dealer" in body:
        c.is_dealer = bool(body["is_dealer"])
    db.commit()
    return _cust_dict(c)


@router.delete("/api/customers/{cust_id}")
async def delete_customer(cust_id: int, db: Session = Depends(get_db),
                          _admin: User = Depends(require_admin)):
    c = db.query(Customer).filter_by(id=cust_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")
    db.delete(c)
    db.commit()
    return {"ok": True}


# ── Contacts (WO v4.34.1 §3.2 / §0.6) ────────────────────────────────────────
# Multiple contacts per customer (Nadie's reality). One is_primary per customer (DB-enforced by a
# partial unique index, migration 0022). Soft-delete via is_active so audit history survives.

def _require_customer(db: Session, cust_id: int) -> Customer:
    c = db.query(Customer).filter_by(id=cust_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")
    return c


def _clear_primary(db: Session, cust_id: int, except_id: int | None = None) -> None:
    """Demote every other primary for this customer, then FLUSH so the demotion lands in the DB
    before the new primary is inserted/updated. Without the flush, SQLAlchemy batches the demote
    and the promote (INSERTs even precede UPDATEs), so the new is_primary=true row would collide
    with the still-true old row on the partial-unique index uq_customer_contacts_one_primary."""
    q = db.query(CustomerContact).filter(CustomerContact.customer_id == cust_id,
                                          CustomerContact.is_primary.is_(True))
    if except_id is not None:
        q = q.filter(CustomerContact.id != except_id)
    demoted = False
    for other in q.all():
        other.is_primary = False
        demoted = True
    if demoted:
        db.flush()


@router.get("/api/customers/{cust_id}/contacts")
async def list_contacts(cust_id: int, db: Session = Depends(get_db),
                        user: User = Depends(require_user)):
    _require_customer(db, cust_id)
    rows = (db.query(CustomerContact)
            .filter(CustomerContact.customer_id == cust_id, CustomerContact.is_active.is_(True))
            .order_by(CustomerContact.is_primary.desc(), CustomerContact.name.nullslast(),
                      CustomerContact.id)
            .all())
    return [_contact_dict(c) for c in rows]


@router.post("/api/customers/{cust_id}/contacts")
async def create_contact(cust_id: int, request: Request, db: Session = Depends(get_db),
                         actor: User = Depends(require_admin)):
    _require_customer(db, cust_id)
    body = await request.json()
    is_primary = bool(body.get("is_primary", False))
    if is_primary:
        _clear_primary(db, cust_id)
    c = CustomerContact(
        customer_id=cust_id,
        name=str(body.get("name", "")).strip() or None,
        role=str(body.get("role", "")).strip() or None,
        email=str(body.get("email", "")).strip() or None,
        telephone=str(body.get("telephone", "")).strip() or None,
        is_primary=is_primary,
        is_active=True,
        created_by=actor.username,
        updated_by=actor.username,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return _contact_dict(c)


@router.put("/api/customers/{cust_id}/contacts/{contact_id}")
async def update_contact(cust_id: int, contact_id: int, request: Request,
                         db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    body = await request.json()
    c = (db.query(CustomerContact)
         .filter_by(id=contact_id, customer_id=cust_id).first())
    if not c:
        raise HTTPException(status_code=404, detail="Contact not found")
    if "name" in body:
        c.name = str(body["name"]).strip() or None
    if "role" in body:
        c.role = str(body["role"]).strip() or None
    if "email" in body:
        c.email = str(body["email"]).strip() or None
    if "telephone" in body:
        c.telephone = str(body["telephone"]).strip() or None
    if body.get("is_primary") is True:
        _clear_primary(db, cust_id, except_id=c.id)
        c.is_primary = True
    elif body.get("is_primary") is False:
        c.is_primary = False
    c.updated_by = actor.username
    db.commit()
    return _contact_dict(c)


@router.post("/api/customers/{cust_id}/contacts/{contact_id}/set-primary")
async def set_primary_contact(cust_id: int, contact_id: int,
                              db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    c = (db.query(CustomerContact)
         .filter_by(id=contact_id, customer_id=cust_id).first())
    if not c:
        raise HTTPException(status_code=404, detail="Contact not found")
    if not c.is_active:
        raise HTTPException(status_code=422, detail="Cannot make an inactive contact primary")
    _clear_primary(db, cust_id, except_id=c.id)
    c.is_primary = True
    c.updated_by = actor.username
    db.commit()
    return _contact_dict(c)


@router.delete("/api/customers/{cust_id}/contacts/{contact_id}")
async def delete_contact(cust_id: int, contact_id: int,
                         db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    """Soft-delete: is_active=false (and drop is_primary so the partial-unique slot frees up)."""
    c = (db.query(CustomerContact)
         .filter_by(id=contact_id, customer_id=cust_id).first())
    if not c:
        raise HTTPException(status_code=404, detail="Contact not found")
    c.is_active = False
    c.is_primary = False
    c.updated_by = actor.username
    db.commit()
    return {"ok": True}
