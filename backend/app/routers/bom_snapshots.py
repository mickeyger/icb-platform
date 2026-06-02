"""BOM snapshot capture, storage, and comparison."""

import io
import json
from collections import defaultdict
from datetime import datetime, timezone, date

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from ..database import (
    get_db, BillOfMaterial, TrailerType, BomSnapshot, BomSnapshotItem, BomOverrideHistory,
    Formula, GlobalVariable,
)
from ..deps import require_admin, get_current_user
from ..services import _bom_load_options
from ..templates_config import templates
from ..formula_engine import calculate_bom
from ..excel_bom_parser import best_sheet_match, norm as _enorm
from .calculator import _build_bom_items, _build_body_variables

import openpyxl

router = APIRouter()

FALLBACK_DIMS = {
    "floor_thickness": 0.060,
    "panel_thickness": 0.042,
    "insulation_thickness": 0.060,
    "num_doors": 2,
    "num_axles": 2,
}


def _trailer_dims(tt: TrailerType) -> dict:
    return {
        "length": float(tt.default_length or 7.5),
        "width":  float(tt.default_width  or 2.6),
        "height": float(tt.default_height or 2.6),
        **FALLBACK_DIMS,
    }


def _capture_app_snapshot(trailer_type_id: int, label: str, db: Session) -> BomSnapshot:
    tt = db.query(TrailerType).filter_by(id=trailer_type_id).first()
    if not tt:
        raise HTTPException(status_code=404, detail="Trailer type not found")

    bom_rows = (
        db.query(BillOfMaterial)
        .filter(BillOfMaterial.trailer_type_id == trailer_type_id)
        .options(*_bom_load_options())
        .order_by(BillOfMaterial.sort_order)
        .all()
    )

    dims = _trailer_dims(tt)
    body_variables = _build_body_variables(bom_rows)
    # Capture with all body options OFF (baseline — no DRD/SRD toggles)
    bom_items = _build_bom_items(bom_rows, dims, {}, {}, db)
    formula_lib = {f.name.lower(): f.expression
                   for f in db.query(Formula).filter_by(is_active=True).all()}
    global_vars = {gv.name: gv.value for gv in db.query(GlobalVariable).all()}
    result = calculate_bom(bom_items, dims, body_variables, formula_lib, global_vars)

    snap = BomSnapshot(
        trailer_type_id=trailer_type_id,
        source="app",
        label=label.strip() if label else None,
        dims_json=json.dumps(dims),
        snapshot_date=date.today().isoformat(),
        created_at=datetime.now(timezone.utc),
    )
    db.add(snap)
    db.flush()  # get snap.id

    sort = 0
    for item in result["items"]:
        db.add(BomSnapshotItem(
            snapshot_id=snap.id,
            category=item["category"],
            item_name=item["material"],
            formula=item["formula"],
            quantity=item["quantity"],
            unit_price=item["unit_price"],
            total=item["line_cost"],
            sort_order=sort,
            bom_id=item.get("bom_id"),
        ))
        sort += 1

    db.commit()
    db.refresh(snap)
    return snap


# ─── Pages ───────────────────────────────────────────────────────────────────

