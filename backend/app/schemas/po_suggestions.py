"""PO-suggestion schemas (WO v4.15, ADR 0008) — Buying / PO Suggestion Queue.

Superset: suggestion columns + `description` (catalogue) + `supplier_contact`
(suppliers) + `jobs_impacted` (Q3 column). raise/defer follow the §0.4 lock.
"""
from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

SuggestionStatus = Literal["pending", "raised", "deferred"]
Urgency = Literal["critical", "order_now", "advisory", "comfortable"]


class POSuggestionListItem(BaseModel):
    id: int
    sap_code: Optional[str] = None
    description: Optional[str] = None        # enriched from the materials catalogue
    qty: Optional[float] = None
    suggested_supplier: Optional[str] = None
    supplier_contact: Optional[str] = None   # enriched from icb_mes.suppliers
    last_price: Optional[float] = None
    total: Optional[float] = None
    need_by: Optional[date] = None
    urgency: Optional[str] = None
    status: Optional[str] = None
    pr_number: Optional[str] = None
    jobs_impacted: List[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    raised_at: Optional[datetime] = None
    raised_by_user_id: Optional[int] = None
    raised_by_name: Optional[str] = None
    deferred_until: Optional[date] = None


class POSuggestionDetail(POSuggestionListItem):
    pass


class DeferRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"deferred_until": "2026-06-30"}})
    deferred_until: date


class OverrideSupplierRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"supplier_name": "Macsteel", "last_price": 4100}})
    supplier_name: str
    last_price: Optional[float] = None


class BulkRaiseRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"ids": [1, 2, 3]}})
    ids: List[int]


class BulkRaiseSkip(BaseModel):
    id: int
    reason: str


class BulkRaiseResponse(BaseModel):
    pr_numbers: List[str] = Field(default_factory=list)
    raised: List[POSuggestionListItem] = Field(default_factory=list)
    skipped: List[BulkRaiseSkip] = Field(default_factory=list)


def to_po_item(p, description: Optional[str] = None,
               supplier_contact: Optional[str] = None) -> POSuggestionListItem:
    """Map a POSuggestion ORM row (+ optional catalogue description + supplier contact)."""
    return POSuggestionListItem(
        id=p.id, sap_code=p.sap_code, description=description, qty=p.qty,
        suggested_supplier=p.suggested_supplier, supplier_contact=supplier_contact,
        last_price=p.last_price, total=p.total, need_by=p.need_by,
        urgency=p.urgency, status=p.status, pr_number=p.pr_number,
        jobs_impacted=(p.jobs_impacted or []),
        created_at=p.created_at, raised_at=p.raised_at,
        raised_by_user_id=p.raised_by_user_id, raised_by_name=p.raised_by_name,
        deferred_until=p.deferred_until,
    )
