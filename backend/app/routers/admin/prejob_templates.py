"""WO v4.33 §3.3 — admin CRUD for icb_mes.prejob_templates (require_admin; v4.26 idiom).

The §0.15 review-and-approve surface: the importer lands drafts (is_active=False); BA/Nadie
review each rendered template here, fix anything, then Approve (is_active=True — only active
templates appear in the §3.4 modal's selector). Deactivate is the symmetric undo. Deleting is
draft-only (an approved template is library content; prejob_cards also FK it RESTRICT).
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...database import User, get_db
from ...deps import require_admin
from ...models.mes import PrejobTemplate
from ...schemas.prejob import (
    PrejobTemplateListItem, PrejobTemplateOut, PrejobTemplateUpdate,
)

router = APIRouter(prefix="/api/admin/prejob-templates", tags=["admin"])


def _list_item(t: PrejobTemplate) -> PrejobTemplateListItem:
    out = PrejobTemplateListItem.model_validate(t)
    out.section_names = [s.get("name", "?") for s in (t.sections or [])]
    out.item_count = sum(len(s.get("items", [])) for s in (t.sections or []))
    return out


def _out(t: PrejobTemplate) -> PrejobTemplateOut:
    out = PrejobTemplateOut.model_validate(t)
    out.section_names = [s.get("name", "?") for s in (t.sections or [])]
    out.item_count = sum(len(s.get("items", [])) for s in (t.sections or []))
    return out


@router.get("", response_model=List[PrejobTemplateListItem])
def list_templates(body_type: Optional[str] = Query(None),
                   product_line: Optional[str] = Query(None),
                   is_active: Optional[bool] = Query(None),
                   db: Session = Depends(get_db), user: User = Depends(require_admin)):
    stmt = select(PrejobTemplate)
    if body_type:
        stmt = stmt.where(PrejobTemplate.body_type == body_type)
    if product_line:
        stmt = stmt.where(PrejobTemplate.product_line == product_line)
    if is_active is not None:
        stmt = stmt.where(PrejobTemplate.is_active.is_(is_active))
    rows = db.execute(
        stmt.order_by(PrejobTemplate.body_type, PrejobTemplate.size_category,
                      PrejobTemplate.name)
    ).scalars().all()
    return [_list_item(t) for t in rows]


@router.get("/{template_id}", response_model=PrejobTemplateOut)
def get_template(template_id: int, db: Session = Depends(get_db),
                 user: User = Depends(require_admin)):
    t = db.get(PrejobTemplate, template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="prejob template not found")
    return _out(t)


@router.patch("/{template_id}", response_model=PrejobTemplateOut)
def update_template(template_id: int, payload: PrejobTemplateUpdate,
                    db: Session = Depends(get_db), user: User = Depends(require_admin)):
    t = db.get(PrejobTemplate, template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="prejob template not found")
    data = payload.model_dump(exclude_unset=True)
    if "sections" in data:
        # pydantic validated the §0.5 shape; persist plain JSON + bump the version.
        t.version = (t.version or 1) + 1
    for k, v in data.items():
        setattr(t, k, v)
    t.updated_by = user.username
    db.commit()
    db.refresh(t)
    return _out(t)


@router.post("/{template_id}/approve", response_model=PrejobTemplateOut)
def approve_template(template_id: int, db: Session = Depends(get_db),
                     user: User = Depends(require_admin)):
    """§0.15 — flips the reviewed draft live (appears in the §3.4 modal selector)."""
    t = db.get(PrejobTemplate, template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="prejob template not found")
    if not (t.sections or []):
        raise HTTPException(status_code=422, detail="cannot approve a template with no sections")
    t.is_active = True
    t.updated_by = user.username
    db.commit()
    db.refresh(t)
    return _out(t)


@router.post("/{template_id}/deactivate", response_model=PrejobTemplateOut)
def deactivate_template(template_id: int, db: Session = Depends(get_db),
                        user: User = Depends(require_admin)):
    t = db.get(PrejobTemplate, template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="prejob template not found")
    t.is_active = False
    t.updated_by = user.username
    db.commit()
    db.refresh(t)
    return _out(t)


@router.delete("/{template_id}", status_code=204)
def delete_template(template_id: int, db: Session = Depends(get_db),
                    user: User = Depends(require_admin)):
    t = db.get(PrejobTemplate, template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="prejob template not found")
    if t.is_active:
        raise HTTPException(status_code=409,
                            detail="active template — deactivate before deleting")
    db.delete(t)
    db.commit()
