"""PO-suggestion service (WO v4.15, ADR 0008) — Buying.

raise/defer follow the §0.4 lock: single-id raise, pr_number = f"PR-{seq}" where
seq is the next free numeric suffix across existing PR numbers (first raise -> PR-1).
SAP is mocked — no BAPI call.
"""
from datetime import date, datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.mes import MesMaterial, POSuggestion, Supplier
from app.schemas.po_suggestions import POSuggestionListItem, to_po_item
from app.services.errors import InvalidStateError, NotFoundError


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _next_pr_seq(db: Session) -> int:
    rows = db.execute(
        select(POSuggestion.pr_number).where(POSuggestion.pr_number.isnot(None))
    ).scalars().all()
    mx = 0
    for pr in rows:
        if pr and pr.startswith("PR-") and pr[3:].isdigit():
            mx = max(mx, int(pr[3:]))
    return mx + 1


def _enrich_one(db: Session, p: POSuggestion) -> POSuggestionListItem:
    descr = db.execute(
        select(MesMaterial.description).where(MesMaterial.sap_code == p.sap_code)
    ).scalar_one_or_none()
    contact = db.execute(
        select(Supplier.contact_person).where(Supplier.name == p.suggested_supplier)
    ).scalar_one_or_none()
    return to_po_item(p, descr, contact)


def list_suggestions(db: Session, *, status: Optional[str] = None,
                     urgency: Optional[str] = None) -> List[POSuggestionListItem]:
    stmt = (select(POSuggestion, MesMaterial.description, Supplier.contact_person)
            .join(MesMaterial, POSuggestion.sap_code == MesMaterial.sap_code, isouter=True)
            .join(Supplier, POSuggestion.suggested_supplier == Supplier.name, isouter=True))
    if status:
        stmt = stmt.where(POSuggestion.status == status)
    if urgency:
        stmt = stmt.where(POSuggestion.urgency == urgency)
    stmt = stmt.order_by(POSuggestion.id)
    return [to_po_item(p, descr, contact) for (p, descr, contact) in db.execute(stmt).all()]


def raise_pr(db: Session, *, suggestion_id: int, user=None) -> POSuggestionListItem:
    p = db.get(POSuggestion, suggestion_id)
    if p is None:
        raise NotFoundError(f"po suggestion {suggestion_id} not found")
    if p.status == "raised":
        raise InvalidStateError(f"po suggestion {suggestion_id} already raised ({p.pr_number})")
    p.pr_number = f"PR-{_next_pr_seq(db)}"
    p.status = "raised"
    p.raised_at = _now()
    p.raised_by_user_id = getattr(user, "id", None)
    p.raised_by_name = getattr(user, "username", None)
    db.commit()
    db.refresh(p)
    return _enrich_one(db, p)


def defer_suggestion(db: Session, *, suggestion_id: int, deferred_until: date,
                     user=None) -> POSuggestionListItem:
    p = db.get(POSuggestion, suggestion_id)
    if p is None:
        raise NotFoundError(f"po suggestion {suggestion_id} not found")
    if p.status == "raised":
        raise InvalidStateError(f"po suggestion {suggestion_id} is already raised; cannot defer")
    p.status = "deferred"
    p.deferred_until = deferred_until
    db.commit()
    db.refresh(p)
    return _enrich_one(db, p)
