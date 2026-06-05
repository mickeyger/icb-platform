"""Materials schemas (WO v4.15, ADR 0008) — Materials Dashboard + Forecast.

Q1 lock: the catalogue lives in icb_mes.mes_materials (self-contained). The response
joins the current SAP stock (icb_sap.OITW — the SAP-mock landing zone, WO v4.23/ADR 0013)
and (cross-schema, §4.5) the costing material by sap_code for reconciliation —
`costing_price_per_unit` is null until codes align. The StockPosition shape is unchanged.
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


def _f(v) -> Optional[float]:
    return float(v) if v is not None else None


def stock_from_oitw(w) -> StockPosition:
    """Map an icb_sap.OITW row onto the (unchanged) StockPosition response shape.

    WO v4.23 / ADR 0013: stock now comes from the SAP-mock landing zone, not from
    icb_mes.stock_positions. Field mapping — OnHand->sap_stock, IsCommited->allocated,
    Available (GENERATED = OnHand-IsCommited+OnOrder)->free, OnOrder->open_po_qty. OITW
    carries no PO ETA so open_po_eta stays null; last_refreshed = the OITW load time.
    """
    return StockPosition(
        sap_code=w.ItemCode, sap_stock=_f(w.OnHand), allocated=_f(w.IsCommited),
        free=_f(w.Available), open_po_qty=_f(w.OnOrder),
        open_po_eta=None, last_refreshed=w.updated_at,
    )


def to_material_item(m, sp=None, costing_price: Optional[float] = None) -> MaterialListItem:
    # `sp` is an icb_sap.OITW row (WO v4.23) or None when the item has no SAP stock record.
    return MaterialListItem(
        sap_code=m.sap_code, description=m.description, supplier=m.supplier,
        lead_days=m.lead_days, last_price=m.last_price, abc_class=m.abc_class, dept=m.dept,
        stock=(stock_from_oitw(sp) if sp is not None else None),
        costing_price_per_unit=costing_price,
    )


def to_material_detail(m, sp=None, costing_price: Optional[float] = None,
                       recent_counts: Optional[List[StockCountListItem]] = None) -> MaterialDetail:
    base = to_material_item(m, sp, costing_price)
    return MaterialDetail(**base.model_dump(), recent_counts=recent_counts or [])
