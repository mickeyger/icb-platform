from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..database import get_db, Customer
from ..deps import get_current_user, require_admin

router = APIRouter()


@router.get("/api/customers")
async def get_customers(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401)
    custs = db.query(Customer).order_by(Customer.name).all()
    return [{"id": c.id, "bp_code": c.bp_code or "", "name": c.name,
             "email": c.email or "", "telephone": c.telephone or "",
             "is_active": c.is_active} for c in custs]


@router.post("/api/customers")
async def create_customer(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
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
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return {"id": c.id, "name": c.name, "bp_code": c.bp_code or "",
            "email": c.email or "", "telephone": c.telephone or "", "is_active": c.is_active}


@router.put("/api/customers/{cust_id}")
async def update_customer(cust_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
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
    db.commit()
    return {"id": c.id, "name": c.name, "bp_code": c.bp_code or "",
            "email": c.email or "", "telephone": c.telephone or "", "is_active": c.is_active}


@router.delete("/api/customers/{cust_id}")
async def delete_customer(cust_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    c = db.query(Customer).filter_by(id=cust_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")
    db.delete(c)
    db.commit()
    return {"ok": True}
