"""WO v4.26 §3.5/§3.6 — admin CRUD for icb_mes.bom_spec_options + OITM autocomplete (require_admin).

sap_code (usually NULL — combination-bound, ADR 0014) is validated against icb_sap.OITM when set.
The OITM typeahead (`GET /api/admin/oitm-search`) backs the spec-options SAP-code field.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...database import User, get_db
from ...deps import require_admin
from ...models.mes import BomSpecOption
from ...schemas.admin_bom import BomSpecOptionCreate, BomSpecOptionUpdate
from ...schemas.bom import BomSpecOptionOut
from ...services import admin_bom as adm

router = APIRouter(prefix="/api/admin/bom-spec-options", tags=["admin"])
# OITM typeahead lives at /api/admin/oitm-search (separate prefix).
search_router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("", response_model=List[BomSpecOptionOut])
def list_options(spec_field_type: Optional[str] = Query(None), body_type: Optional[str] = Query(None),
                 active: Optional[bool] = Query(None),
                 db: Session = Depends(get_db), user: User = Depends(require_admin)):
    stmt = select(BomSpecOption)
    if spec_field_type:
        stmt = stmt.where(BomSpecOption.spec_field_type == spec_field_type)
    if body_type:
        stmt = stmt.where(BomSpecOption.body_type == body_type)
    if active is not None:
        stmt = stmt.where(BomSpecOption.active.is_(active))
    return db.execute(
        stmt.order_by(BomSpecOption.spec_field_type, BomSpecOption.priority, BomSpecOption.id)
    ).scalars().all()


@router.post("", response_model=BomSpecOptionOut, status_code=201)
def create_option(payload: BomSpecOptionCreate, db: Session = Depends(get_db),
                  user: User = Depends(require_admin)):
    adm.validate_sap_code(db, payload.sap_code)
    obj = BomSpecOption(**payload.model_dump())
    adm.audit_create(obj, user.username)
    return adm.save(db, obj)


@router.patch("/{option_id}", response_model=BomSpecOptionOut)
def update_option(option_id: int, payload: BomSpecOptionUpdate,
                  db: Session = Depends(get_db), user: User = Depends(require_admin)):
    obj = db.get(BomSpecOption, option_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="bom_spec_option not found")
    data = payload.model_dump(exclude_unset=True)
    if "sap_code" in data:
        adm.validate_sap_code(db, data["sap_code"])
    for k, v in data.items():
        setattr(obj, k, v)
    adm.audit_update(obj, user.username)
    adm.commit(db)
    db.refresh(obj)
    return obj


@router.delete("/{option_id}", status_code=204)
def delete_option(option_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    obj = db.get(BomSpecOption, option_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="bom_spec_option not found")
    db.delete(obj)
    db.commit()


@search_router.get("/oitm-search")
def oitm_search(q: str = Query("", description="ItemCode / ItemName substring"),
                db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return adm.oitm_search(db, q)
