"""WO v4.26 §3.5 — admin CRUD for icb_mes.material_price_overrides (require_admin).

Validation (§0.7): sap_code ∈ icb_sap.OITM; valid_from ≤ valid_to. Multiple overrides per sap_code
(different validity windows) are intentional — no UNIQUE here.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...database import User, get_db
from ...deps import require_admin
from ...models.mes import MaterialPriceOverride
from ...schemas.admin_bom import MaterialPriceOverrideCreate, MaterialPriceOverrideUpdate
from ...schemas.bom import MaterialPriceOverrideOut
from ...services import admin_bom as adm

router = APIRouter(prefix="/api/admin/material-price-overrides", tags=["admin"])


@router.get("", response_model=List[MaterialPriceOverrideOut])
def list_overrides(sap_code: Optional[str] = Query(None),
                   db: Session = Depends(get_db), user: User = Depends(require_admin)):
    stmt = select(MaterialPriceOverride)
    if sap_code:
        stmt = stmt.where(MaterialPriceOverride.sap_code == sap_code)
    return db.execute(
        stmt.order_by(MaterialPriceOverride.sap_code, MaterialPriceOverride.valid_from.desc())
    ).scalars().all()


@router.post("", response_model=MaterialPriceOverrideOut, status_code=201)
def create_override(payload: MaterialPriceOverrideCreate,
                    db: Session = Depends(get_db), user: User = Depends(require_admin)):
    adm.validate_sap_code(db, payload.sap_code)
    adm.validate_date_range(payload.valid_from, payload.valid_to)
    obj = MaterialPriceOverride(**payload.model_dump(exclude_none=True))  # let valid_from default apply
    adm.audit_create(obj, user.username)
    return adm.save(db, obj)


@router.patch("/{override_id}", response_model=MaterialPriceOverrideOut)
def update_override(override_id: int, payload: MaterialPriceOverrideUpdate,
                    db: Session = Depends(get_db), user: User = Depends(require_admin)):
    obj = db.get(MaterialPriceOverride, override_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="material_price_override not found")
    data = payload.model_dump(exclude_unset=True)
    if "sap_code" in data:
        adm.validate_sap_code(db, data["sap_code"])
    adm.validate_date_range(data.get("valid_from", obj.valid_from), data.get("valid_to", obj.valid_to))
    for k, v in data.items():
        setattr(obj, k, v)
    adm.audit_update(obj, user.username)
    adm.commit(db)
    db.refresh(obj)
    return obj


@router.delete("/{override_id}", status_code=204)
def delete_override(override_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    obj = db.get(MaterialPriceOverride, override_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="material_price_override not found")
    db.delete(obj)
    db.commit()
