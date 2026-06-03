"""PO-suggestion service (WO v4.15, ADR 0008) — Buying.

raise/defer follow the §0.4 lock: single-id raise, pr_number = f"PR-{seq}" where
seq is the next free numeric suffix across existing PR numbers (first raise -> PR-1).
SAP is mocked — no BAPI call.
"""
from datetime import date, datetime, timezone
from typing import List, Optional

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.mes import MesMaterial, POSuggestion, Supplier
from app.schemas.po_suggestions import (
    BulkRaiseResponse, BulkRaiseSkip, POSuggestionListItem, to_po_item,
)
from app.services.errors import InvalidStateError, NotFoundError


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _next_pr_number(db: Session) -> str:
    """Atomic, race-safe PR number via the PostgreSQL sequence (WO v4.16 §4.6).
    Replaces the v4.15 full-table scan, which bulk-raise would have amplified."""
    seq = db.execute(text("SELECT nextval('icb_mes.pr_number_seq')")).scalar()
    return f"PR-{seq}"


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
    p.pr_number = _next_pr_number(db)
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


def override_supplier(db: Session, *, suggestion_id: int, supplier_name: str,
                      last_price=None, user=None) -> POSuggestionListItem:
    p = db.get(POSuggestion, suggestion_id)
    if p is None:
        raise NotFoundError(f"po suggestion {suggestion_id} not found")
    if p.status == "raised":
        raise InvalidStateError(f"po suggestion {suggestion_id} is already raised; cannot override")
    p.suggested_supplier = supplier_name
    # Best-effort: keep the current last_price when none supplied (no per-supplier
    # price source exists). Recompute the line total either way.
    if last_price is not None:
        p.last_price = last_price
    p.total = (p.qty or 0) * (p.last_price or 0)
    db.commit()
    db.refresh(p)
    return _enrich_one(db, p)


def bulk_raise(db: Session, *, ids, user=None) -> BulkRaiseResponse:
    """Raise PRs for many suggestions: one PR-{seq} per supplier group. Already-raised
    (and unknown) ids are returned in `skipped`, not raised."""
    found = {p.id: p for p in db.execute(
        select(POSuggestion).where(POSuggestion.id.in_(list(ids)))).scalars().all()}
    skipped, raisable = [], []
    for sid in ids:
        p = found.get(sid)
        if p is None:
            skipped.append(BulkRaiseSkip(id=sid, reason="not found"))
        elif p.status == "raised":
            skipped.append(BulkRaiseSkip(id=sid, reason=f"already raised ({p.pr_number})"))
        else:
            raisable.append(p)
    by_supplier: dict = {}
    for p in raisable:
        by_supplier.setdefault(p.suggested_supplier or "", []).append(p)
    now = _now()
    actor_id = getattr(user, "id", None)
    actor = getattr(user, "username", None)
    pr_numbers = []
    for _supplier, group in by_supplier.items():
        pr = _next_pr_number(db)
        pr_numbers.append(pr)
        for p in group:
            p.pr_number = pr
            p.status = "raised"
            p.raised_at = now
            p.raised_by_user_id = actor_id
            p.raised_by_name = actor
    db.commit()
    raised_items = [_enrich_one(db, p) for p in raisable]
    return BulkRaiseResponse(pr_numbers=pr_numbers, raised=raised_items, skipped=skipped)
