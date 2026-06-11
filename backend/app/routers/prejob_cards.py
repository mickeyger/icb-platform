"""WO v4.33 §3.4/§3.5 — /api/prejob-cards: the Pre-Job Card workflow API.

Creation/edit/submit gate on `prejob.create` (sales + admin, seeded in 0017 — §0.3); reads
are require_user (sign-off pages + costings surfaces need them; §3.5 adds the signoff/reject
mutations with their own permission gates). Thin handlers → services.prejob_cards.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import CalculationRecord, Customer, User, get_db
from ..deps import require_permission, require_user
from ..models.mes import PrejobCard, PrejobTemplate
from ..schemas.prejob import (
    PrejobCardCreate, PrejobCardOut, PrejobCardUpdate, RejectRequest, SignOffRequest,
    SubmitForCheck, TemplateOption, UserOption,
)
from ..services import prejob_cards as svc

router = APIRouter(prefix="/api/prejob-cards", tags=["prejob"])


def _out(db: Session, card: PrejobCard) -> PrejobCardOut:
    out = PrejobCardOut.model_validate(card)
    calc = db.get(CalculationRecord, card.calculation_id)
    if calc is not None:
        out.quote_number = calc.quote_number
        if calc.customer_id:
            cust = db.get(Customer, calc.customer_id)
            out.customer_name = cust.name if cust else None
    if card.template_id:
        tpl = db.get(PrejobTemplate, card.template_id)
        out.template_name = tpl.name if tpl else None
    for fld, target in (("sales_rep_user_id", "sales_rep_username"),
                        ("planner_user_id", "planner_username"),
                        ("created_by_user_id", "created_by_username")):
        uid = getattr(card, fld)
        if uid:
            u = db.get(User, uid)
            setattr(out, target, u.username if u else None)
    return out


@router.get("/templates", response_model=List[TemplateOption])
def template_options(body_type: Optional[str] = Query(None),
                     size_hint: Optional[str] = Query(None),
                     db: Session = Depends(get_db), user: User = Depends(require_user)):
    """ACTIVE templates only (the §0.15 structural gate), §0.6 suggestion-ranked."""
    return svc.list_active_templates(db, body_type=body_type, size_hint=size_hint)


@router.get("/user-options", response_model=List[UserOption])
def user_options(kind: str = Query(..., description="sales | planner"),
                 db: Session = Depends(get_db), user: User = Depends(require_user)):
    return svc.list_user_options(db, kind)


@router.get("/by-calculation/{calculation_id}", response_model=Optional[PrejobCardOut])
def get_by_calculation(calculation_id: int, db: Session = Depends(get_db),
                       user: User = Depends(require_user)):
    card = svc.get_for_calculation(db, calculation_id)
    return _out(db, card) if card else None


@router.get("/{card_id}", response_model=PrejobCardOut)
def get_card(card_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    card = db.get(PrejobCard, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="pre-job card not found")
    return _out(db, card)


@router.post("", response_model=PrejobCardOut, status_code=201)
def create_card(payload: PrejobCardCreate, db: Session = Depends(get_db),
                user: User = Depends(require_permission("prejob.create"))):
    return _out(db, svc.create_card(db, payload.calculation_id, payload.template_id, user))


@router.patch("/{card_id}", response_model=PrejobCardOut)
def update_card(card_id: int, payload: PrejobCardUpdate, db: Session = Depends(get_db),
                user: User = Depends(require_permission("prejob.create"))):
    data = payload.model_dump(exclude_unset=True)
    if "sections" in data and data["sections"] is not None:
        data["sections"] = [s if isinstance(s, dict) else s for s in data["sections"]]
    return _out(db, svc.update_card(db, card_id, data, user))


@router.post("/{card_id}/submit-for-check", response_model=PrejobCardOut)
def submit_for_check(card_id: int, payload: SubmitForCheck, db: Session = Depends(get_db),
                     user: User = Depends(require_permission("prejob.create"))):
    return _out(db, svc.submit_for_check(db, card_id, user,
                                         waive_body_gap=payload.waive_body_gap))


# ── §3.5 — check sign-off + reject (per-role gates; admin passes via the wildcard — Q4) ──
@router.post("/{card_id}/signoff/sales", response_model=PrejobCardOut)
def signoff_sales(card_id: int, payload: SignOffRequest, db: Session = Depends(get_db),
                  user: User = Depends(require_permission("prejob.signoff_sales"))):
    return _out(db, svc.sign_off(db, card_id, "sales", payload.attestation, user))


@router.post("/{card_id}/signoff/planner", response_model=PrejobCardOut)
def signoff_planner(card_id: int, payload: SignOffRequest, db: Session = Depends(get_db),
                    user: User = Depends(require_permission("prejob.signoff_planner"))):
    return _out(db, svc.sign_off(db, card_id, "planner", payload.attestation, user))


@router.post("/{card_id}/reject/sales", response_model=PrejobCardOut)
def reject_sales(card_id: int, payload: RejectRequest, db: Session = Depends(get_db),
                 user: User = Depends(require_permission("prejob.signoff_sales"))):
    return _out(db, svc.reject(db, card_id, "sales", payload.reason, user))


@router.post("/{card_id}/reject/planner", response_model=PrejobCardOut)
def reject_planner(card_id: int, payload: RejectRequest, db: Session = Depends(get_db),
                   user: User = Depends(require_permission("prejob.signoff_planner"))):
    return _out(db, svc.reject(db, card_id, "planner", payload.reason, user))
