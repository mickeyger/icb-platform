"""WO v4.26 §3.5 — admin CRUD for icb_mes.bom_rule_lookups (require_admin)."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...database import User, get_db
from ...deps import require_admin
from ...models.mes import BomRuleLookup
from ...schemas.admin_bom import BomRuleLookupCreate, BomRuleLookupUpdate
from ...schemas.bom import BomRuleLookupOut
from ...services import admin_bom as adm

router = APIRouter(prefix="/api/admin/bom-rule-lookups", tags=["admin"])


@router.get("", response_model=List[BomRuleLookupOut])
def list_lookups(body_type: Optional[str] = Query(None), section: Optional[str] = Query(None),
                 lookup_type: Optional[str] = Query(None),
                 db: Session = Depends(get_db), user: User = Depends(require_admin)):
    stmt = select(BomRuleLookup)
    if body_type:
        stmt = stmt.where(BomRuleLookup.body_type == body_type)
    if section:
        stmt = stmt.where(BomRuleLookup.section == section)
    if lookup_type:
        stmt = stmt.where(BomRuleLookup.lookup_type == lookup_type)
    return db.execute(
        stmt.order_by(BomRuleLookup.body_type, BomRuleLookup.section,
                      BomRuleLookup.lookup_type, BomRuleLookup.lookup_key)
    ).scalars().all()


@router.post("", response_model=BomRuleLookupOut, status_code=201)
def create_lookup(payload: BomRuleLookupCreate, db: Session = Depends(get_db),
                  user: User = Depends(require_admin)):
    obj = BomRuleLookup(**payload.model_dump())
    adm.audit_create(obj, user.username)
    return adm.save(db, obj)


@router.patch("/{lookup_id}", response_model=BomRuleLookupOut)
def update_lookup(lookup_id: int, payload: BomRuleLookupUpdate,
                  db: Session = Depends(get_db), user: User = Depends(require_admin)):
    obj = db.get(BomRuleLookup, lookup_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="bom_rule_lookup not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    adm.audit_update(obj, user.username)
    adm.commit(db)
    db.refresh(obj)
    return obj


@router.delete("/{lookup_id}", status_code=204)
def delete_lookup(lookup_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    obj = db.get(BomRuleLookup, lookup_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="bom_rule_lookup not found")
    db.delete(obj)
    db.commit()