@router.get("/admin/bom-snapshots", response_class=HTMLResponse)
async def snapshot_list(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/login")
    require_admin(request, db)

    snapshots = (
        db.query(BomSnapshot)
        .order_by(BomSnapshot.created_at.desc())
        .all()
    )
    # Annotate each with grand total
    snap_data = []
    for s in snapshots:
        grand = round(sum(i.total for i in s.items), 2)
        snap_data.append({
            "id": s.id,
            "trailer_name": s.trailer_type.name if s.trailer_type else "—",
            "trailer_type_id": s.trailer_type_id,
            "source": s.source,
            "label": s.label or "",
            "source_file": s.source_file or "",
            "snapshot_date": s.snapshot_date,
            "grand_total": grand,
            "item_count": len(s.items),
            "is_pinned_baseline": bool(s.is_pinned_baseline),
            "is_stale": bool(s.is_stale),
        })

    trailer_types = (
        db.query(TrailerType)
        .filter_by(is_active=True)
        .order_by(TrailerType.name)
        .all()
    )

    return templates.TemplateResponse("bom_snapshots.html", {
        "request": request,
        "user": user,
        "snapshots": snap_data,
        "trailer_types": trailer_types,
    })


@router.get("/admin/bom-snapshots/{snapshot_id}", response_class=HTMLResponse)
async def snapshot_detail(snapshot_id: int, request: Request,
                          compare_to: int = None,
                          db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/login")
    require_admin(request, db)

    snap = db.query(BomSnapshot).filter_by(id=snapshot_id).first()
    if not snap:
        raise HTTPException(status_code=404)

    # Group items by category
    categories = {}
    for it in snap.items:
        categories.setdefault(it.category, []).append(it)
    cat_totals = {cat: round(sum(i.total for i in items), 2)
                  for cat, items in categories.items()}
    grand_total = round(sum(cat_totals.values()), 2)

    # Optional comparison snapshot — positional matching handles duplicate names
    comp_data = None
    item_diffs = {}        # snap_item.id -> float diff (0.0 = no change) or None = new item
    comp_item_totals = {}  # snap_item.id -> comp snapshot's total for that item
    comp_item_prices = {}  # snap_item.id -> comp snapshot's unit_price for that item
    cat_diffs  = {}        # cat -> float diff

    if compare_to:
        comp = db.query(BomSnapshot).filter_by(id=compare_to).first()
        if comp:
            # Build per-(category, name) queues ordered by sort_order
            # Each entry stores (total, unit_price) so both values travel together
            queues: dict[tuple, list] = defaultdict(list)
            for it in sorted(comp.items, key=lambda x: x.sort_order):
                queues[(it.category, it.item_name)].append(
                    (round(float(it.total), 2), it.unit_price)
                )

            for it in snap.items:
                key = (it.category, it.item_name)
                q = queues[key]
                if q:
                    comp_total, comp_unit_price = q.pop(0)
                    # Excel total = 0 means this item is not costed for this config —
                    # not a real price difference, treat as not comparable
                    if abs(comp_total) < 0.01:
                        comp_item_totals[it.id] = None
                        comp_item_prices[it.id] = None
                        item_diffs[it.id] = 0.0
                    else:
                        comp_item_totals[it.id] = comp_total
                        comp_item_prices[it.id] = comp_unit_price
                        raw_diff = round(float(it.total) - comp_total, 2)
                        item_diffs[it.id] = raw_diff if abs(raw_diff) >= 0.01 else 0.0
                else:
                    comp_item_totals[it.id] = None
                    comp_item_prices[it.id] = None
                    item_diffs[it.id] = None  # item exists in snap but not in comp

            for cat, items in categories.items():
                d = round(sum(
                    item_diffs[it.id] for it in items
                    if item_diffs.get(it.id) is not None
                ), 2)
                cat_diffs[cat] = d if abs(d) >= 0.01 else 0.0

            comp_grand = round(sum(round(float(it.total), 2) for it in comp.items), 2)
            comp_data = {
                "id": comp.id,
                "label": comp.label or comp.snapshot_date,
                "source": comp.source,
                "grand_total": comp_grand,
            }

    # Sibling snapshots for the same body type (for compare dropdown)
    siblings = (
        db.query(BomSnapshot)
        .filter(BomSnapshot.trailer_type_id == snap.trailer_type_id,
                BomSnapshot.id != snap.id)
        .order_by(BomSnapshot.created_at.desc())
        .all()
    )

    dims = json.loads(snap.dims_json) if snap.dims_json else {}

    # Pricing-source info for each item — tells user where to go to update the price
    _PRICING_SOURCES = {
        "skin_formula_id":   ("Skin Formulas",    "/admin/skin-formulas"),
        "floor_plate_id":    ("Floor Plates",     "/admin/floor-plates"),
        "taping_block_id":   ("Taping Blocks",    "/admin/taping-blocks"),
        "mounting_cleat_id": ("Mounting Cleats",  "/admin/mounting-cleats"),
    }
    pricing_sources: dict[int, dict] = {}
    if snap.source == "app":
        bom_ids = [it.bom_id for it in snap.items if it.bom_id]
        if bom_ids:
            bom_map = {
                row.id: row
                for row in db.query(BillOfMaterial)
                              .filter(BillOfMaterial.id.in_(bom_ids))
                              .all()
            }
            for it in snap.items:
                row = bom_map.get(it.bom_id) if it.bom_id else None
                if not row:
                    continue
                src = None
                for field, (label, url) in _PRICING_SOURCES.items():
                    if getattr(row, field, None):
                        src = {"label": label, "url": url}
                        break
                if src is None:
                    if row.unit_price_override is not None:
                        src = {"label": "Materials & Prices (manual override)", "url": "/admin/materials"}
                    else:
                        src = {"label": "Materials & Prices", "url": "/admin/materials"}
                pricing_sources[it.id] = src

    # Pinned baseline for this body type (may be a different snapshot)
    pinned_baseline = (
        db.query(BomSnapshot)
        .filter(
            BomSnapshot.trailer_type_id == snap.trailer_type_id,
            BomSnapshot.is_pinned_baseline == True,
        )
        .first()
    )

    return templates.TemplateResponse("bom_snapshot_detail.html", {
        "request": request,
        "user": user,
        "snap": snap,
        "categories": categories,
        "cat_totals": cat_totals,
        "grand_total": grand_total,
        "dims": dims,
        "comp_data": comp_data,
        "item_diffs": item_diffs,
        "comp_item_totals": comp_item_totals,
        "comp_item_prices": comp_item_prices,
        "cat_diffs": cat_diffs,
        "compare_to": compare_to,
        "siblings": siblings,
        "pricing_sources": pricing_sources,
        "pinned_baseline": pinned_baseline,
    })


# ─── API ─────────────────────────────────────────────────────────────────────

@router.post("/api/bom-snapshots/capture")
async def capture_snapshot(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    trailer_type_id = int(body.get("trailer_type_id", 0))
    label = body.get("label", "")
    if not trailer_type_id:
        raise HTTPException(status_code=400, detail="trailer_type_id required")
    snap = _capture_app_snapshot(trailer_type_id, label, db)
    grand = round(sum(i.total for i in snap.items), 2)
    return JSONResponse({
        "ok": True,
        "snapshot_id": snap.id,
        "grand_total": grand,
        "item_count": len(snap.items),
        "redirect": f"/admin/bom-snapshots/{snap.id}",
    })


@router.post("/api/bom-snapshots/capture-excel")
async def capture_excel_snapshot(
    request: Request,
    trailer_type_id: int = Form(...),
    label: str = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    require_admin(request, db)

    tt = db.query(TrailerType).filter_by(id=trailer_type_id).first()
    if not tt:
        raise HTTPException(status_code=404, detail="Trailer type not found")

    contents = await file.read()
    filename = file.filename or "upload.xlsx"

    # Write to a temp file so excel_importer can open it with xlrd/openpyxl
    import tempfile, os
    suffix = ".xlsx" if filename.lower().endswith(".xlsx") else ".xls"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        # List sheets to find the best match for this trailer type
        try:
            tmp_wb = openpyxl.load_workbook(tmp_path, data_only=True, read_only=True)
            candidate_sheets = [ws.title for ws in tmp_wb.worksheets]
            tmp_wb.close()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not open Excel file: {e}")

        matched_sheet, score = best_sheet_match(candidate_sheets, tt.name)
        if not matched_sheet or score < 0.2:
            raise HTTPException(
                status_code=422,
                detail=f'No matching sheet found for "{tt.name}" in {filename}. '
                       f'Best match was "{matched_sheet}" (score {score:.2f}).'
            )

        # Use the full excel_importer parser — same logic as the BOM import wizard
        from .. import excel_importer as xi
        try:
            parsed = xi.parse_sheet(matched_sheet, grp_path=tmp_path)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f'Failed to parse sheet "{matched_sheet}": {e}')

        if not parsed.sections:
            raise HTTPException(status_code=422,
                                detail=f'Sheet "{matched_sheet}" contained no parseable BOM sections.')

        snap = BomSnapshot(
            trailer_type_id=trailer_type_id,
            source="excel",
            label=label.strip() if label else None,
            source_file=filename,
            dims_json=None,
            snapshot_date=date.today().isoformat(),
            created_at=datetime.now(timezone.utc),
        )
        db.add(snap)
        db.flush()

        sort = 0
        for section in parsed.sections:
            # section.multiplier = 2.0 for SIDES (two sides of the body), 1.0 for all others.
            # item.excel_total is the per-item column-H value for ONE side; we scale it up
            # so Excel snapshot totals match the App snapshot (which applies the multiplier
            # via formula_engine.calculate_bom → qty_raw * section_multiplier).
            sect_mult = float(section.multiplier or 1.0)
            for item in section.items:
                # Skip items with no Excel total (not costed in this config)
                if item.excel_total is None:
                    continue
                scaled_qty   = (item.qty * sect_mult)   if item.qty   is not None else None
                scaled_total = round(float(item.excel_total) * sect_mult, 2)
                db.add(BomSnapshotItem(
                    snapshot_id=snap.id,
                    category=section.name,
                    item_name=item.name,
                    formula=item.symbolic_formula or None,
                    quantity=scaled_qty,
                    unit_price=item.unit_price if item.unit_price else None,
                    total=scaled_total,
                    sort_order=sort,
                    bom_id=None,  # Excel snapshots have no app BOM link
                ))
                sort += 1

        db.commit()
        db.refresh(snap)

    finally:
        os.unlink(tmp_path)

    grand = round(sum(i.total for i in snap.items), 2)
    return JSONResponse({
        "ok": True,
        "snapshot_id": snap.id,
        "grand_total": grand,
        "item_count": len(snap.items),
        "matched_sheet": matched_sheet,
        "match_score": round(score, 3),
        "redirect": f"/admin/bom-snapshots/{snap.id}",
    })


@router.post("/api/bom-snapshots/items/{snap_item_id}/update-price")
async def update_snapshot_item_price(
    snap_item_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    require_admin(request, db)
    body = await request.json()
    new_price = body.get("unit_price")
    if new_price is None:
        raise HTTPException(status_code=400, detail="unit_price required")
    try:
        new_price = float(new_price)
        if new_price < 0:
            raise ValueError
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="unit_price must be a non-negative number")

    snap_item = db.query(BomSnapshotItem).filter_by(id=snap_item_id).first()
    if not snap_item:
        raise HTTPException(status_code=404, detail="Snapshot item not found")
    if not snap_item.bom_id:
        raise HTTPException(status_code=422, detail="This item has no linked BOM row (Excel snapshots cannot be edited)")

    bom_row = db.query(BillOfMaterial).filter_by(id=snap_item.bom_id).first()
    if not bom_row:
        raise HTTPException(status_code=404, detail="Linked BOM row not found")

    bom_row.unit_price_override = new_price

    # Flag the snapshot so the UI can prompt for a re-capture
    parent_snap = db.query(BomSnapshot).filter_by(id=snap_item.snapshot_id).first()
    if parent_snap:
        parent_snap.is_stale = True

    db.commit()

    return JSONResponse({
        "ok": True,
        "bom_id": snap_item.bom_id,
        "material_name": bom_row.material.name if bom_row.material else snap_item.item_name,
        "unit_price_override": new_price,
    })


@router.post("/api/bom-snapshots/{snapshot_id}/pin")
async def pin_snapshot_as_baseline(snapshot_id: int, request: Request,
                                   db: Session = Depends(get_db)):
    """Mark this snapshot as the pinned baseline for its body type.
    Unpins any previously pinned snapshot for the same body type."""
    require_admin(request, db)
    snap = db.query(BomSnapshot).filter_by(id=snapshot_id).first()
    if not snap:
        raise HTTPException(status_code=404)
    # Unpin any existing baseline for this body type
    db.query(BomSnapshot).filter(
        BomSnapshot.trailer_type_id == snap.trailer_type_id,
        BomSnapshot.is_pinned_baseline == True,
        BomSnapshot.id != snapshot_id,
    ).update({"is_pinned_baseline": False})
    snap.is_pinned_baseline = True
    db.commit()
    return {"ok": True, "pinned": True}


@router.post("/api/bom-snapshots/{snapshot_id}/unpin")
async def unpin_snapshot_baseline(snapshot_id: int, request: Request,
                                  db: Session = Depends(get_db)):
    """Remove the pinned baseline flag from this snapshot."""
    require_admin(request, db)
    snap = db.query(BomSnapshot).filter_by(id=snapshot_id).first()
    if not snap:
        raise HTTPException(status_code=404)
    snap.is_pinned_baseline = False
    db.commit()
    return {"ok": True, "pinned": False}


@router.post("/api/bom-snapshots/{snapshot_id}/restore-baseline")
async def restore_snapshot_baseline(snapshot_id: int, request: Request,
                                    db: Session = Depends(get_db)):
    """Restore this snapshot's prices by writing unit_price_override back onto
    every linked BOM row.  Records the changes in bom_override_history so the
    restore can be undone via the BT override undo endpoint."""
    require_admin(request, db)
    snap = db.query(BomSnapshot).filter_by(id=snapshot_id).first()
    if not snap:
        raise HTTPException(status_code=404)

    now = datetime.now(timezone.utc)
    restored = 0
    skipped  = 0  # items with no bom_id (Excel snapshots) or no unit_price

    for item in snap.items:
        if not item.bom_id or item.unit_price is None:
            skipped += 1
            continue
        bom = db.query(BillOfMaterial).filter_by(id=item.bom_id).first()
        if not bom:
            skipped += 1
            continue

        old_price = bom.unit_price_override
        new_price = item.unit_price

        # Record history so this can be undone
        db.add(BomOverrideHistory(
            bom_id=bom.id,
            material_id=bom.material_id,
            trailer_type_id=snap.trailer_type_id,
            trailer_type_name=snap.trailer_type.name if snap.trailer_type else "",
            material_name=item.item_name,
            old_price=old_price,
            new_price=new_price,
            changed_at=now,
            batch_at=now,
        ))
        bom.unit_price_override = new_price
        restored += 1

    db.commit()
    return {"ok": True, "restored": restored, "skipped": skipped}


@router.delete("/api/bom-snapshots/{snapshot_id}")
async def delete_snapshot(snapshot_id: int, request: Request,
                          db: Session = Depends(get_db)):
    require_admin(request, db)
    snap = db.query(BomSnapshot).filter_by(id=snapshot_id).first()
    if not snap:
        raise HTTPException(status_code=404)
    db.delete(snap)
    db.commit()
    return {"ok": True}
