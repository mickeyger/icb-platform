"""WO v4.33 scope addition — admin CRUD for icb_mes.fridge_units (require_admin; v4.26 idiom).

The fridge DDM behind the modal dropdown + the {{fridge_*}} template tokens. Flat enough for
the generic AdminCrudTable — standard list/create/patch/delete contract. Deactivate (PATCH
is_active=false) hides a unit from the modal without losing its drawing data.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...database import User, get_db
from ...deps import require_admin
from ...models.mes import FridgeUnit

router = APIRouter(prefix="/api/admin/fridge-units", tags=["admin"])


class FridgeUnitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    manufacturer: str
    model: str
    display_name: str
    mounting_drawing: Optional[str] = None
    cutout_width_mm: Optional[int] = None
    cutout_height_mm: Optional[int] = None
    is_active: bool


class FridgeUnitCreate(BaseModel):
    manufacturer: str
    model: str = ""
    display_name: str
    mounting_drawing: Optional[str] = "A"
    cutout_width_mm: Optional[int] = None
    cutout_height_mm: Optional[int] = None
    is_active: bool = True


class FridgeUnitUpdate(BaseModel):
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    display_name: Optional[str] = None
    mounting_drawing: Optional[str] = None
    cutout_width_mm: Optional[int] = None
    cutout_height_mm: Optional[int] = None
    is_active: Optional[bool] = None


@router.get("", response_model=List[FridgeUnitOut])
def list_units(manufacturer: Optional[str] = Query(None),
               is_active: Optional[bool] = Query(None),
               db: Session = Depends(get_db), user: User = Depends(require_admin)):
    stmt = select(FridgeUnit)
    if manufacturer:
        stmt = stmt.where(FridgeUnit.manufacturer == manufacturer)
    if is_active is not None:
        stmt = stmt.where(FridgeUnit.is_active.is_(is_active))
    return db.execute(stmt.order_by(FridgeUnit.manufacturer, FridgeUnit.model)).scalars().all()


@router.post("", response_model=FridgeUnitOut, status_code=201)
def create_unit(payload: FridgeUnitCreate, db: Session = Depends(get_db),
                user: User = Depends(require_admin)):
    dup = db.execute(select(FridgeUnit).where(
        FridgeUnit.manufacturer == payload.manufacturer,
        FridgeUnit.model == payload.model)).scalars().first()
    if dup is not None:
        raise HTTPException(status_code=409, detail="that manufacturer/model already exists")
    obj = FridgeUnit(**payload.model_dump(), created_by=user.username)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.patch("/{unit_id}", response_model=FridgeUnitOut)
def update_unit(unit_id: int, payload: FridgeUnitUpdate, db: Session = Depends(get_db),
                user: User = Depends(require_admin)):
    obj = db.get(FridgeUnit, unit_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="fridge unit not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    obj.updated_by = user.username
    obj.version = (obj.version or 1) + 1
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{unit_id}", status_code=204)
def delete_unit(unit_id: int, db: Session = Depends(get_db),
                user: User = Depends(require_admin)):
    obj = db.get(FridgeUnit, unit_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="fridge unit not found")
    db.delete(obj)
    db.commit()
