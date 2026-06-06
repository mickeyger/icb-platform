"""WO v4.26 §3.5 — admin CRUD for icb_mes.bom_rules + parse-only formula validation.

All routes require_admin. Formula is validated by the safe evaluator (parse + whitelist, no
execution) before persist. AdminValidationError → 422, AdminConflictError → 409 (global handlers).
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...database import User, get_db
from ...deps import require_admin
from ...models.mes import BomRule
from ...schemas.admin_bom import BomRuleCreate, BomRuleUpdate
from ...schemas.bom import BomRuleOut
from ...services import admin_bom as adm

router = APIRouter(prefix="/api/admin/bom-rules", tags=["admin"])


@router.get("", response_model=List[BomRuleOut])
def list_rules(body_type: Optional[str] = Query(None), section: Optional[str] = Query(None),
               db: Session = Depends(get_db), user: User = Depends(require_admin)):
    stmt = select(BomRule)
    if body_type:
        stmt = stmt.where(BomRule.body_type == body_type)
    if section:
        stmt = stmt.where(BomRule.section == section)
    return db.execute(
        stmt.order_by(BomRule.body_type, BomRule.section, BomRule.priority, BomRule.id)
    ).scalars().all()


@router.post("", response_model=BomRuleOut, status_code=201)
def create_rule(payload: BomRuleCreate, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    adm.validate_formula(payload.formula_expression)
    obj = BomRule(**payload.model_dump())
    adm.audit_create(obj, user.username)
    return adm.save(db, obj)


@router.patch("/{rule_id}", response_model=BomRuleOut)
def update_rule(rule_id: int, payload: BomRuleUpdate,
                db: Session = Depends(get_db), user: User = Depends(require_admin)):
    obj = db.get(BomRule, rule_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="bom_rule not found")
    data = payload.model_dump(exclude_unset=True)
    if "formula_expression" in data:
        adm.validate_formula(data["formula_expression"])
    for k, v in data.items():
        setattr(obj, k, v)
    adm.audit_update(obj, user.username)
    adm.commit(db)
    db.refresh(obj)
    return obj


@router.delete("/{rule_id}", status_code=204)
def delete_rule(rule_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    obj = db.get(BomRule, rule_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="bom_rule not found")
    db.delete(obj)
    db.commit()


class _FormulaCheck(BaseModel):
    formula_expression: str


@router.post("/validate-formula")
def validate_formula(payload: _FormulaCheck, user: User = Depends(require_admin)):
    """Parse-only check for the admin editor's live validation (no execution)."""
    try:
        adm.validate_formula(payload.formula_expression)
        return {"valid": True}
    except adm.AdminValidationError as e:
        return {"valid": False, "error": str(e)}
