"""WO v4.36c — admin CRUD for icb_mes.defect_categories (require_admin; fridge_units idiom).

Kenny's QC inspection taxonomy, admin-editable so categories refine during parallel-run with no
redeploy (§0.5). DELETE SOFT-deactivates (is_active=false) — NEVER hard-delete (§3.0 §3d / §0.6): the
immutable qc_inspections rows reference category_id (FK ondelete=RESTRICT), and the audit must survive.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...database import User, get_db
from ...deps import require_admin
from ...models.mes import DefectCategory

router = APIRouter(prefix="/api/admin/defect-categories", tags=["admin"])


class DefectCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    sort_order: int
    is_active: bool


class DefectCategoryCreate(BaseModel):
    name: str
    sort_order: int = 100
    is_active: bool = True


class DefectCategoryUpdate(BaseModel):
    name: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


@router.get("", response_model=List[DefectCategoryOut])
def list_categories(is_active: Optional[bool] = Query(None),
                    db: Session = Depends(get_db), user: User = Depends(require_admin)):
    stmt = select(DefectCategory)
    if is_active is not None:
        stmt = stmt.where(DefectCategory.is_active.is_(is_active))
    return db.execute(stmt.order_by(DefectCategory.sort_order, DefectCategory.id)).scalars().all()


@router.post("", response_model=DefectCategoryOut, status_code=201)
def create_category(payload: DefectCategoryCreate, db: Session = Depends(get_db),
                    user: User = Depends(require_admin)):
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    dup = db.execute(select(DefectCategory).where(DefectCategory.name == name)).scalars().first()
    if dup is not None:
        raise HTTPException(status_code=409, detail="a category with that name already exists")
    obj = DefectCategory(name=name, sort_order=payload.sort_order, is_active=payload.is_active,
                         created_by=user.username)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.patch("/{category_id}", response_model=DefectCategoryOut)
def update_category(category_id: int, payload: DefectCategoryUpdate, db: Session = Depends(get_db),
                    user: User = Depends(require_admin)):
    obj = db.get(DefectCategory, category_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="defect category not found")
    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        nm = (data["name"] or "").strip()
        if not nm:
            raise HTTPException(status_code=422, detail="name cannot be blank")
        clash = db.execute(select(DefectCategory).where(
            DefectCategory.name == nm, DefectCategory.id != category_id)).scalars().first()
        if clash is not None:
            raise HTTPException(status_code=409, detail="a category with that name already exists")
        data["name"] = nm
    for k, v in data.items():
        setattr(obj, k, v)
    obj.updated_by = user.username
    obj.version = (obj.version or 1) + 1
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{category_id}", status_code=204)
def deactivate_category(category_id: int, db: Session = Depends(get_db),
                        user: User = Depends(require_admin)):
    """SOFT-deactivate (is_active=false) — never hard-delete: qc_inspections FK-reference the row and
    the audit must survive (§3.0 §3d). The row stays; it's just hidden from the active taxonomy."""
    obj = db.get(DefectCategory, category_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="defect category not found")
    obj.is_active = False
    obj.updated_by = user.username
    obj.version = (obj.version or 1) + 1
    db.commit()
