"""Stock-count service (WO v4.15, ADR 0008) — Stores Reconciliation."""
from datetime import date, datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Branch
from app.models.mes import Discrepancy, StockCount, StockPosition
from app.schemas.discrepancies import DiscrepancyListItem, to_discrepancy_item
from app.schemas.stock_counts import StockCountListItem, to_stock_count_item
from app.services.errors import InvalidStateError, NotFoundError
from app.services.materials import description_map


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _default_branch_id(db: Session):
    """JHB id — stock_counts.branch_id is NOT NULL (0005); fall back here when the
    caller supplies no branch (e.g. no active branch in the session)."""
    b = db.execute(select(Branch).where(Branch.code == "JHB")).scalar_one_or_none()
    return b.id if b is not None else None


def list_counts(db: Session, *, status: Optional[str] = None, branch_id: Optional[int] = None,
                counted_since: Optional[date] = None) -> List[StockCountListItem]:
    stmt = select(StockCount)
    if status:
        stmt = stmt.where(StockCount.status == status)
    if branch_id is not None:
        stmt = stmt.where(StockCount.branch_id == branch_id)
    if counted_since is not None:
        stmt = stmt.where(StockCount.counted_at >= counted_since)
    stmt = stmt.order_by(StockCount.counted_at.desc().nullslast(), StockCount.id.desc())
    rows = db.execute(stmt).scalars().all()
    dmap = description_map(db, [c.sap_code for c in rows])
    return [to_stock_count_item(c, dmap.get(c.sap_code)) for c in rows]


def record_count(db: Session, *, sap_code: str, bin: Optional[str], physical_count: float,
                 branch_id: Optional[int] = None, user=None) -> StockCountListItem:
    """Record a cycle count. status = confirmed if physical == SAP-at-count else discrepancy
    (SAP stock defaults to 0 when no stock position exists, matching the mockup)."""
    sp = db.execute(
        select(StockPosition).where(StockPosition.sap_code == sap_code)
    ).scalar_one_or_none()
    sap_stock = sp.sap_stock if sp is not None else 0
    status = "confirmed" if physical_count == sap_stock else "discrepancy"
    if branch_id is None:                       # branch_id is NOT NULL (WO v4.16 / 0005)
        branch_id = _default_branch_id(db)
    sc = StockCount(
        sap_code=sap_code, bin=bin, sap_stock_at_count=sap_stock, physical_count=physical_count,
        counted_by_user_id=getattr(user, "id", None), counted_by_name=getattr(user, "username", None),
        counted_at=_now(), status=status, branch_id=branch_id,
    )
    db.add(sc)
    db.commit()
    db.refresh(sc)
    return to_stock_count_item(sc, description_map(db, [sap_code]).get(sap_code))


def raise_discrepancy(db: Session, *, stock_count_id: int, raised_to_buyer_user_id: Optional[int] = None,
                      raised_to_buyer_name: Optional[str] = None, notes: Optional[str] = None,
                      user=None) -> DiscrepancyListItem:
    sc = db.get(StockCount, stock_count_id)
    if sc is None:
        raise NotFoundError(f"stock count {stock_count_id} not found")
    if sc.status != "discrepancy":
        raise InvalidStateError(
            f"stock count {stock_count_id} is '{sc.status}'; only 'discrepancy' counts can raise a discrepancy")
    d = Discrepancy(
        stock_count_id=sc.id, raised_at=_now(),
        raised_to_buyer_user_id=raised_to_buyer_user_id, raised_to_buyer_name=raised_to_buyer_name,
        notes=notes,
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    descr = description_map(db, [sc.sap_code]).get(sc.sap_code)
    return to_discrepancy_item(d, sc, descr)
