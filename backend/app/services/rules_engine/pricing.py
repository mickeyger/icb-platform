"""WO v4.25 §0.5 / §3.3 — hybrid pricing: Nadie override → live SAP.

Precedence: an active `icb_mes.material_price_overrides` row (valid_from ≤ today AND
(valid_to IS NULL OR valid_to ≥ today)) wins; else fall back to
`icb_sap.OITM.U_LastPurchasePrice` (read-only, ADR 0013). Returns (price, source) so the
caller can record provenance. The v4.24 spike's price-divergence finding motivates the
override table.
"""
from datetime import date
from decimal import Decimal
from typing import Optional, Tuple

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.mes import MaterialPriceOverride
from app.models.sap import OITM


def get_price(db: Session, sap_code: str) -> Tuple[Optional[Decimal], Optional[str]]:
    """Return (unit_price, source) where source is 'override' | 'sap' | None."""
    if not sap_code:
        return None, None
    today = date.today()
    ov = db.execute(
        select(MaterialPriceOverride.override_price)
        .where(
            MaterialPriceOverride.sap_code == sap_code,
            MaterialPriceOverride.valid_from <= today,
            or_(MaterialPriceOverride.valid_to.is_(None), MaterialPriceOverride.valid_to >= today),
        )
        .order_by(MaterialPriceOverride.valid_from.desc(), MaterialPriceOverride.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if ov is not None:
        return ov, "override"
    sap = db.execute(
        select(OITM.U_LastPurchasePrice).where(OITM.ItemCode == sap_code)
    ).scalar_one_or_none()
    if sap is not None:
        return sap, "sap"
    return None, None
