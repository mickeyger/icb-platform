"""Supplier service (WO v4.15, ADR 0008) — read-only master list."""
from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.mes import Supplier
from app.schemas.suppliers import SupplierListItem


def list_suppliers(db: Session) -> List[SupplierListItem]:
    rows = db.execute(select(Supplier).order_by(Supplier.name)).scalars().all()
    return [SupplierListItem.model_validate(s) for s in rows]
