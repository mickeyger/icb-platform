"""Stock-count schemas (WO v4.15, ADR 0008) — Stores Reconciliation.

Superset responses: canonical columns + `description` (enriched from the
materials catalogue) + derived `diff` (physical − SAP at count).
"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

CountStatus = Literal["pending", "confirmed", "discrepancy"]


class StockCountListItem(BaseModel):
    id: int
    sap_code: Optional[str] = None
    description: Optional[str] = None          # enriched from icb_mes.materials
    bin: Optional[str] = None
    sap_stock_at_count: Optional[float] = None
    physical_count: Optional[float] = None
    diff: Optional[float] = None               # physical − sap_stock_at_count; None until counted
    counted_by_user_id: Optional[int] = None
    counted_by_name: Optional[str] = None
    counted_at: Optional[datetime] = None
    status: Optional[str] = None
    branch_id: Optional[int] = None
    created_at: Optional[datetime] = None


class StockCountDetail(StockCountListItem):
    pass


class RecordCountRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {"sap_code": "GRP-MPS-A-0077", "bin": "A-12-3", "physical_count": 5}
        }
    )
    sap_code: str
    bin: Optional[str] = None
    physical_count: float = Field(..., description="Counted physical quantity")
    branch_id: Optional[int] = None


class RaiseDiscrepancyRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {"raised_to_buyer_name": "M. Nkomo", "notes": "Short 3 units vs SAP"}
        }
    )
    raised_to_buyer_user_id: Optional[int] = None
    raised_to_buyer_name: Optional[str] = None
    notes: Optional[str] = None


def to_stock_count_item(sc, description: Optional[str] = None) -> StockCountListItem:
    """Map a StockCount ORM row (+ optional catalogue description) to the response."""
    diff = None
    if sc.physical_count is not None and sc.sap_stock_at_count is not None:
        diff = sc.physical_count - sc.sap_stock_at_count
    return StockCountListItem(
        id=sc.id, sap_code=sc.sap_code, description=description, bin=sc.bin,
        sap_stock_at_count=sc.sap_stock_at_count, physical_count=sc.physical_count, diff=diff,
        counted_by_user_id=sc.counted_by_user_id, counted_by_name=sc.counted_by_name,
        counted_at=sc.counted_at, status=sc.status, branch_id=sc.branch_id,
        created_at=sc.created_at,
    )
