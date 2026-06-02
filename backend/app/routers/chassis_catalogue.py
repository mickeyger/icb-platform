"""Read-only chassis catalogue for the Icecold Bodies MES Planning Ack panel
(Work Order v4.2).

Returns the live ChassisConstant (fixed steel + running-gear parts every chassis
includes) + ChassisOption (selectable suspension / brake / tyre / rim / lifting
axle dropdowns) records from the costing-app DB. The MES React mockup's "Browse
live catalogue" button on the Planning Ack panel hits this endpoint to render
the real catalogue alongside the costing's saved chassis BOM.

Read-only, no mutation. Origin-gated to MES dev origins (mirrors /api/mes/autologin).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..database import ChassisConstant, ChassisOption, get_db
from ..deps import get_current_user

router = APIRouter(prefix="/api/chassis", tags=["chassis-catalogue"])

_MES_ORIGINS = {
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
}


def _origin_ok(request: Request) -> bool:
    ref = request.headers.get("origin") or request.headers.get("referer") or ""
    return any(ref == o or ref.startswith(o + "/") for o in _MES_ORIGINS)


@router.get("/catalogue")
async def api_chassis_catalogue(request: Request, db: Session = Depends(get_db)):
    """Return the live chassis catalogue. Origin-gated to MES dev origins."""
    if not _origin_ok(request):
        raise HTTPException(status_code=403, detail="Origin not permitted")
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    constants = db.query(ChassisConstant).filter_by(is_active=True) \
        .order_by(ChassisConstant.category, ChassisConstant.sort_order, ChassisConstant.name).all()
    options = db.query(ChassisOption).filter_by(is_active=True) \
        .order_by(ChassisOption.kind, ChassisOption.label).all()
    return {
        "constants": [
            {
                "id": c.id,
                "category": c.category,
                "name": c.name,
                "qty_per_metre": c.qty_per_metre,
                "qty_constant": c.qty_constant,
                "unit_price": c.unit_price,
            }
            for c in constants
        ],
        "options": [
            {
                "id": o.id,
                "kind": o.kind,
                "label": o.label,
                "axle_count": o.axle_count,
                "tyre_style": o.tyre_style,
                "price": o.price,
            }
            for o in options
        ],
    }
