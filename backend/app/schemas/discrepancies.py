"""Discrepancy schemas (WO v4.15, ADR 0008) — the buyer's queue.

Superset: discrepancy columns + `sap_code`/`bin` (from the linked stock count)
+ `description` (from the catalogue) + derived `resolved` bool.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class DiscrepancyListItem(BaseModel):
    id: int
    stock_count_id: int
    sap_code: Optional[str] = None         # enriched from the linked stock_count
    bin: Optional[str] = None              # enriched from the linked stock_count
    description: Optional[str] = None      # enriched from the materials catalogue
    raised_at: Optional[datetime] = None
    raised_to_buyer_user_id: Optional[int] = None
    raised_to_buyer_name: Optional[str] = None
    notes: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolution_notes: Optional[str] = None
    resolved: bool = False


class DiscrepancyDetail(DiscrepancyListItem):
    pass


class ResolveRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"resolution_notes": "Mis-issue corrected; SAP adjusted."}}
    )
    resolution_notes: Optional[str] = None


def to_discrepancy_item(d, sc=None, description: Optional[str] = None) -> DiscrepancyListItem:
    """Map a Discrepancy ORM row (+ optional linked StockCount + catalogue description)."""
    return DiscrepancyListItem(
        id=d.id, stock_count_id=d.stock_count_id,
        sap_code=(sc.sap_code if sc is not None else None),
        bin=(sc.bin if sc is not None else None),
        description=description,
        raised_at=d.raised_at, raised_to_buyer_user_id=d.raised_to_buyer_user_id,
        raised_to_buyer_name=d.raised_to_buyer_name, notes=d.notes,
        resolved_at=d.resolved_at, resolution_notes=d.resolution_notes,
        resolved=d.resolved_at is not None,
    )
