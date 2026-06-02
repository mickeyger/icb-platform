"""Discrepancy service (WO v4.15, ADR 0008) — the buyer's queue."""
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.mes import Discrepancy, StockCount
from app.schemas.discrepancies import DiscrepancyListItem, to_discrepancy_item
from app.services.errors import InvalidStateError, NotFoundError
from app.services.materials import description_map


def _now() -> datetime:
    return datetime.now(timezone.utc)


def list_discrepancies(db: Session, *, resolved: Optional[bool] = None) -> List[DiscrepancyListItem]:
    stmt = (select(Discrepancy, StockCount)
            .join(StockCount, Discrepancy.stock_count_id == StockCount.id))
    if resolved is True:
        stmt = stmt.where(Discrepancy.resolved_at.isnot(None))
    elif resolved is False:
        stmt = stmt.where(Discrepancy.resolved_at.is_(None))
    stmt = stmt.order_by(Discrepancy.raised_at.desc().nullslast(), Discrepancy.id.desc())
    rows = db.execute(stmt).all()
    dmap = description_map(db, [sc.sap_code for (_, sc) in rows])
    return [to_discrepancy_item(d, sc, dmap.get(sc.sap_code)) for (d, sc) in rows]


def resolve_discrepancy(db: Session, *, discrepancy_id: int, resolution_notes: Optional[str] = None,
                        user=None) -> DiscrepancyListItem:
    d = db.get(Discrepancy, discrepancy_id)
    if d is None:
        raise NotFoundError(f"discrepancy {discrepancy_id} not found")
    if d.resolved_at is not None:
        raise InvalidStateError(f"discrepancy {discrepancy_id} is already resolved")
    d.resolved_at = _now()
    d.resolution_notes = resolution_notes
    db.commit()
    db.refresh(d)
    sc = db.get(StockCount, d.stock_count_id)
    descr = description_map(db, [sc.sap_code]).get(sc.sap_code) if sc is not None else None
    return to_discrepancy_item(d, sc, descr)
