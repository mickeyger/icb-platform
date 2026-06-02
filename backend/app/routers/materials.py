from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import (
    get_db, Material, MaterialCategory, PriceHistory,
    BillOfMaterial, TrailerType, BomOverrideHistory,
)
from ..deps import get_current_user, require_admin, user_can
from ..templates_config import templates

router = APIRouter()


@router.get("/api/materials")
async def get_materials(cat_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(Material).filter_by(is_active=True)
    if cat_id:
        q = q.filter_by(category_id=cat_id)
    mats = q.order_by(Material.name).all()

    # Single query: count BOM rows with a non-null override per material
    override_counts = dict(
        db.query(BillOfMaterial.material_id, func.count(BillOfMaterial.id))
        .filter(BillOfMaterial.unit_price_override.isnot(None))
        .group_by(BillOfMaterial.material_id)
        .all()
    )

    return [{"id": m.id, "name": m.name,
             "category": m.category.name if m.category else "",
             "category_id": m.category_id,
             "unit": m.unit_of_measure, "price": m.price_per_unit, "supplier": m.supplier or "",
             "sap_code": m.sap_code or "", "material_code": m.material_code or "",
             "manufacture_sub_category": m.manufacture_sub_category or "",
             "size": m.size or "", "last_updated": str(m.last_updated)[:10],
             "last_bulk_update_at":   m.last_bulk_update_at.isoformat() if m.last_bulk_update_at else None,
             "last_bulk_update_note": m.last_bulk_update_note or "",
             "override_count": override_counts.get(m.id, 0),
             "version_ts": m.last_updated.isoformat() if m.last_updated else ""} for m in mats]


@router.post("/api/materials")
async def create_material(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    mat = Material(**{k: v for k, v in body.items() if k in [
        "name", "category_id", "unit_of_measure", "price_per_unit",
        "supplier", "material_code", "sap_code", "size",
        "manufacture_sub_category"]})
    mat.last_updated = datetime.now(timezone.utc)
    db.add(mat)
    db.commit()
    db.refresh(mat)
    return {"id": mat.id, "name": mat.name}


@router.put("/api/materials/{mat_id}")
async def update_material(mat_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    mat = db.query(Material).filter_by(id=mat_id).first()
    if not mat:
        raise HTTPException(status_code=404)
    client_ts = (body.pop("version_ts", None) or "").strip()
    if client_ts and mat.last_updated:
        if client_ts != mat.last_updated.isoformat():
            raise HTTPException(
                status_code=409,
                detail="This material was updated by someone else while you had it open. "
                       "Close this dialog, refresh the list, and try again."
            )
    old_price = mat.price_per_unit
    for k, v in body.items():
        if hasattr(mat, k) and k not in ["id"]:
            setattr(mat, k, v)
    mat.last_updated = datetime.now(timezone.utc)
    if "price_per_unit" in body and body["price_per_unit"] != old_price:
        db.add(PriceHistory(material_id=mat_id, old_price=old_price,
                            new_price=body["price_per_unit"]))
    db.commit()
    return {"ok": True}


@router.delete("/api/materials/{mat_id}")
async def delete_material(mat_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    mat = db.query(Material).filter_by(id=mat_id).first()
    if mat:
        mat.is_active = False
        db.commit()
    return {"ok": True}


@router.post("/api/materials/bulk-price")
async def bulk_price_update(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    ids       = body.get("ids") or []
    percent   = float(body.get("percent") or 0)
    summary   = (body.get("filter_summary") or "").strip()
    if not ids or percent == 0:
        raise HTTPException(status_code=400, detail="ids and non-zero percent required")
    if abs(percent) > 50:
        raise HTTPException(status_code=400, detail="Percent must be between -50 and 50")
    factor = 1 + percent / 100.0
    now    = datetime.now(timezone.utc)
    sign   = "+" if percent > 0 else ""
    note   = f"{sign}{percent:g}% on {now.strftime('%Y-%m-%d')}"
    if summary:
        note = f"{note} — {summary}"
    mats = db.query(Material).filter(Material.id.in_(ids), Material.is_active == True).all()
    updated_ids = []
    updated = 0
    for m in mats:
        old = m.price_per_unit or 0
        new = round(old * factor, 4)
        if new == old:
            continue
        db.add(PriceHistory(material_id=m.id, old_price=old, new_price=new))
        m.price_per_unit        = new
        m.last_updated          = now
        m.last_bulk_update_at   = now
        m.last_bulk_update_note = note
        updated_ids.append(m.id)
        updated += 1
    db.commit()

    # Find BOM rows that have unit_price_override for the affected materials.
    # Split by protected vs unprotected body types so the UI can present both groups.
    bypassed_overrides = []
    protected_overrides = []
    if updated_ids:
        bom_rows = (
            db.query(BillOfMaterial, TrailerType, Material)
            .join(TrailerType, BillOfMaterial.trailer_type_id == TrailerType.id)
            .join(Material, BillOfMaterial.material_id == Material.id)
            .filter(
                BillOfMaterial.material_id.in_(updated_ids),
                BillOfMaterial.unit_price_override.isnot(None),
            )
            .all()
        )
        mat_new_prices = {m.id: m.price_per_unit for m in mats}
        for bom, tt, mat in bom_rows:
            entry = {
                "bom_id": bom.id,
                "material_id": mat.id,
                "material_name": mat.name,
                "trailer_type_id": tt.id,
                "trailer_type_name": tt.name,
                "current_override": bom.unit_price_override,
                "new_base_price": mat_new_prices.get(mat.id),
                "percent": percent,
            }
            if tt.protect_overrides:
                protected_overrides.append(entry)
            else:
                bypassed_overrides.append(entry)

    return {
        "ok": True,
        "updated": updated,
        "note": note,
        "batch_at": now.isoformat(),
        "bypassed_overrides": bypassed_overrides,
        "protected_overrides": protected_overrides,
    }


@router.post("/api/materials/bulk-price/undo")
async def bulk_price_undo(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    latest = db.query(Material).filter(Material.last_bulk_update_at.isnot(None)) \
               .order_by(Material.last_bulk_update_at.desc()).first()
    if not latest:
        raise HTTPException(status_code=404, detail="No bulk update to undo")
    batch_at = latest.last_bulk_update_at
    mats = db.query(Material).filter(Material.last_bulk_update_at == batch_at).all()
    reverted = 0
    for m in mats:
        ph = db.query(PriceHistory).filter_by(material_id=m.id) \
               .order_by(PriceHistory.changed_date.desc()).first()
        if not ph:
            continue
        m.price_per_unit       = ph.old_price
        m.last_updated         = datetime.now(timezone.utc)
        m.last_bulk_update_at  = None
        m.last_bulk_update_note = None
        db.delete(ph)
        reverted += 1
    db.commit()
    return {"ok": True, "reverted": reverted}


@router.post("/api/materials/bulk-price/apply-bom-overrides")
async def apply_bom_override_bulk(request: Request, db: Session = Depends(get_db)):
    """Apply a % change to selected BOM unit_price_override rows.
    Records a batch in bom_override_history so the whole batch can be undone."""
    require_admin(request, db)
    body = await request.json()
    bom_ids = body.get("bom_ids") or []
    percent = float(body.get("percent") or 0)
    if not bom_ids or percent == 0:
        raise HTTPException(status_code=400, detail="bom_ids and non-zero percent required")
    if abs(percent) > 50:
        raise HTTPException(status_code=400, detail="Percent must be between -50 and 50")

    factor  = 1 + percent / 100.0
    now     = datetime.now(timezone.utc)
    updated = 0

    rows = (
        db.query(BillOfMaterial, TrailerType, Material)
        .join(TrailerType, BillOfMaterial.trailer_type_id == TrailerType.id)
        .join(Material, BillOfMaterial.material_id == Material.id)
        .filter(
            BillOfMaterial.id.in_(bom_ids),
            BillOfMaterial.unit_price_override.isnot(None),
            TrailerType.protect_overrides == False,
        )
        .all()
    )

    for bom, tt, mat in rows:
        old = bom.unit_price_override
        new = round(old * factor, 4)
        db.add(BomOverrideHistory(
            bom_id=bom.id,
            material_id=mat.id,
            trailer_type_id=tt.id,
            trailer_type_name=tt.name,
            material_name=mat.name,
            old_price=old,
            new_price=new,
            changed_at=now,
            batch_at=now,
        ))
        bom.unit_price_override = new
        updated += 1

    db.commit()
    return {"ok": True, "updated": updated, "batch_at": now.isoformat()}


@router.post("/api/materials/bulk-price/undo-bom-overrides")
async def undo_bom_override_bulk(request: Request, db: Session = Depends(get_db)):
    """Revert the most recent BT override bulk update batch."""
    require_admin(request, db)
    latest = (
        db.query(BomOverrideHistory)
        .order_by(BomOverrideHistory.batch_at.desc())
        .first()
    )
    if not latest:
        raise HTTPException(status_code=404, detail="No BT override bulk update to undo")
    batch_at = latest.batch_at
    rows = db.query(BomOverrideHistory).filter_by(batch_at=batch_at).all()
    reverted = 0
    for h in rows:
        bom = db.query(BillOfMaterial).filter_by(id=h.bom_id).first()
        if bom:
            bom.unit_price_override = h.old_price
            reverted += 1
        db.delete(h)
    db.commit()
    return {"ok": True, "reverted": reverted}


@router.get("/api/materials/{mat_id}/bom-overrides")
async def get_material_bom_overrides(mat_id: int, db: Session = Depends(get_db)):
    """Return all body-type BOM override rows for a single material (drilldown)."""
    rows = (
        db.query(BillOfMaterial, TrailerType)
        .join(TrailerType, BillOfMaterial.trailer_type_id == TrailerType.id)
        .filter(
            BillOfMaterial.material_id == mat_id,
            BillOfMaterial.unit_price_override.isnot(None),
        )
        .order_by(TrailerType.name)
        .all()
    )
    mat = db.query(Material).filter_by(id=mat_id).first()
    base_price = mat.price_per_unit if mat else None
    return [
        {
            "bom_id": bom.id,
            "trailer_type_id": tt.id,
            "trailer_type_name": tt.name,
            "override_price": bom.unit_price_override,
            "base_price": base_price,
            "section": bom.bom_section or "",
            "protect_overrides": tt.protect_overrides,
        }
        for bom, tt in rows
    ]


@router.get("/api/materials/{mat_id}/trailer-usage")
async def get_material_trailer_usage(mat_id: int, db: Session = Depends(get_db)):
    """Return every BOM row for a material across all active body types.
    Used by the price-edit modals (calculator & admin/materials) to show
    'also used in these body types' with the effective price for each."""
    mat = db.query(Material).filter_by(id=mat_id).first()
    if not mat:
        raise HTTPException(status_code=404)
    base_price = mat.price_per_unit or 0

    rows = (
        db.query(BillOfMaterial, TrailerType)
        .join(TrailerType, BillOfMaterial.trailer_type_id == TrailerType.id)
        .filter(
            BillOfMaterial.material_id == mat_id,
            TrailerType.is_active == True,
        )
        .order_by(TrailerType.name)
        .all()
    )
    return [
        {
            "bom_id": bom.id,
            "trailer_id": tt.id,
            "trailer_name": tt.name,
            "effective_price": (
                bom.unit_price_override
                if bom.unit_price_override is not None
                else base_price
            ),
            "has_override": bom.unit_price_override is not None,
            "base_price": base_price,
            "bom_section": bom.bom_section or "",
        }
        for bom, tt in rows
    ]


@router.get("/api/materials/bom-overrides/all")
async def get_all_bom_overrides(
    trailer_type_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Return every BOM override row, optionally filtered by body type.
    Used by the Body Type Overrides tab."""
    q = (
        db.query(BillOfMaterial, TrailerType, Material)
        .join(TrailerType, BillOfMaterial.trailer_type_id == TrailerType.id)
        .join(Material, BillOfMaterial.material_id == Material.id)
        .filter(
            BillOfMaterial.unit_price_override.isnot(None),
            TrailerType.is_active == True,
            Material.is_active == True,
        )
    )
    if trailer_type_id:
        q = q.filter(BillOfMaterial.trailer_type_id == trailer_type_id)
    rows = q.order_by(TrailerType.name, Material.name).all()
    return [
        {
            "bom_id": bom.id,
            "material_id": mat.id,
            "material_name": mat.name,
            "material_category": mat.category.name if mat.category else "",
            "trailer_type_id": tt.id,
            "trailer_type_name": tt.name,
            "override_price": bom.unit_price_override,
            "base_price": mat.price_per_unit,
            "section": bom.bom_section or "",
            "protect_overrides": tt.protect_overrides,
        }
        for bom, tt, mat in rows
    ]


@router.put("/api/materials/bom-overrides/{bom_id}")
async def update_single_bom_override(bom_id: int, request: Request,
                                     db: Session = Depends(get_db)):
    """Set or clear a single BOM unit_price_override from the overrides tab."""
    require_admin(request, db)
    body = await request.json()
    action = body.get("action")  # "set", "clear", or "sync"
    bom = db.query(BillOfMaterial).filter_by(id=bom_id).first()
    if not bom:
        raise HTTPException(status_code=404)
    if action == "clear":
        bom.unit_price_override = None
    elif action == "sync":
        # Set override to current base material price
        mat = db.query(Material).filter_by(id=bom.material_id).first()
        bom.unit_price_override = mat.price_per_unit if mat else bom.unit_price_override
    elif action == "set":
        new_price = body.get("price")
        if new_price is None:
            raise HTTPException(status_code=400, detail="price required for set action")
        bom.unit_price_override = float(new_price)
    else:
        raise HTTPException(status_code=400, detail="action must be set, clear, or sync")
    db.commit()
    return {"ok": True, "unit_price_override": bom.unit_price_override}


@router.put("/api/trailer-types/{tt_id}/protect-overrides")
async def set_protect_overrides(tt_id: int, request: Request, db: Session = Depends(get_db)):
    """Toggle the protect_overrides flag on a body type."""
    require_admin(request, db)
    body = await request.json()
    tt = db.query(TrailerType).filter_by(id=tt_id).first()
    if not tt:
        raise HTTPException(status_code=404)
    tt.protect_overrides = bool(body.get("protect", False))
    db.commit()
    return {"ok": True, "protect_overrides": tt.protect_overrides}


@router.get("/api/categories")
async def get_categories(db: Session = Depends(get_db)):
    cats = db.query(MaterialCategory).order_by(MaterialCategory.name).all()
    return [{"id": c.id, "name": c.name, "description": c.description or ""} for c in cats]


@router.post("/api/categories")
async def create_category(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    cat = MaterialCategory(name=body["name"], description=body.get("description", ""))
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return {"id": cat.id, "name": cat.name}


@router.get("/api/materials/{mat_id}/history")
async def price_history(mat_id: int, db: Session = Depends(get_db)):
    rows = (db.query(PriceHistory).filter_by(material_id=mat_id)
            .order_by(PriceHistory.changed_date.desc()).limit(20).all())
    return [{"old": r.old_price, "new": r.new_price,
             "date": str(r.changed_date)[:16]} for r in rows]


@router.get("/admin/materials", response_class=HTMLResponse)
async def admin_materials(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login")
    if not user_can(user, "menu.materials", db):
        raise HTTPException(status_code=403, detail="Not authorized")
    cats = db.query(MaterialCategory).order_by(MaterialCategory.name).all()
    return templates.TemplateResponse("admin_materials.html", {
        "request": request, "user": user, "categories": cats,
    })
