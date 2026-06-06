"""WO v4.26 §3.5/§3.7 — admin CRUD validation + audit helpers (shared by the 4 admin routers).

Validation (§0.7): sap_code ∈ icb_sap.OITM (read-only check, ADR 0013); formula parses + passes
the safe-evaluator whitelist (no execution); price-override valid_from ≤ valid_to. Audit
(created_by/updated_by) is server-set from the session user. UNIQUE violations → AdminConflictError
(→ 409); validation failures → AdminValidationError (→ 422).
"""
from typing import List

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.sap import OITM
from app.services.rules_engine.evaluator import EvaluationError, validate_expression


class AdminValidationError(ValueError):
    """422 — invalid create/update payload."""


class AdminConflictError(ValueError):
    """409 — UNIQUE constraint violation."""


def validate_sap_code(db: Session, sap_code) -> None:
    if not sap_code:
        return
    if db.execute(select(OITM.ItemCode).where(OITM.ItemCode == sap_code)).first() is None:
        raise AdminValidationError(f"sap_code {sap_code!r} not found in icb_sap.OITM")


def validate_formula(expr) -> None:
    if expr is None:
        return
    try:
        validate_expression(expr)
    except EvaluationError as e:
        raise AdminValidationError(f"invalid formula: {e}") from e


def validate_date_range(valid_from, valid_to) -> None:
    if valid_from and valid_to and valid_from > valid_to:
        raise AdminValidationError("valid_from must be on or before valid_to")


def audit_create(obj, username) -> None:
    for attr in ("created_by", "updated_by"):
        if hasattr(obj, attr):
            setattr(obj, attr, username)


def audit_update(obj, username) -> None:
    if hasattr(obj, "updated_by"):
        obj.updated_by = username


def save(db: Session, obj):
    """Add + commit, mapping a UNIQUE violation to AdminConflictError (409)."""
    db.add(obj)
    _commit(db)
    db.refresh(obj)
    return obj


def commit(db: Session) -> None:
    _commit(db)


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise AdminConflictError("a row with these unique fields already exists") from e


def oitm_search(db: Session, q: str, limit: int = 20) -> List[dict]:
    """Typeahead for the spec-options SAP-code field — only existing OITM codes are selectable."""
    q = (q or "").strip()
    if not q:
        return []
    like = f"%{q}%"
    rows = db.execute(
        select(OITM.ItemCode, OITM.ItemName)
        .where(OITM.ItemCode.ilike(like) | OITM.ItemName.ilike(like))
        .order_by(OITM.ItemCode).limit(limit)
    ).all()
    return [{"sap_code": c, "description": n} for (c, n) in rows]
