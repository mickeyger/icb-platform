"""Materials catalogue + stock service (WO v4.15, ADR 0008).

The catalogue is icb_mes.mes_materials (Q1). `_materials_select` joins the current
stock position and (cross-schema, §4.5) the costing material by sap_code for
reconciliation — `costing_price_per_unit` stays null until the MES demo codes and
the real costing catalogue align.
"""
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Material as CostingMaterial
from app.models.mes import MesMaterial, StockCount, StockPosition
from app.schemas.materials import (
    MaterialDetail, MaterialListItem, to_material_detail, to_material_item,
)
from app.schemas.stock_counts import to_stock_count_item
from app.services.errors import NotFoundError


def description_map(db: Session, sap_codes) -> dict:
    """sap_code -> description from the catalogue (enriches the other resources)."""
    codes = [c for c in set(sap_codes) if c]
    if not codes:
        return {}
    rows = db.execute(
        select(MesMaterial.sap_code, MesMaterial.description).where(MesMaterial.sap_code.in_(codes))
    ).all()
    return {c: d for (c, d) in rows}


def _materials_select():
    # icb_mes.mes_materials ⋈ icb_mes.stock_positions ⋈ (LEFT) icb_costings.materials  (§4.5).
    # CostingMaterial is schema-less (renders bare `materials` -> icb_costings via search_path).
    return (
        select(MesMaterial, StockPosition, CostingMaterial.price_per_unit)
        .join(StockPosition, MesMaterial.sap_code == StockPosition.sap_code, isouter=True)
        .join(CostingMaterial, MesMaterial.sap_code == CostingMaterial.sap_code, isouter=True)
    )


def list_materials(db: Session, *, dept: Optional[str] = None, abc_class: Optional[str] = None,
                   low_stock: bool = False, branch_id: Optional[int] = None) -> List[MaterialListItem]:
    stmt = _materials_select()
    if dept:
        stmt = stmt.where(MesMaterial.dept == dept)
    if abc_class:
        stmt = stmt.where(MesMaterial.abc_class == abc_class)
    stmt = stmt.order_by(MesMaterial.sap_code)
    items = [to_material_item(m, sp, price) for (m, sp, price) in db.execute(stmt).all()]
    # branch_id is accepted but a no-op: stock_positions are not branch-scoped (documented).
    if low_stock:
        # No reorder column in the mockup; "low stock" == no free stock (free <= 0).
        items = [it for it in items
                 if it.stock is not None and it.stock.free is not None and it.stock.free <= 0]
    return items


def get_material(db: Session, sap_code: str) -> MaterialDetail:
    row = db.execute(_materials_select().where(MesMaterial.sap_code == sap_code)).first()
    if row is None:
        raise NotFoundError(f"material {sap_code} not found")
    m, sp, price = row
    counts = db.execute(
        select(StockCount).where(StockCount.sap_code == sap_code)
        .order_by(StockCount.counted_at.desc().nullslast(), StockCount.id.desc()).limit(5)
    ).scalars().all()
    recent = [to_stock_count_item(c, m.description) for c in counts]
    return to_material_detail(m, sp, price, recent)
