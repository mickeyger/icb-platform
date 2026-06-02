"""Materials schemas (WO v4.15, ADR 0008) — Materials Dashboard + Forecast.

Q1 lock: the catalogue lives in icb_mes.materials (self-contained). The response
joins the current stock position and (cross-schema, §4.5) the costing material by
sap_code for reconciliation — `costing_price_per_unit` is null until codes align.
"""
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.stock_counts import StockCountListItem


class StockPosition(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sap_code: Optional[str] = None
    sap_stock: Optional[float] = None
    allocated: Optional[float] = None
    free: Optional[float] = None
    open_po_qty: Optional[float] = None
    open_po_eta: Optional[date] = None
    last_refreshed: Optional[datetime] = None


class MaterialListItem(BaseModel):
    sap_code: str
    description: Optional[str] = None
    supplier: Optional[str] = None
    lead_days: Optional[int] = None
    last_price: Optional[float] = None
    abc_class: Optional[str] = None
    dept: Optional[str] = None
    stock: Optional[StockPosition] = None
    # cross-schema reconciliation (icb_costings.materials ⋈ on sap_code); null when no match
    costing_price_per_unit: Optional[float] = None


class MaterialDetail(MaterialListItem):
    recent_counts: List[StockCountListItem] = Field(default_factory=list)


def to_material_item(m, sp=None, costing_price: Optional[float] = None) -> MaterialListItem:
    return MaterialListItem(
        sap_code=m.sap_code, description=m.description, supplier=m.supplier,
        lead_days=m.lead_days, last_price=m.last_price, abc_class=m.abc_class, dept=m.dept,
        stock=(StockPosition.model_validate(sp) if sp is not None else None),
        costing_price_per_unit=costing_price,
    )


def to_material_detail(m, sp=None, costing_price: Optional[float] = None,
                       recent_counts: Optional[List[StockCountListItem]] = None) -> MaterialDetail:
    base = to_material_item(m, sp, costing_price)
    return MaterialDetail(**base.model_dump(), recent_counts=recent_counts or [])
