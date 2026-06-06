"""WO v4.24 spike — unit-price lookup from the SAP-mock item master.

Reads icb_sap.OITM.U_LastPurchasePrice (§0.3, for replay fidelity vs the workbook's
Table15 "Item Price"). READ-ONLY (ADR 0013). Returns None when a code is absent — the
caller flags it (unpriced_codes) rather than crashing.

NOTE (§7.4 pricing assessment): OITM.U_LastPurchasePrice was loaded (v4.23) from the
Inventory workbook, which is a *different* snapshot than the Costing Module's internal
Table15. The replay test compares the two head-to-head.
"""
from decimal import Decimal
from typing import Optional

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session


def unit_price(db: Session, sap_code: str) -> Optional[Decimal]:
    """icb_sap.OITM.U_LastPurchasePrice for sap_code, or None if not found."""
    if not sap_code:
        return None
    row = db.execute(
        sa_text('SELECT "U_LastPurchasePrice" FROM icb_sap."OITM" WHERE "ItemCode" = :c'),
        {"c": sap_code},
    ).first()
    return row[0] if row and row[0] is not None else None


def unit_price_map(db: Session, sap_codes) -> dict:
    """Batch variant: {sap_code: U_LastPurchasePrice} for codes that exist in OITM."""
    codes = sorted({c for c in sap_codes if c})
    if not codes:
        return {}
    rows = db.execute(
        sa_text('SELECT "ItemCode", "U_LastPurchasePrice" FROM icb_sap."OITM" '
                'WHERE "ItemCode" = ANY(:codes)'),
        {"codes": codes},
    ).all()
    return {c: p for (c, p) in rows if p is not None}
