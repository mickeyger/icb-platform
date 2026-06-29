import json
from datetime import datetime, timezone, date

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..database import (
    get_db,
    TrailerType, BillOfMaterial, Material, MaterialCategory,
    BOMSection, BodyOptionGroup, BodyOptionSubgroup,
    TrailerRatio,
    ConfiguratorSnapshot, ConfiguratorDraft, ConfiguratorDraftSnapshot,
)  # Material is used by the configurator move-section endpoint
from ..deps import get_current_user, require_admin, require_user, user_can
from ..services import (
    _bom_load_options,
    _compute_skin_formula_cost, _compute_taping_block_cost, _compute_floor_plate_cost,
    _compute_mounting_cleat_cost,
    _resolve_bom_section, _resolve_body_option_group, _resolve_body_option_subgroup,
    archive_trailer_template_binding,
    get_section_snapshot,
)
from ..templates_config import templates

router = APIRouter()


# ─── Trailer Types ────────────────────────────────────────────────────────────

@router.get("/api/trailers")
async def get_trailers(db: Session = Depends(get_db)):
    tts = db.query(TrailerType).filter_by(is_active=True).order_by(TrailerType.name).all()
    return [{"id": t.id, "name": t.name, "description": t.description or "",
             "default_length":    t.default_length,
             "default_width":     t.default_width,
             "default_height":    t.default_height,
             "markup_percentage": t.markup_percentage or 0.0,
             "protect_overrides": bool(t.protect_overrides),
             "configurator_v2":   bool(t.configurator_v2)} for t in tts]


@router.post("/api/trailers")
async def create_trailer(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    existing = db.query(TrailerType).filter_by(is_active=True, name=name).first()
    if existing:
        raise HTTPException(status_code=400, detail=f'A trailer type named "{name}" already exists')
    tt = TrailerType(name=name, description=body.get("description", ""))
    db.add(tt)
    db.commit()
    db.refresh(tt)
    return {"id": tt.id, "name": tt.name}


@router.put("/api/trailers/{tt_id}")
async def update_trailer(tt_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    tt = db.query(TrailerType).filter_by(id=tt_id).first()
    if not tt:
        raise HTTPException(status_code=404)
    new_name = body.get("name", "").strip()
    if new_name and new_name != tt.name:
        existing = db.query(TrailerType).filter(
            TrailerType.is_active == True,
            TrailerType.name == new_name,
            TrailerType.id != tt_id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail=f'A trailer type named "{new_name}" already exists')
    for k, v in body.items():
        if hasattr(tt, k) and k not in ["id"]:
            setattr(tt, k, v)
    db.commit()
    return {"ok": True}


@router.delete("/api/trailers/{tt_id}")
async def delete_trailer(tt_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    tt = db.query(TrailerType).filter_by(id=tt_id).first()
    if tt:
        archive_trailer_template_binding(tt, db)
        tt.is_active = False
        tt.name = f"{tt.name} [deleted-{tt_id}]"
        db.commit()
    return {"ok": True}


@router.post("/api/trailers/{tt_id}/duplicate")
async def duplicate_trailer(tt_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    src = db.query(TrailerType).filter_by(id=tt_id).first()
    if not src:
        raise HTTPException(status_code=404)
    body = await request.json()
    new_tt = TrailerType(
        name=body.get("name", src.name + " (Copy)"),
        description=src.description,
        default_length=src.default_length,
        default_width=src.default_width,
        default_height=src.default_height,
        markup_percentage=src.markup_percentage,
        group_id=src.group_id,
        override_report_template_id=src.override_report_template_id,
    )
    db.add(new_tt)
    db.flush()
    for bom in src.bom_items:
        db.add(BillOfMaterial(
            trailer_type_id=new_tt.id,
            material_id=bom.material_id,
            formula_expression=bom.formula_expression,
            waste_percentage=bom.waste_percentage,
            notes=bom.notes,
            sort_order=bom.sort_order,
            bom_section=bom.bom_section,
            bom_section_id=bom.bom_section_id,
            unit_price_override=bom.unit_price_override,
            unit_price_snapshot=bom.unit_price_snapshot,
            excel_formula=bom.excel_formula,
            source_cell=bom.source_cell,
            is_formula_skin=bom.is_formula_skin,
            highlight_color=bom.highlight_color,
            is_body_option=bom.is_body_option,
            body_option_group=bom.body_option_group,
            body_option_group_id=bom.body_option_group_id,
            body_option_subgroup=bom.body_option_subgroup,
            body_option_subgroup_id=bom.body_option_subgroup_id,
            body_option_default=bom.body_option_default,
            body_option_linked=bom.body_option_linked,
            body_option_linked_id=bom.body_option_linked_id,
        ))
    for ratio in src.ratios:
        db.add(TrailerRatio(
            trailer_type_id=new_tt.id,
            ratio_value=ratio.ratio_value,
            label=ratio.label,
            sort_order=ratio.sort_order,
        ))
    db.commit()
    return {"id": new_tt.id, "name": new_tt.name}


# ─── BOM ─────────────────────────────────────────────────────────────────────

@router.get("/api/trailers/{tt_id}/bom")
async def get_bom(tt_id: int, db: Session = Depends(get_db)):
    bom_rows = (db.query(BillOfMaterial)
                .filter_by(trailer_type_id=tt_id)
                .options(*_bom_load_options()).all())
    section_order = get_section_snapshot().order
    def _sec_key(r):
        name = r.bom_section or (r.material.category.name if r.material and r.material.category else "")
        return (section_order.get(name, 99998), name.lower(), r.sort_order)
    bom_rows.sort(key=_sec_key)
    result = []
    for row in bom_rows:
        mat = row.material
        if mat is None:
            # Orphaned row: material was deleted after the BOM was created.
            # Skip rather than crash — admin can clean up via the BOM editor.
            import logging as _log
            _log.getLogger("burtcost").warning(
                "get_bom: skipping BOM row id=%s (trailer %s) — material_id=%s not found",
                row.id, row.trailer_type_id, row.material_id,
            )
            continue
        category = row.bom_section or (mat.category.name if mat.category else "")
        if row.skin_formula_id and row.skin_formula:
            sf_region = row.skin_formula_region or "standard"
            effective_price = _compute_skin_formula_cost(row.skin_formula, sf_region)
        elif row.taping_block_id and row.taping_block:
            effective_price = _compute_taping_block_cost(row.taping_block)
        elif row.floor_plate_id and row.floor_plate:
            effective_price = _compute_floor_plate_cost(row.floor_plate)
        elif row.mounting_cleat_id and row.mounting_cleat:
            effective_price = _compute_mounting_cleat_cost(row.mounting_cleat)
        elif row.unit_price_override is not None:
            effective_price = row.unit_price_override
        else:
            effective_price = mat.price_per_unit
        result.append({
            "id": row.id, "material_id": mat.id, "material_name": mat.name,
            "category": category,
            "bom_section": row.bom_section or "",
            "unit": mat.unit_of_measure, "price": effective_price,
            "material_price": mat.price_per_unit,
            "unit_price_override": row.unit_price_override,
            "sap_code": mat.sap_code or "",
            "formula": row.formula_expression, "waste_pct": row.waste_percentage,
            "notes": row.notes or "", "sort_order": row.sort_order,
            "last_updated": mat.last_updated.isoformat() if mat.last_updated else None,
            "last_bulk_update_at":   mat.last_bulk_update_at.isoformat() if mat.last_bulk_update_at else None,
            "last_bulk_update_note": mat.last_bulk_update_note or "",
            "is_body_option":         bool(row.is_body_option),
            "selection_mode":         row.selection_mode or "always",
            "selection_group":        row.selection_group or "",
            "body_option_group":         row.body_option_group or "",
            "body_option_group_id":      row.body_option_group_id,
            "body_option_subgroup":      row.body_option_subgroup or "",
            "body_option_subgroup_id":   row.body_option_subgroup_id,
            "body_option_default":       bool(row.body_option_default),
            "calc2_default_excluded":    bool(row.calc2_default_excluded),
            "variable_value":            row.variable_value,
            "body_option_linked":        row.body_option_linked or "",
            "body_option_linked_id":     row.body_option_linked_id,
            "skin_formula_id":           row.skin_formula_id,
            "skin_formula_name":         row.skin_formula.name if row.skin_formula else None,
            "skin_formula_region":       row.skin_formula_region or "standard",
            "skin_formula_items":        [
                {
                    "ing_id":       item.ingredient.id,
                    "name":         item.ingredient.name,
                    "qty":          item.qty_per_m2,
                    "price_std":    item.ingredient.price_standard,
                    "price_kzn":    item.ingredient.price_kzn,
                    "price_source": getattr(item, "price_source", "standard") or "standard",
                    "price_sap":    (item.ingredient.sap_item.last_purch_price
                                     if item.ingredient.sap_item else None),
                }
                for item in row.skin_formula.items
                if item.ingredient
            ] if row.skin_formula else None,
            "taping_block_id":           row.taping_block_id,
            "taping_block_name":         row.taping_block.name if row.taping_block else None,
            "floor_plate_id":            row.floor_plate_id,
            "floor_plate_name":          row.floor_plate.name if row.floor_plate else None,
            "mounting_cleat_id":         row.mounting_cleat_id,
            "mounting_cleat_name":       row.mounting_cleat.name if row.mounting_cleat else None,
        })
    return result


@router.post("/api/trailers/{tt_id}/bom")
async def add_bom_item(tt_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    sect_name = body.get("bom_section", "") or ""
    if "sort_order" in body:
        sort_order = body["sort_order"]
    else:
        # Place after the last item in this section; if section is new, after all items
        max_in_sect = db.query(func.max(BillOfMaterial.sort_order)).filter_by(
            trailer_type_id=tt_id, bom_section=sect_name).scalar()
        if max_in_sect is not None:
            sort_order = max_in_sect + 1
        else:
            max_overall = db.query(func.max(BillOfMaterial.sort_order)).filter_by(
                trailer_type_id=tt_id).scalar()
            sort_order = (max_overall or 0) + 1
    bom = BillOfMaterial(
        trailer_type_id=tt_id,
        material_id=body["material_id"],
        formula_expression=body.get("formula_expression", "1"),
        waste_percentage=float(body.get("waste_percentage", 0)),
        notes=body.get("notes", ""),
        bom_section=sect_name,
        bom_section_id=_resolve_bom_section(db, sect_name),
        sort_order=sort_order,
    )
    db.add(bom)
    db.commit()
    db.refresh(bom)
    return {"id": bom.id}


@router.put("/api/bom/{bom_id}")
async def update_bom_item(bom_id: int, request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    # variable_value (insulation thickness in metres) AND unit_price_override
    # (per-row estimator price override) may be written by any logged-in user
    # (WO v4.37 §3.1 D-5 — restores GRP parity per CA3 §C.2: estimators persist
    # insulation thickness + per-row price overrides). All other BOM fields
    # (formula, group, section, material…) remain admin-only.
    if set(body.keys()) <= {"variable_value", "unit_price_override"}:
        require_user(request, db)
    else:
        require_admin(request, db)
    row = db.query(BillOfMaterial).filter_by(id=bom_id).first()
    if not row:
        raise HTTPException(status_code=404)
    for k in ["formula_expression", "waste_percentage", "notes", "sort_order", "material_id"]:
        if k in body:
            setattr(row, k, body[k])
    if "body_option_group" in body:
        grp_name = (body["body_option_group"] or "").upper() or None
        row.body_option_group = grp_name
        row.body_option_group_id = _resolve_body_option_group(db, grp_name) if grp_name else None
        row.body_option_subgroup_id = None
    if "body_option_subgroup" in body:
        sub_name = (body["body_option_subgroup"] or "").upper() or None
        row.body_option_subgroup = sub_name
        grp_id = row.body_option_group_id
        row.body_option_subgroup_id = _resolve_body_option_subgroup(db, grp_id, sub_name) if (grp_id and sub_name) else None
    if "bom_section" in body:
        row.bom_section = body["bom_section"]
        row.bom_section_id = _resolve_bom_section(db, body["bom_section"])
    if "body_option_linked" in body:
        linked_name = body["body_option_linked"] or None
        row.body_option_linked = linked_name
        if linked_name:
            lm = db.query(Material).filter_by(name=linked_name).first()
            row.body_option_linked_id = lm.id if lm else None
        else:
            row.body_option_linked_id = None
    if "body_option_linked_id" in body:
        row.body_option_linked_id = body["body_option_linked_id"] or None
    if "is_body_option" in body:
        row.is_body_option = bool(body["is_body_option"])
    if "calc2_default_excluded" in body:
        row.calc2_default_excluded = bool(body["calc2_default_excluded"])
    if "variable_value" in body:
        v = body["variable_value"]
        row.variable_value = float(v) if v is not None and v != "" else None
    if "unit_price_override" in body:
        v = body["unit_price_override"]
        row.unit_price_override = float(v) if v is not None and v != "" else None
    if "skin_formula_id" in body:
        row.skin_formula_id = int(body["skin_formula_id"]) if body["skin_formula_id"] else None
    if "skin_formula_region" in body:
        row.skin_formula_region = body["skin_formula_region"] or "standard"
    if "taping_block_id" in body:
        row.taping_block_id = int(body["taping_block_id"]) if body["taping_block_id"] else None
    if "floor_plate_id" in body:
        row.floor_plate_id = int(body["floor_plate_id"]) if body["floor_plate_id"] else None
    if "mounting_cleat_id" in body:
        row.mounting_cleat_id = int(body["mounting_cleat_id"]) if body["mounting_cleat_id"] else None
    db.commit()
    return {"ok": True}


@router.post("/api/bom/{bom_id}/duplicate")
async def duplicate_bom_item(bom_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    row = db.query(BillOfMaterial).filter_by(id=bom_id).first()
    if not row:
        raise HTTPException(status_code=404)
    mat = row.material
    if not mat:
        raise HTTPException(status_code=400, detail="BOM item has no linked material")
    new_mat = Material(
        name=mat.name + "_copy",
        category_id=mat.category_id,
        unit_of_measure=mat.unit_of_measure,
        price_per_unit=mat.price_per_unit,
        supplier=mat.supplier,
        material_code=mat.material_code,
        sap_code=mat.sap_code,
        size=mat.size,
        is_active=True,
        last_updated=datetime.now(timezone.utc),
    )
    db.add(new_mat)
    db.flush()
    new_bom = BillOfMaterial(
        trailer_type_id=row.trailer_type_id,
        material_id=new_mat.id,
        formula_expression=row.formula_expression,
        waste_percentage=row.waste_percentage,
        notes=row.notes,
        bom_section=row.bom_section,
        bom_section_id=row.bom_section_id,
        sort_order=(row.sort_order or 0) + 1,
        skin_formula_id=row.skin_formula_id,
        skin_formula_region=row.skin_formula_region,
        taping_block_id=row.taping_block_id,
        floor_plate_id=row.floor_plate_id,
        mounting_cleat_id=row.mounting_cleat_id,
    )
    db.add(new_bom)
    db.commit()
    db.refresh(new_bom)
    return {"bom_id": new_bom.id, "material_id": new_mat.id, "material_name": new_mat.name}


CROSS_BODY_TYPE_COPY_NAMES = {
    "ALU EXTRUTION FLOOR",
    "RICE GRAIN ALU FLOOR",
    "1ST ROW ALU KICK PLATE",
    "2ND ROW ALU KICK PLATE",
}


@router.get("/api/bom/cross-body-copy-names")
async def list_cross_body_copy_names():
    return {"names": sorted(CROSS_BODY_TYPE_COPY_NAMES)}


@router.post("/api/bom/{bom_id}/copy-to-trailer")
async def copy_bom_to_trailer(bom_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    target_tt_id = body.get("target_tt_id")
    if not target_tt_id:
        raise HTTPException(status_code=400, detail="target_tt_id required")

    src = db.query(BillOfMaterial).filter_by(id=bom_id).first()
    if not src:
        raise HTTPException(status_code=404, detail="Source BOM item not found")
    src_mat = src.material
    if not src_mat:
        raise HTTPException(status_code=400, detail="Source BOM item has no linked material")
    src_name_norm = (src_mat.name or "").strip().upper()
    if src_name_norm not in CROSS_BODY_TYPE_COPY_NAMES:
        raise HTTPException(status_code=400,
            detail=f'"{src_mat.name}" is not eligible for cross-body-type copy')

    target = db.query(TrailerType).filter_by(id=int(target_tt_id)).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target trailer type not found")
    if target.id == src.trailer_type_id:
        raise HTTPException(status_code=400, detail="Source and target trailer are the same")

    existing = (db.query(BillOfMaterial)
                .join(Material, BillOfMaterial.material_id == Material.id)
                .filter(BillOfMaterial.trailer_type_id == target.id)
                .filter(func.upper(func.trim(Material.name)) == src_name_norm)
                .first())
    if existing:
        raise HTTPException(status_code=409,
            detail=f'"{src_mat.name}" already exists in "{target.name}"')

    new_mat = Material(
        name=src_mat.name,
        category_id=src_mat.category_id,
        unit_of_measure=src_mat.unit_of_measure,
        price_per_unit=src_mat.price_per_unit,
        supplier=src_mat.supplier,
        material_code=src_mat.material_code,
        sap_code=src_mat.sap_code,
        size=src_mat.size,
        is_active=True,
        last_updated=datetime.now(timezone.utc),
    )
    db.add(new_mat)
    db.flush()

    max_in_sect = db.query(func.max(BillOfMaterial.sort_order)).filter_by(
        trailer_type_id=target.id, bom_section=src.bom_section).scalar()
    if max_in_sect is None:
        max_in_sect = db.query(func.max(BillOfMaterial.sort_order)).filter_by(
            trailer_type_id=target.id).scalar()
    sort_order = (max_in_sect or 0) + 1

    new_bom = BillOfMaterial(
        trailer_type_id=target.id,
        material_id=new_mat.id,
        formula_expression=src.formula_expression,
        waste_percentage=src.waste_percentage,
        notes=src.notes,
        bom_section=src.bom_section,
        bom_section_id=src.bom_section_id,
        sort_order=sort_order,
        is_body_option=src.is_body_option,
        body_option_group=src.body_option_group,
        body_option_group_id=src.body_option_group_id,
        body_option_subgroup=src.body_option_subgroup,
        body_option_subgroup_id=src.body_option_subgroup_id,
        body_option_default=src.body_option_default,
        body_option_linked=src.body_option_linked,
        body_option_linked_id=src.body_option_linked_id,
        variable_value=src.variable_value,
        unit_price_override=src.unit_price_override,
        skin_formula_id=src.skin_formula_id,
        skin_formula_region=src.skin_formula_region,
        taping_block_id=src.taping_block_id,
        floor_plate_id=src.floor_plate_id,
        mounting_cleat_id=src.mounting_cleat_id,
    )
    db.add(new_bom)
    db.commit()
    db.refresh(new_bom)
    return {
        "bom_id": new_bom.id,
        "material_id": new_mat.id,
        "material_name": new_mat.name,
        "target_tt_id": target.id,
        "target_name": target.name,
    }


@router.delete("/api/bom/{bom_id}")
async def delete_bom_item(bom_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    row = db.query(BillOfMaterial).filter_by(id=bom_id).first()
    if row:
        db.delete(row)
        db.commit()
    return {"ok": True}


@router.post("/api/bom/bulk-delete")
async def bulk_delete_bom_items(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    ids = [int(i) for i in body.get("ids", [])]
    if ids:
        db.query(BillOfMaterial).filter(BillOfMaterial.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
    return {"ok": True, "deleted": len(ids)}


@router.post("/api/bom/bulk-calc2-default")
async def bulk_set_calc2_default(request: Request, db: Session = Depends(get_db)):
    """Set calc2_default_excluded on multiple BOM rows at once — used by the
    Body Templates section-header 'exclude from Calculator 2' checkbox."""
    require_admin(request, db)
    body = await request.json()
    ids = [int(i) for i in body.get("ids", [])]
    excluded = bool(body.get("excluded", False))
    if ids:
        db.query(BillOfMaterial).filter(BillOfMaterial.id.in_(ids)).update(
            {BillOfMaterial.calc2_default_excluded: excluded},
            synchronize_session=False,
        )
        db.commit()
    return {"ok": True, "updated": len(ids)}


# ─── BOM Sections ─────────────────────────────────────────────────────────────

@router.post("/api/trailers/{tt_id}/bom/link-section-to-option")
async def link_section_to_body_option(tt_id: int, request: Request, db: Session = Depends(get_db)):
    """Link every regular item in a BOM section to a body option in one shot.

    Either pick an existing body option on this trailer (by its bom row id)
    or create a new one. Items already linked to a *different* body option
    are skipped (returned in the response so the caller can show them).

    Body:
        section            (str, required)  — source section name on this trailer
        existing_option_id (int, optional)  — existing body option's BOM row id
        new_option         (obj, optional)  — when creating one:
            name             (str)  default: section name
            default_selected (bool) default: True
            group            (str)  default: section name
    """
    require_admin(request, db)
    body = await request.json()
    section = (body.get("section") or "").strip()
    if not section:
        raise HTTPException(status_code=400, detail="section is required")

    tt = db.query(TrailerType).filter_by(id=tt_id).first()
    if not tt:
        raise HTTPException(status_code=404, detail="Trailer type not found")

    existing_id = body.get("existing_option_id")
    new_spec = body.get("new_option")
    if not existing_id and not new_spec:
        raise HTTPException(status_code=400,
            detail="Provide existing_option_id or new_option")
    if existing_id and new_spec:
        raise HTTPException(status_code=400,
            detail="Provide either existing_option_id or new_option, not both")

    # Resolve / create the body option row
    if existing_id:
        opt_row = (db.query(BillOfMaterial)
                   .filter_by(id=int(existing_id), trailer_type_id=tt_id, is_body_option=True)
                   .first())
        if not opt_row:
            raise HTTPException(status_code=404,
                detail=f"Body option id {existing_id} not found on this trailer")
        opt_material = db.query(Material).filter_by(id=opt_row.material_id).first()
        if not opt_material:
            raise HTTPException(status_code=500,
                detail=f"Body option {existing_id} has no material")
        option_name = opt_material.name
    else:
        from datetime import datetime, timezone
        opt_name_raw = (new_spec.get("name") or section).strip()
        if not opt_name_raw:
            raise HTTPException(status_code=400, detail="new_option.name cannot be empty")
        opt_name = opt_name_raw  # keep user's casing in Material; group is upper-cased separately

        # Refuse if a body option with this name already exists on the trailer
        clash = (db.query(BillOfMaterial)
                 .join(Material, Material.id == BillOfMaterial.material_id)
                 .filter(BillOfMaterial.trailer_type_id == tt_id,
                         BillOfMaterial.is_body_option == True,
                         Material.name == opt_name)
                 .first())
        if clash:
            raise HTTPException(status_code=409,
                detail=f"A body option named {opt_name!r} already exists on this trailer "
                       f"(bom_id={clash.id}). Pick it from the existing list instead.")

        # Re-use a Material with this name if one already exists, otherwise create
        opt_material = db.query(Material).filter_by(name=opt_name).first()
        if not opt_material:
            cat = (db.query(MaterialCategory)
                   .filter_by(name="Body Options").first())
            if not cat:
                cat = MaterialCategory(name="Body Options")
                db.add(cat); db.flush()
            opt_material = Material(
                name=opt_name,
                category_id=cat.id,
                price_per_unit=0.0,
                unit_of_measure="ea",
                is_active=True,
                last_updated=datetime.now(timezone.utc),
            )
            db.add(opt_material); db.flush()

        grp_name_raw = (new_spec.get("group") or section).strip().upper() or None
        grp_id = _resolve_body_option_group(db, grp_name_raw) if grp_name_raw else None

        body_opt_sec_id = _resolve_bom_section(db, "BODY OPTIONS")
        max_sort = (db.query(func.max(BillOfMaterial.sort_order))
                    .filter_by(trailer_type_id=tt_id, bom_section="BODY OPTIONS")
                    .scalar() or 0)
        opt_row = BillOfMaterial(
            trailer_type_id=tt_id,
            material_id=opt_material.id,
            formula_expression="1",
            waste_percentage=0,
            bom_section="BODY OPTIONS",
            bom_section_id=body_opt_sec_id,
            is_body_option=True,
            body_option_group=grp_name_raw,
            body_option_group_id=grp_id,
            body_option_default=bool(new_spec.get("default_selected", True)),
            sort_order=max_sort + 1,
        )
        db.add(opt_row); db.flush()
        option_name = opt_material.name

    # Now link every item in the source section. Items that are body options
    # themselves, or already linked to a different option, are skipped.
    section_rows = (db.query(BillOfMaterial)
                    .filter(BillOfMaterial.trailer_type_id == tt_id,
                            BillOfMaterial.bom_section == section)
                    .all())
    if not section_rows:
        raise HTTPException(status_code=400,
            detail=f"Section {section!r} has no rows on this trailer")

    linked = 0
    skipped: list[dict] = []
    for r in section_rows:
        if r.id == opt_row.id:
            continue   # don't link the option to itself
        if r.is_body_option:
            mat = db.query(Material).filter_by(id=r.material_id).first()
            skipped.append({"id": r.id, "name": mat.name if mat else "?",
                            "reason": "row is itself a body option"})
            continue
        existing_link = r.body_option_linked or ""
        if existing_link and existing_link != option_name:
            mat = db.query(Material).filter_by(id=r.material_id).first()
            skipped.append({"id": r.id, "name": mat.name if mat else "?",
                            "reason": f"already linked to {existing_link!r}"})
            continue
        r.body_option_linked = option_name
        r.body_option_linked_id = opt_material.id
        linked += 1

    db.commit()
    return {
        "linked":  linked,
        "skipped": skipped,
        "option":  {"id": opt_row.id, "name": option_name,
                    "is_new": not bool(existing_id)},
    }


@router.get("/api/bom-sections")
async def list_bom_sections(db: Session = Depends(get_db)):
    rows = db.query(BOMSection).order_by(BOMSection.sort_order, BOMSection.name).all()
    return [{"id": r.id, "name": r.name, "multiplier": r.multiplier or 1.0,
             "is_optional": bool(r.is_optional)} for r in rows]


@router.post("/api/bom-sections")
async def create_bom_section(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Section name required")
    existing = db.query(BOMSection).filter_by(name=name).first()
    if existing:
        return {"id": existing.id, "name": existing.name,
                "multiplier": existing.multiplier or 1.0,
                "is_optional": bool(existing.is_optional), "created": False}
    last = db.query(BOMSection).order_by(BOMSection.sort_order.desc()).first()
    sort_order = (last.sort_order + 1) if last else 0
    row = BOMSection(name=name, sort_order=sort_order,
                     multiplier=float(body.get("multiplier") or 1.0),
                     is_optional=bool(body.get("is_optional", False)))
    db.add(row)
    db.commit()
    return {"id": row.id, "name": row.name,
            "multiplier": row.multiplier or 1.0,
            "is_optional": bool(row.is_optional), "created": True}


@router.put("/api/bom-sections/{section_id}")
async def update_bom_section(section_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    row = db.query(BOMSection).filter_by(id=section_id).first()
    if not row:
        raise HTTPException(status_code=404)
    if "multiplier" in body:
        row.multiplier = max(0.0, float(body["multiplier"]))
    if "is_optional" in body:
        row.is_optional = bool(body["is_optional"])
    if "name" in body:
        new_name = (body.get("name") or "").strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="Name cannot be empty")
        if new_name != row.name:
            existing = db.query(BOMSection).filter(BOMSection.name == new_name, BOMSection.id != section_id).first()
            if existing:
                raise HTTPException(status_code=400, detail=f"A section named '{new_name}' already exists")
            old_name = row.name
            row.name = new_name
            # Cascade to bill_of_materials.bom_section (string fallback column)
            db.query(BillOfMaterial).filter(BillOfMaterial.bom_section == old_name).update(
                {"bom_section": new_name}, synchronize_session=False
            )
    db.commit()
    return {"ok": True, "name": row.name, "multiplier": row.multiplier,
            "is_optional": bool(row.is_optional)}


# ─── Body Option Groups ───────────────────────────────────────────────────────

@router.post("/api/bom/bulk-selection-mode")
async def bulk_set_selection_mode(request: Request, db: Session = Depends(get_db)):
    """Set selection_mode (and selection_group) on multiple BOM rows in one
    shot. Writes through to the legacy is_body_option / body_option_subgroup
    fields so the calculator engine continues to work unchanged.

    Body:
        ids:             list[int]   — BOM row ids
        mode:            str         — 'always' | 'single' | 'multi'
        selection_group: str | null  — required when mode='single'

    For mode='single' the choice group string is also written to
    body_option_subgroup so the existing radio-cluster logic at
    calculator.js:1784 ("its.length>1 && !!sub" → radio) kicks in.
    """
    require_admin(request, db)
    body = await request.json()
    ids = body.get("ids") or []
    mode = (body.get("mode") or "").strip().lower()
    selection_group = (body.get("selection_group") or "").strip() or None

    if not ids:
        raise HTTPException(status_code=400, detail="ids is required")
    if mode not in ("always", "single", "multi"):
        raise HTTPException(status_code=400,
            detail=f"mode must be one of always|single|multi (got {mode!r})")
    if mode == "single" and not selection_group:
        raise HTTPException(status_code=400,
            detail="selection_group is required when mode='single'")

    rows = (db.query(BillOfMaterial)
            .filter(BillOfMaterial.id.in_(ids))
            .all())
    if not rows:
        raise HTTPException(status_code=404, detail="No matching BOM rows")

    updated = 0
    for r in rows:
        # Save the per-item Inclusion mode + group on the new columns
        r.selection_mode = mode
        r.selection_group = selection_group if mode == "single" else None
        # Mirror to legacy fields so the calculator engine sees the change
        if mode == "always":
            r.is_body_option = False
            r.body_option_subgroup = None
            r.body_option_subgroup_id = None
        else:
            # Either 'single' or 'multi' — both flip the row to a body option.
            r.is_body_option = True
            r.body_option_linked = None      # an option doesn't link to one
            r.body_option_linked_id = None
            # Default body_option_group to the row's BOM section so the
            # row doesn't fall into the synthetic "MISC" bucket on the
            # calculator. Existing values are left alone.
            if not (r.body_option_group or "").strip():
                grp_name = (r.bom_section or "").strip().upper() or None
                if grp_name:
                    r.body_option_group = grp_name
                    r.body_option_group_id = _resolve_body_option_group(db, grp_name)
            if mode == "single":
                r.body_option_subgroup = selection_group
                grp_id = r.body_option_group_id
                r.body_option_subgroup_id = (
                    _resolve_body_option_subgroup(db, grp_id, selection_group)
                    if grp_id and selection_group else None
                )
            else:  # multi
                r.body_option_subgroup = None
                r.body_option_subgroup_id = None
        updated += 1

    db.commit()
    return {"updated": updated, "mode": mode, "selection_group": selection_group}


@router.post("/api/trailers/{tt_id}/body-option-groups/rename")
async def rename_body_option_group(tt_id: int, request: Request, db: Session = Depends(get_db)):
    """Rename a body-option group on this trailer only.

    Updates body_option_group + body_option_group_id on every BOM row of
    this trailer that currently carries old_name. The canonical
    body_option_groups record for old_name is left intact (other trailers
    may still use it). The new name is upper-cased to match how
    _resolve_body_option_group stores it.

    Body: {"old_name": str, "new_name": str}
    """
    require_admin(request, db)
    body = await request.json()
    # old_name may be "" (or absent) when the user is renaming the
    # synthetic 'MISC' placeholder group — those rows have body_option_group
    # IS NULL or '' in the DB. Match accordingly.
    old_name_raw = body.get("old_name")
    old_name = (old_name_raw or "").strip()
    new_name = (body.get("new_name") or "").strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="new_name is required")
    new_name_norm = new_name.upper()
    if old_name and new_name_norm == old_name.upper():
        return {"updated": 0, "new_name": new_name_norm, "no_change": True}

    new_group_id = _resolve_body_option_group(db, new_name_norm)

    # Scope the rename to body-option rows only — regular BOM rows with no
    # group are NOT in the synthetic 'MISC' placeholder; they just don't
    # carry a group at all. Without this filter, renaming 'MISC' would
    # spread a group onto every group-less row in the BOM.
    q = (db.query(BillOfMaterial)
         .filter(BillOfMaterial.trailer_type_id == tt_id,
                 BillOfMaterial.is_body_option == True))
    if old_name:
        q = q.filter(BillOfMaterial.body_option_group == old_name)
    else:
        # Placeholder 'MISC' rename — match NULL or empty string
        from sqlalchemy import or_
        q = q.filter(or_(BillOfMaterial.body_option_group.is_(None),
                         BillOfMaterial.body_option_group == ""))
    rows = q.all()
    if not rows:
        label = old_name or "(no group set)"
        raise HTTPException(status_code=404,
            detail=f"No BOM rows on trailer {tt_id} use group {label!r}")

    updated = 0
    for r in rows:
        r.body_option_group = new_name_norm
        r.body_option_group_id = new_group_id
        # Re-resolve the subgroup under the new group so the FK stays valid
        if r.body_option_subgroup:
            r.body_option_subgroup_id = _resolve_body_option_subgroup(
                db, new_group_id, r.body_option_subgroup
            )
        updated += 1
    db.commit()
    return {"updated": updated, "new_name": new_name_norm,
            "new_group_id": new_group_id, "no_change": False}


@router.get("/api/body-option-groups")
async def list_body_option_groups(db: Session = Depends(get_db)):
    rows = (db.query(BodyOptionGroup)
            .order_by(BodyOptionGroup.sort_order, BodyOptionGroup.name).all())
    result = []
    for g in rows:
        subs = (db.query(BodyOptionSubgroup)
                .filter_by(group_id=g.id)
                .order_by(BodyOptionSubgroup.sort_order, BodyOptionSubgroup.name).all())
        result.append({
            "id": g.id, "name": g.name,
            "bom_section_id":   g.bom_section_id,
            "bom_section_name": g.bom_section.name if g.bom_section else None,
            "subgroups": [{"id": s.id, "name": s.name} for s in subs],
        })
    return result


# ─── Trailer Ratios ───────────────────────────────────────────────────────────

def _ratio_display_label(value: float) -> str:
    """Always show ratios as percentages — drops trailing zeros (55%, 57.5%)."""
    pct = round(value * 100, 1)
    return f"{int(pct)}%" if pct == int(pct) else f"{pct}%"


@router.get("/api/trailers/{tt_id}/ratios")
async def get_ratios(tt_id: int, db: Session = Depends(get_db)):
    rows = db.query(TrailerRatio).filter_by(trailer_type_id=tt_id).order_by(TrailerRatio.sort_order).all()
    return [{"id": r.id, "ratio_value": r.ratio_value,
             "label": _ratio_display_label(r.ratio_value),
             "sort_order": r.sort_order} for r in rows]


@router.post("/api/trailers/{tt_id}/ratios")
async def create_ratio(tt_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    ratio_value = float(body.get("ratio_value", 0))
    if not (0 < ratio_value <= 1):
        raise HTTPException(status_code=400, detail="ratio_value must be between 0 and 1")
    existing = db.query(TrailerRatio).filter_by(trailer_type_id=tt_id, ratio_value=ratio_value).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Ratio {ratio_value} already exists for this trailer")
    last = db.query(TrailerRatio).filter_by(trailer_type_id=tt_id).count()
    r = TrailerRatio(trailer_type_id=tt_id, ratio_value=ratio_value,
                     label=body.get("label") or f"{round(ratio_value*100,1)}%",
                     sort_order=last)
    db.add(r)
    db.commit()
    db.refresh(r)
    return {"id": r.id, "ratio_value": r.ratio_value, "label": r.label}


@router.put("/api/ratios/{ratio_id}")
async def update_ratio(ratio_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    r = db.query(TrailerRatio).filter_by(id=ratio_id).first()
    if not r:
        raise HTTPException(status_code=404)
    if "ratio_value" in body:
        r.ratio_value = float(body["ratio_value"])
    if "label" in body:
        r.label = body["label"]
    db.commit()
    return {"ok": True}


@router.delete("/api/ratios/{ratio_id}")
async def delete_ratio(ratio_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    r = db.query(TrailerRatio).filter_by(id=ratio_id).first()
    if r:
        db.delete(r)
        db.commit()
    return {"ok": True}


# ─── Admin Pages ─────────────────────────────────────────────────────────────

@router.get("/admin/templates", response_class=HTMLResponse)
async def admin_templates(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login")
    if not user_can(user, "menu.body_templates", db):
        raise HTTPException(status_code=403, detail="Not authorized")
    trailers = db.query(TrailerType).filter_by(is_active=True).order_by(TrailerType.name).all()
    categories = db.query(MaterialCategory).order_by(MaterialCategory.name).all()
    trailer_list = [{"id": t.id, "name": t.name} for t in trailers]
    return templates.TemplateResponse("admin_templates.html", {
        "request": request, "user": user,
        "trailers": trailer_list, "categories": categories,
    })


@router.get("/admin/formulas", response_class=HTMLResponse)
async def admin_formulas(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or user.role != "admin":
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin_formulas.html", {
        "request": request, "user": user,
    })


@router.get("/admin/configurator-preview", response_class=HTMLResponse)
async def admin_configurator_preview(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or user.role != "admin":
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("admin_configurator_preview.html", {
        "request": request, "user": user,
    })


@router.get("/admin/settings", response_class=HTMLResponse)
async def admin_visual_configurator_settings(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or user.role != "admin":
        return RedirectResponse(url="/login")
    trailers = db.query(TrailerType).filter_by(is_active=True).order_by(TrailerType.name).all()
    return templates.TemplateResponse("admin_visual_configurator_settings.html", {
        "request": request,
        "user": user,
        "trailers": [{"id": t.id, "name": t.name} for t in trailers],
    })


@router.get("/api/admin/settings/body-types/{trailer_id}/categories")
async def admin_visual_configurator_categories(
    trailer_id: int, request: Request, db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user or user.role != "admin":
        raise HTTPException(status_code=401, detail="Admin only")
    trailer = db.query(TrailerType).filter_by(id=trailer_id, is_active=True).first()
    if not trailer:
        raise HTTPException(status_code=404, detail="Trailer not found")

    rows = (
        db.query(BillOfMaterial)
        .outerjoin(BOMSection, BillOfMaterial.bom_section_id == BOMSection.id)
        .options(*_bom_load_options())
        .filter(
            BillOfMaterial.trailer_type_id == trailer_id,
            BillOfMaterial.is_body_option == False,
        )
        .order_by(
            func.coalesce(BOMSection.sort_order, 999999),
            BillOfMaterial.sort_order,
            BillOfMaterial.id,
        )
        .all()
    )

    categories_by_key: dict[str, dict] = {}
    ordered_keys: list[str] = []
    for row in rows:
        name = (row.bom_section or (row.section.name if row.section else "")).strip()
        if not name or name.upper() == "BODY OPTIONS":
            continue
        key = name.upper()
        if key not in categories_by_key:
            categories_by_key[key] = {
                "id": row.bom_section_id or key,
                "key": key,
                "name": name,
                "sort_order": int(getattr(row.section, "sort_order", 0) or 0),
                "multiplier": float(getattr(row.section, "multiplier", 1.0) or 1.0),
                "items": [],
            }
            ordered_keys.append(key)

        if row.material and getattr(row.material, "name", None):
            item_name = row.material.name
            sap_code = row.material.sap_code or ""
        elif row.linked_material and getattr(row.linked_material, "name", None):
            item_name = row.linked_material.name
            sap_code = row.linked_material.sap_code or ""
        elif row.skin_formula and getattr(row.skin_formula, "name", None):
            item_name = row.skin_formula.name
            sap_code = ""
        elif row.taping_block and getattr(row.taping_block, "name", None):
            item_name = row.taping_block.name
            sap_code = ""
        elif row.floor_plate and getattr(row.floor_plate, "name", None):
            item_name = row.floor_plate.name
            sap_code = ""
        elif row.mounting_cleat and getattr(row.mounting_cleat, "name", None):
            item_name = row.mounting_cleat.name
            sap_code = ""
        else:
            item_name = (row.notes or f"BOM item {row.id}").strip()
            sap_code = ""

        conds = []
        cond_mode = "include"
        raw = row.bom_conditions
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    conds = [
                        {"option": str(c.get("option", "")), "equals": str(c.get("equals", "Y")).upper()}
                        for c in parsed
                        if isinstance(c, dict) and c.get("option")
                    ]
                elif isinstance(parsed, dict):
                    raw_mode = (parsed.get("mode") or "include").lower()
                    if raw_mode == "always_exclude":
                        cond_mode = "always_exclude"
                    elif raw_mode == "exclude":
                        cond_mode = "exclude"
                    conds = [
                        {"option": str(c.get("option", "")), "equals": str(c.get("equals", "Y")).upper()}
                        for c in (parsed.get("all") or [])
                        if isinstance(c, dict) and c.get("option")
                    ]
            except (ValueError, TypeError):
                pass

        categories_by_key[key]["items"].append({
            "id": row.id,
            "name": item_name,
            "sapCode": sap_code,
            "unitPrice": round(_bom_item_unit_price(row), 4),
            "sortOrder": int(row.sort_order or 0),
            "conditions": conds,
            "conditionMode": cond_mode,
        })

    categories = []
    for key in ordered_keys:
        category = categories_by_key[key]
        category["itemCount"] = len(category["items"])
        categories.append(category)

    body_option_rows = (
        db.query(BillOfMaterial)
        .options(*_bom_load_options())
        .filter(
            BillOfMaterial.trailer_type_id == trailer_id,
            BillOfMaterial.is_body_option == True,
        )
        .order_by(BillOfMaterial.sort_order, BillOfMaterial.id)
        .all()
    )
    body_options = []
    seen_body_options: set[str] = set()
    for row in body_option_rows:
        option_name = ""
        if row.material and getattr(row.material, "name", None):
            option_name = row.material.name.strip()
        if not option_name:
            continue
        option_key = option_name.upper()
        if option_key in seen_body_options:
            continue
        seen_body_options.add(option_key)
        body_options.append({
            "id": row.id,
            "name": option_name,
            "group": row.body_option_group or "",
            "section": row.bom_section or "",
            "selectionMode": row.selection_mode or "always",
        })

    return {
        "trailerId": trailer.id,
        "trailerName": trailer.name,
        "categories": categories,
        "bodyOptions": body_options,
    }


# ─── Configurator (read-only Phase 1) ─────────────────────────────────────────
# Maps existing schema (trailer_types + body option groups/subgroups + bom_sections
# + bom rows) into the tree shape the configurator UI expects. Lives here so the
# mockup can fetch real data for any trailer instead of using a hardcoded SAMPLE.

_DOOR_TYPE_OPTIONS = ("DRD", "SRD")


def _bom_item_name(row: BillOfMaterial) -> str:
    if row.material and getattr(row.material, "name", None):
        return row.material.name
    return row.linked_material or "(unnamed)"


def _bom_item_unit_price(row: BillOfMaterial) -> float:
    val = row.unit_price_override
    if val is None:
        val = row.unit_price_snapshot
    if val is None and row.material is not None:
        val = getattr(row.material, "current_price", None)
    return float(val or 0)


def _build_configurator_tree(db: Session, trailer: TrailerType) -> dict:
    rows = (
        db.query(BillOfMaterial)
        .filter_by(trailer_type_id=trailer.id)
        .order_by(BillOfMaterial.sort_order, BillOfMaterial.id)
        .all()
    )
    masters = [r for r in rows if r.is_body_option]
    items = [r for r in rows if not r.is_body_option]

    # Resolve cross-trailer body_option_master_id FKs to the local trailer's
    # equivalent master row. Section.body_option_master_id can point to a master
    # on a different trailer (sections are global; the FK was set during another
    # trailer's configurator save). The frontend needs the LOCAL master id so
    # that radio clicks toggle a master row that actually exists on this trailer.
    master_ids_set = {m.id for m in masters}
    _local_master_by_name: dict[str, int] = {}
    for r in masters:
        if r.material and r.material.name:
            _local_master_by_name.setdefault(r.material.name, r.id)

    def _resolve_local_master(fk_id: int | None) -> int | None:
        if fk_id is None:
            return None
        if fk_id in master_ids_set:
            return fk_id  # already local
        m = db.query(BillOfMaterial).filter_by(id=fk_id).first()
        if not m or not m.material or not m.material.name:
            return None
        return _local_master_by_name.get(m.material.name)

    sec_ids = {r.bom_section_id for r in items if r.bom_section_id}
    # Also include empty sections owned by one of this trailer's masters via
    # body_option_master_id (newly created sections won't have items yet, but
    # the configurator should still show them under their owning option).
    master_ids = {m.id for m in masters}
    owned_empty = (
        db.query(BOMSection)
        .filter(BOMSection.body_option_master_id.in_(master_ids))
        .all()
        if master_ids else []
    )
    sec_ids.update(s.id for s in owned_empty)
    all_sections = (
        db.query(BOMSection).filter(BOMSection.id.in_(sec_ids)).all() if sec_ids else []
    )
    # 'sections' = live ones (Unassigned tray sections excluded from the gate/always
    # layout). Tray sections are emitted in their own bucket at the end.
    sections = {s.id: s for s in all_sections if s.archived_at is None}
    archived_sections = [s for s in all_sections if s.archived_at is not None]

    # Pre-compute section-bound flag masters so fmt_section can reference them.
    # A flag master with bom_section_id set is "moved into" that section and
    # renders under it instead of in its body_option_group bucket.
    #
    # IMPORTANT: only treat a master as section-bound if the section it
    # points at is actually rendered in this tree (i.e. lives in `sections`).
    # The legacy "BODY OPTIONS" import bucket section has many flag masters
    # pointing at it as default — those are NOT user moves; they're legacy
    # data and must continue to render in their flag group.
    section_bound_flags: dict[int, list[BillOfMaterial]] = {}
    for _m in masters:
        sid = _m.bom_section_id
        if sid is not None and sid in sections:
            section_bound_flags.setdefault(sid, []).append(_m)

    def fmt_item(r: BillOfMaterial) -> dict:
        # Phase 2: per-item AND-conditions live in bom_conditions (JSON text).
        # Two accepted shapes:
        #   1. Legacy list (implicit mode='include'): [{"option","equals"}, ...]
        #   2. Object form: {"mode":"include"|"exclude", "all":[{"option","equals"},...]}
        conds = []
        mode = "include"
        raw = r.bom_conditions
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    items = parsed
                elif isinstance(parsed, dict):
                    items = parsed.get("all") or []
                    raw_mode = parsed.get("mode")
                    if raw_mode == "exclude":
                        mode = "exclude"
                    elif raw_mode == "always_exclude":
                        mode = "always_exclude"
                else:
                    items = []
                conds = [
                    {"option": str(c.get("option", "")), "equals": str(c.get("equals", "Y")).upper()}
                    for c in items
                    if isinstance(c, dict) and c.get("option")
                ]
            except (ValueError, TypeError):
                pass
        return {
            "id": r.id,
            "name": _bom_item_name(r),
            "qty": r.formula_expression or "",
            "unitPrice": _bom_item_unit_price(r),
            "conditions": conds,
            "conditionMode": mode,
        }

    def fmt_section(sec: BOMSection, owning_master_id: int | None = None) -> dict:
        sec_items = [fmt_item(r) for r in items if r.bom_section_id == sec.id]
        # Determine the owner master id we ship to the client. Priority:
        #   1. Explicit owning_master_id passed by an option context (already local).
        #   2. The section's stored FK, RESOLVED to the local trailer's equivalent
        #      master by material-name match. Sections are global, so the stored
        #      FK can legitimately point at a master on another trailer; the UI
        #      needs the local id to toggle a master that actually exists here.
        resolved_owner = (
            owning_master_id if owning_master_id is not None
            else _resolve_local_master(sec.body_option_master_id)
        )
        return {
            "id": f"s{sec.id}",
            "name": sec.name,
            "items": sec_items,
            "bodyOptionMasterId": resolved_owner,
            # Flag masters that were moved into this section render here as
            # checkbox/radio rows under the section in the UI.
            "flags": [
                {
                    "id": f"flag-m{m.id}",
                    "name": _bom_item_name(m),
                    "style": "radio" if (m.selection_mode or "").lower() == "single" else "tick",
                }
                for m in section_bound_flags.get(sec.id, [])
            ],
        }

    # Track which sections are "claimed" by a master (rendered under Door type), so
    # they don't double up in Always-include.
    claimed_section_ids: set[int] = set()

    def sections_for_master(master: BillOfMaterial, legacy_prefix: str | None = None) -> list[BOMSection]:
        """Sections owned by this master.

        Priority order:
          1. New explicit ownership: BOMSection.body_option_master_id == master.id
             (set by the Phase 2 move-section endpoint).
          2. Legacy name-prefix fallback: any section whose name equals the prefix
             or starts with "<prefix> " (e.g. DRD → DRD, DRD DOOR FITTINGS).

        Sections claimed by step 1 are also matched even if their name doesn't share
        the prefix — that's the whole point of the new column.
        """
        out: list[BOMSection] = []
        for sid, sec in sections.items():
            if sid in claimed_section_ids:
                continue
            if sec.body_option_master_id == master.id:
                out.append(sec)
                claimed_section_ids.add(sid)
                continue
            if legacy_prefix:
                n = (sec.name or "").upper().strip()
                if n == legacy_prefix or n.startswith(legacy_prefix + " "):
                    out.append(sec)
                    claimed_section_ids.add(sid)
        # Stable order: bare prefix (or master name) first, then alpha.
        canonical = (legacy_prefix or _bom_item_name(master).upper()).strip()
        out.sort(key=lambda s: (0 if s.name.upper().strip() == canonical else 1, s.name))
        return out

    # Backwards-compatible alias for older call sites that still pass just the prefix.
    def sections_with_prefix(prefix: str) -> list[BOMSection]:
        # No master object available — fall back to pure prefix matching.
        out = []
        for sid, sec in sections.items():
            if sid in claimed_section_ids:
                continue
            n = (sec.name or "").upper().strip()
            if n == prefix or n.startswith(prefix + " "):
                out.append(sec)
                claimed_section_ids.add(sid)
        out.sort(key=lambda s: (0 if s.name.upper().strip() == prefix else 1, s.name))
        return out

    groups: list[dict] = []

    # ── Top-level user-created choice gates (FLOOR TYPE, Door type, etc.) ──
    # A "gate" is a BodyOptionGroup with 2+ masters all using selection_mode='single'.
    # The move-section endpoint creates exactly this shape. Within each gate, we
    # dedupe options by name (preferring the master that owns sections, so an
    # accidental orphan duplicate doesn't show up twice).
    masters_by_group: dict[int, list[BillOfMaterial]] = {}
    for m in masters:
        if m.body_option_group_id:
            masters_by_group.setdefault(m.body_option_group_id, []).append(m)

    # Section-ownership lookup: a master id → number of live sections it owns.
    # Built first because the gate-detection criterion depends on it.
    section_ownership_count = {
        m.id: sum(1 for sid in sections if sections[sid].body_option_master_id == m.id)
        for m in masters
    }

    gate_group_ids: set[int] = set()
    for gid, ms in masters_by_group.items():
        if len(ms) < 2:
            continue
        if not all((m.selection_mode or "").lower() == "single" for m in ms):
            continue
        # CRITICAL: only treat as a top-level gate if at least one master in the
        # group OWNS sections via body_option_master_id. Otherwise this is an
        # inline bundle (e.g. RHINORANGE's FRONT EPS / FRONT PU under "INSULATION")
        # — those gate items WITHIN a shared parent section, they don't gate the
        # section itself, and they belong in the flags group, not the top level.
        if not any(section_ownership_count.get(m.id, 0) > 0 for m in ms):
            continue
        gate_group_ids.add(gid)

    for gid in gate_group_ids:
        ms = masters_by_group[gid]
        grp_obj = db.query(BodyOptionGroup).filter_by(id=gid).first()
        # Dedupe by name; prefer the master that owns more sections.
        by_name: dict[str, BillOfMaterial] = {}
        for m in ms:
            name = _bom_item_name(m)
            cur = by_name.get(name)
            if not cur or section_ownership_count.get(m.id, 0) > section_ownership_count.get(cur.id, 0):
                by_name[name] = m
        opts: list[dict] = []
        default_id = None
        for m in by_name.values():
            oid = f"opt-m{m.id}"
            opts.append({
                "id": oid,
                "name": _bom_item_name(m),
                "sections": [fmt_section(s, owning_master_id=m.id) for s in sections_for_master(m)],
            })
            if m.body_option_default and not default_id:
                default_id = oid
        opts.sort(key=lambda o: (o["name"] or "").lower())
        groups.append({
            "kind": "choice",
            "id": f"gate-{gid}",
            "label": (grp_obj.name if grp_obj else "Choice point"),
            "defaultId": default_id or (opts[0]["id"] if opts else None),
            "options": opts,
            "required": True,
        })

    # ── Door type (DRD / SRD) — legacy mutex pair, only if not already in a gate ──
    door_masters = {
        _bom_item_name(m).upper(): m
        for m in masters
        if _bom_item_name(m).upper() in _DOOR_TYPE_OPTIONS
        and m.body_option_group_id not in gate_group_ids
    }
    if door_masters:
        opts = []
        default_id = None
        for key in _DOOR_TYPE_OPTIONS:
            m = door_masters.get(key)
            if not m:
                continue
            opt_id = f"opt-m{m.id}"
            opts.append({
                "id": opt_id,
                "name": _bom_item_name(m),
                "sections": [fmt_section(s, owning_master_id=m.id) for s in sections_for_master(m, legacy_prefix=key)],
            })
            if m.body_option_default and not default_id:
                default_id = opt_id
        if opts:
            opts.sort(key=lambda o: (o["name"] or "").lower())
            groups.append({
                "kind": "choice",
                "id": "door-type",
                "label": "Door type",
                "defaultId": default_id or opts[0]["id"],
                "options": opts,
                "required": True,
            })

    # ── Body options — flags (with pick-one bundles) ────────────────────────
    # Masters that share a (body_option_group, selection_group) AND have selection_mode='single'
    # are mutually-exclusive bundles (e.g. RHINORANGE's FRONT EPS / FRONT PU under "INSULATION").
    # Group them; render the rest as independent flags.
    body_grp_lookup = {
        g.id: g.name
        for g in db.query(BodyOptionGroup)
        .filter(
            BodyOptionGroup.id.in_([m.body_option_group_id for m in masters if m.body_option_group_id])
        ).all()
    } if masters else {}

    bucket_map: dict[tuple, list[BillOfMaterial]] = {}
    independents: list[BillOfMaterial] = []
    for m in masters:
        # Skip masters that are already rendered as options of a top-level gate
        # or part of the legacy DRD/SRD door-type pair.
        if m.body_option_group_id in gate_group_ids:
            continue
        name = _bom_item_name(m)
        if name.upper() in _DOOR_TYPE_OPTIONS and m.body_option_group_id not in gate_group_ids:
            # If the legacy DRD/SRD block claimed this master, it'll appear there;
            # we also skip here so it isn't double-counted.
            if name.upper() in (door_masters or {}):
                continue
        # Flag was moved into a section (section_bound_flags above); skip the
        # flag-group buckets so it doesn't double-render. Use the same
        # "section is actually rendered" guard so legacy bom_section_id
        # values to invisible sections don't cause masters to vanish from
        # their groups.
        if m.bom_section_id is not None and m.bom_section_id in sections:
            continue
        sg = (m.selection_group or "").strip()
        if sg and (m.selection_mode or "").lower() == "single":
            grp_name = body_grp_lookup.get(m.body_option_group_id, "")
            bucket_map.setdefault((grp_name, sg), []).append(m)
        else:
            independents.append(m)

    # Resolve completed bundles (>=2 masters) and roll singletons back to independents.
    completed_bundles: list[tuple[tuple, list[BillOfMaterial]]] = []
    for key, ms in bucket_map.items():
        if len(ms) >= 2:
            completed_bundles.append((key, ms))
        else:
            independents.extend(ms)

    # Per-flag-group emission: each BodyOptionGroup with flag masters becomes its
    # own top-level group in the tree. Previously every flag landed in a single
    # "Body options (flags)" bucket regardless of body_option_group_id, which hid
    # the move-flags-to-group operation from the UI.
    per_group: dict[int, dict] = {}  # group_id → {label, independents:[], bundles:[]}

    def _ensure_group(m: BillOfMaterial) -> dict:
        gid = m.body_option_group_id or 0  # 0 = orphan/no group
        if gid not in per_group:
            label = body_grp_lookup.get(gid) if gid else "Body options"
            per_group[gid] = {
                "id": f"flags-g{gid}" if gid else "flags-orphan",
                "label": label or "Body options (flags)",
                "independents": [],
                "bundles_grouped": {},  # selection_group → [masters]
            }
        return per_group[gid]

    for m in independents:
        bucket = _ensure_group(m)
        bucket["independents"].append(m)

    for (_grp_name, sg_name), ms in completed_bundles:
        # All masters in a bundle share the same body_option_group_id (bucket key
        # is built from it), so we can pick the first to find the right group.
        bucket = _ensure_group(ms[0])
        bucket["bundles_grouped"].setdefault(sg_name, []).extend(ms)

    # Flag-group → linked gate-option master id (Option A nesting).
    # Loaded once; used both to set parentOptionMasterId on each flag group
    # dict and (after all groups are built) to migrate linked flag groups out
    # of the top-level list and onto their owning choice option.
    all_bogs = db.query(BodyOptionGroup).all()
    bog_parent_lookup = {
        bog.id: bog.parent_option_master_id
        for bog in all_bogs
        if getattr(bog, "parent_option_master_id", None) is not None
    }
    bog_by_id = {bog.id: bog for bog in all_bogs}
    # Seed empty user-created flag groups into per_group so they render in the
    # tree even before any flags are added. A group qualifies if it has a
    # parent_option_master_id (linked to a gate option) — those are the only
    # ones the configurator UI created explicitly. Default-import groups stay
    # invisible until they have flag masters, so we don't pollute the tree
    # with the dozens of legacy import groups.
    for bog in all_bogs:
        if bog.id in per_group:
            continue
        if bog.parent_option_master_id is None:
            continue
        per_group[bog.id] = {
            "id": f"flags-g{bog.id}",
            "label": bog.name,
            "independents": [],
            "bundles_grouped": {},
        }

    for gid, bucket in per_group.items():
        # Build independent flag options (deduped by name).
        flag_opts = []
        seen_flag_names: set[str] = set()
        for m in bucket["independents"]:
            name = _bom_item_name(m)
            if name in seen_flag_names:
                continue
            seen_flag_names.add(name)
            style = "radio" if (m.selection_mode or "").lower() == "single" else "tick"
            flag_opts.append({
                "id": f"flag-m{m.id}", "name": name, "sections": [], "style": style,
            })
        flag_opts.sort(key=lambda o: (o["name"] or "").lower())

        # Build bundles within this group.
        bundles = []
        for sg_name, ms in bucket["bundles_grouped"].items():
            bopts = []
            default_id = None
            for m in ms:
                oid = f"flag-m{m.id}"
                bopts.append({"id": oid, "name": _bom_item_name(m), "sections": []})
                if m.body_option_default and not default_id:
                    default_id = oid
            bopts.sort(key=lambda o: (o["name"] or "").lower())
            slug = f"{bucket['label']}__{sg_name}".replace(" ", "_").replace("/", "-")
            bundles.append({
                "id": f"bundle-{slug}",
                "label": f"{bucket['label']} — {sg_name}",
                "defaultId": default_id or bopts[0]["id"],
                "options": bopts,
                "originGroup": bucket["label"],
                "originSelectionGroup": sg_name,
            })
        bundles.sort(key=lambda b: (b["label"] or "").lower())

        # Empty groups normally hide, but a user-linked empty group still
        # needs to render under its gate option so the user can drop flags in.
        if not flag_opts and not bundles and bog_parent_lookup.get(gid) is None:
            continue

        # Display id: keep "body-flags" for the original BODY OPTIONS group so existing
        # selectors/snapshots still work; other groups get a stable id from their gid.
        display_id = "body-flags" if (bucket["label"] or "").upper() == "BODY OPTIONS" else bucket["id"]
        display_label = "Body options (flags)" if (bucket["label"] or "").upper() == "BODY OPTIONS" else bucket["label"]
        groups.append({
            "kind": "flags",
            "id": display_id,
            "label": display_label,
            "options": flag_opts,
            "bundles": bundles,
            # Carry DB identifiers so the configurator UI can POST link/unlink
            # operations on this flag group, and so the nesting pass below can
            # migrate this entry under its parent gate option.
            "dbGroupId": gid or None,
            "parentOptionMasterId": bog_parent_lookup.get(gid),
        })

    # ── Nest linked flag groups under their parent choice option ────────────
    # When body_option_groups.parent_option_master_id is set, the flag group
    # moves out of the top-level `groups` list and lives on the option's
    # `linkedFlagGroups` array. The data inside the flag group (options +
    # bundles) is untouched — only its placement in the tree changes.
    by_opt_id_choice = {}  # opt-m<id> → option dict
    for g in groups:
        if g.get("kind") != "choice":
            continue
        for o in g.get("options", []):
            by_opt_id_choice[o["id"]] = o
    remaining_top: list[dict] = []
    for g in groups:
        if g.get("kind") == "flags" and g.get("parentOptionMasterId"):
            target = by_opt_id_choice.get(f"opt-m{g['parentOptionMasterId']}")
            if target is not None:
                target.setdefault("linkedFlagGroups", []).append(g)
                continue  # do NOT keep at top level
            # Parent master not found in any choice gate — surface at top
            # level as a fallback so the user can see/unlink it.
        remaining_top.append(g)
    groups = remaining_top

    # ── Always include — every remaining section with items ─────────────────
    always_sections = [
        fmt_section(sections[sid])
        for sid in sec_ids
        if sid in sections and sid not in claimed_section_ids
    ]
    always_sections.sort(key=lambda s: s["name"])
    groups.insert(0, {
        "kind": "always",
        "id": "always",
        "label": "Always include",
        "sections": always_sections,
    })

    # Catalog of every BodyOptionGroup so pickers (e.g. "Link existing flag
    # group" in the gate-option ＋ modal) can offer every group even when
    # the tree builder skips rendering an empty/legacy one. UI is expected
    # to filter the list further if needed.
    available_flag_groups = sorted([
        {
            "dbGroupId": bog.id,
            "name": bog.name,
            "parentOptionMasterId": bog.parent_option_master_id,
        }
        for bog in all_bogs
    ], key=lambda g: (g["name"] or "").lower())

    # Orphan BOM items: non-master rows that lost their section assignment (e.g.
    # delete-and-re-add path that drops bom_section_id, or a section that was
    # hard-deleted leaving its items dangling). Surface them in the unassigned
    # tray under a synthetic "ORPHANED ITEMS" section so the user can see and
    # recover them — without this they're silently invisible everywhere.
    orphan_items = [r for r in items if r.bom_section_id is None and not r.is_body_option]
    unassigned_payload = [fmt_section(s) for s in archived_sections]
    if orphan_items:
        unassigned_payload.append({
            "id": "orphan-items",
            "name": "ORPHANED ITEMS",
            "items": [fmt_item(r) for r in orphan_items],
            "bodyOptionMasterId": None,
            "flags": [],
        })

    return {
        "trailerName": trailer.name,
        "trailerId": trailer.id,
        "groups": groups,
        "unassigned": unassigned_payload,
        "bodyOptions": [_bom_item_name(m) for m in masters],
        "availableFlagGroups": available_flag_groups,
    }


@router.get("/api/configurator/trailers")
async def configurator_list_trailers(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or user.role != "admin":
        raise HTTPException(status_code=401, detail="Admin only")
    trailers = (
        db.query(TrailerType)
        .filter_by(is_active=True)
        .order_by(TrailerType.name)
        .all()
    )
    return [{"id": t.id, "name": t.name} for t in trailers]


@router.get("/api/configurator/trailers/{trailer_id}/tree")
async def configurator_tree(
    trailer_id: int, request: Request, db: Session = Depends(get_db)
):
    # Read-only for any authenticated user — the costings page also consumes
    # this endpoint to render its body-options panel as a tree on v2 trailers.
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    trailer = db.query(TrailerType).filter_by(id=trailer_id, is_active=True).first()
    if not trailer:
        raise HTTPException(status_code=404, detail="Trailer not found")
    return _build_configurator_tree(db, trailer)


def _require_admin_api(request: Request, db: Session):
    user = get_current_user(request, db)
    if not user or user.role != "admin":
        raise HTTPException(status_code=401, detail="Admin only")
    return user


# ─── Visual-configurator draft persistence ──────────────────────────────────
# The settings page builds a body-options tree (folders/categories/flags). It
# used to live only in the admin's browser localStorage; these endpoints store
# it server-side so the costings page applies it for everyone, on any device.

@router.get("/api/configurator/trailers/{trailer_id}/draft")
async def configurator_get_draft(
    trailer_id: int, request: Request, db: Session = Depends(get_db)
):
    # Any authenticated user — the costings page reads this to render the
    # body-options panel from the admin's saved configurator tree.
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    row = db.query(ConfiguratorDraft).filter_by(trailer_type_id=trailer_id).first()
    if not row or not row.payload:
        return {"draft": None}
    try:
        return {"draft": json.loads(row.payload)}
    except (ValueError, TypeError):
        return {"draft": None}


@router.get("/api/configurator/drafts")
async def configurator_list_drafts(request: Request, db: Session = Depends(get_db)):
    # Admin only — the settings page pulls every saved draft on load so the
    # browser's localStorage mirror stays in sync with the server.
    _require_admin_api(request, db)
    out = {}
    for row in db.query(ConfiguratorDraft).all():
        if not row.payload:
            continue
        try:
            out[str(row.trailer_type_id)] = json.loads(row.payload)
        except (ValueError, TypeError):
            continue
    return out


@router.put("/api/configurator/trailers/{trailer_id}/draft")
async def configurator_put_draft(
    trailer_id: int, payload: dict, request: Request, db: Session = Depends(get_db)
):
    user = _require_admin_api(request, db)
    draft = payload.get("draft")
    if not isinstance(draft, dict):
        raise HTTPException(status_code=400, detail="draft object required")
    trailer = db.query(TrailerType).filter_by(id=trailer_id).first()
    if not trailer:
        raise HTTPException(status_code=404, detail="Trailer not found")
    row = db.query(ConfiguratorDraft).filter_by(trailer_type_id=trailer_id).first()
    if row is None:
        row = ConfiguratorDraft(trailer_type_id=trailer_id)
        db.add(row)
    row.payload = json.dumps(draft)
    row.updated_by = getattr(user, "username", None)
    db.commit()
    return {"ok": True}


# ─── Configurator draft snapshots (Settings page Explorer backup/restore) ────
# Distinct from ConfiguratorSnapshot (which captures BOM schema state for the
# /admin/configurator-preview page). This system snapshots only the Explorer
# tree the Settings page edits — never BOM rows, prices, or any other data.

def _capture_draft_snapshot(
    db: Session, trailer_id: int, label: str, created_by: str | None,
) -> ConfiguratorDraftSnapshot:
    draft_row = db.query(ConfiguratorDraft).filter_by(trailer_type_id=trailer_id).first()
    payload = draft_row.payload if (draft_row and draft_row.payload) else "{}"
    snap = ConfiguratorDraftSnapshot(
        trailer_type_id=trailer_id,
        label=label.strip()[:255] or "Snapshot",
        payload=payload,
        created_at=datetime.now(timezone.utc),
        created_by=created_by,
    )
    db.add(snap)
    db.flush()
    return snap


@router.post("/api/configurator/trailers/{trailer_id}/draft-snapshots")
async def configurator_capture_draft_snapshot(
    trailer_id: int, payload: dict, request: Request, db: Session = Depends(get_db),
):
    user = _require_admin_api(request, db)
    trailer = db.query(TrailerType).filter_by(id=trailer_id).first()
    if not trailer:
        raise HTTPException(status_code=404, detail="Trailer not found")
    label = (payload.get("label") or "").strip()
    if not label:
        label = f"{trailer.name} {date.today().isoformat()}"
    snap = _capture_draft_snapshot(db, trailer_id, label, getattr(user, "username", None))
    db.commit()
    return {
        "ok": True,
        "id": snap.id,
        "label": snap.label,
        "created_at": snap.created_at.isoformat(),
        "created_by": snap.created_by,
    }


@router.get("/api/configurator/trailers/{trailer_id}/draft-snapshots")
async def configurator_list_draft_snapshots(
    trailer_id: int, request: Request, db: Session = Depends(get_db),
):
    _require_admin_api(request, db)
    rows = (
        db.query(ConfiguratorDraftSnapshot)
        .filter_by(trailer_type_id=trailer_id)
        .order_by(ConfiguratorDraftSnapshot.created_at.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "label": r.label,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "created_by": r.created_by,
        }
        for r in rows
    ]


@router.post("/api/configurator/draft-snapshots/{snap_id}/restore")
async def configurator_restore_draft_snapshot(
    snap_id: int, request: Request, db: Session = Depends(get_db),
):
    user = _require_admin_api(request, db)
    snap = db.query(ConfiguratorDraftSnapshot).filter_by(id=snap_id).first()
    if not snap:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    trailer = db.query(TrailerType).filter_by(id=snap.trailer_type_id).first()
    if not trailer:
        raise HTTPException(status_code=404, detail="Trailer not found")

    # Safety net: capture current draft state before overwriting
    pre = _capture_draft_snapshot(
        db, snap.trailer_type_id,
        f"Auto-backup before restore of '{snap.label}' — {date.today().isoformat()}",
        getattr(user, "username", None),
    )

    # Overwrite the live draft with the snapshot's payload
    draft = db.query(ConfiguratorDraft).filter_by(trailer_type_id=snap.trailer_type_id).first()
    if draft is None:
        draft = ConfiguratorDraft(trailer_type_id=snap.trailer_type_id)
        db.add(draft)
    draft.payload = snap.payload
    draft.updated_by = getattr(user, "username", None)
    db.commit()

    try:
        restored = json.loads(snap.payload)
    except (ValueError, TypeError):
        restored = {}
    return {
        "ok": True,
        "restored_label": snap.label,
        "pre_restore_snapshot_id": pre.id,
        "draft": restored,
    }


@router.delete("/api/configurator/draft-snapshots/{snap_id}")
async def configurator_delete_draft_snapshot(
    snap_id: int, request: Request, db: Session = Depends(get_db),
):
    _require_admin_api(request, db)
    snap = db.query(ConfiguratorDraftSnapshot).filter_by(id=snap_id).first()
    if not snap:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    db.delete(snap)
    db.commit()
    return {"ok": True}


_LINKED_PREFIXES = {"DRD": "SRD", "SRD": "DRD"}  # legacy mutex pair — body_option_linked_id


@router.post("/api/configurator/trailers/{trailer_id}/move-section")
async def configurator_move_section(
    trailer_id: int, payload: dict, request: Request, db: Session = Depends(get_db)
):
    """Move one or more sections under a choice-point option.

    Payload:
      {
        "sourceSectionId": <int>,                       # required, DB id
        "alsoMoveSectionIds": [<int>, ...],             # optional, DB ids
        "choicePoint": {"id": <int>|null, "label": str},# id=BodyOptionGroup.id if existing
        "option":      {"id": <int>|null, "name": str}, # id=BillOfMaterial.id of an existing master
      }

    Behaviour:
      - Creates/finds a BodyOptionGroup (the choice-point container).
      - Creates/finds a master row (BillOfMaterial with is_body_option=1) for the option.
      - Updates BOMSection.body_option_master_id for the source + alsoMove sections.
      - For DRD/SRD options, also wires body_option_linked_id so the legacy calculator
        pre-filter treats them as a mutex pair (matches existing trailers).
    """
    _require_admin_api(request, db)

    trailer = db.query(TrailerType).filter_by(id=trailer_id, is_active=True).first()
    if not trailer:
        raise HTTPException(status_code=404, detail="Trailer not found")

    try:
        source_id = int(payload.get("sourceSectionId"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="sourceSectionId required")

    also_ids = payload.get("alsoMoveSectionIds") or []
    try:
        also_ids = [int(x) for x in also_ids if x is not None]
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="alsoMoveSectionIds must be a list of ints")

    cp = payload.get("choicePoint") or {}
    opt = payload.get("option") or {}
    cp_label = (cp.get("label") or "").strip()
    opt_name = (opt.get("name") or "").strip()
    cp_existing_id = cp.get("id")
    opt_existing_id = opt.get("id")

    if not cp_existing_id and not cp_label:
        raise HTTPException(status_code=400, detail="choicePoint.label or id required")
    if not opt_existing_id and not opt_name:
        raise HTTPException(status_code=400, detail="option.name or id required")

    # ── Section existence + ownership check ──────────────────────────────────
    target_ids = [source_id] + [x for x in also_ids if x != source_id]
    sections = (
        db.query(BOMSection).filter(BOMSection.id.in_(target_ids)).all()
    )
    sections_by_id = {s.id: s for s in sections}
    missing = [x for x in target_ids if x not in sections_by_id]
    if missing:
        raise HTTPException(status_code=404, detail=f"Sections not found: {missing}")

    # Only act on sections that actually have items on this trailer (defensive).
    own_secs = {
        r.bom_section_id
        for r in db.query(BillOfMaterial.bom_section_id)
        .filter(BillOfMaterial.trailer_type_id == trailer.id)
        .filter(BillOfMaterial.bom_section_id.in_(target_ids))
        .distinct()
        .all()
    }
    if source_id not in own_secs:
        raise HTTPException(
            status_code=400, detail="Source section has no items on this trailer"
        )

    # Block: any of the sections being moved are already owned by an option of
    # another gate on this trailer. Allow re-owning by the SAME master id (idempotent
    # re-save) but reject if it would put one section under two different masters.
    incoming_existing_master_id = int(opt_existing_id) if opt_existing_id else None
    conflicts = []
    for sid in target_ids:
        s = sections_by_id[sid]
        if s.body_option_master_id and s.body_option_master_id != incoming_existing_master_id:
            owner = db.query(BillOfMaterial).filter_by(id=s.body_option_master_id).first()
            owner_name = _bom_item_name(owner) if owner else "another option"
            conflicts.append(f'"{s.name}" is already under option "{owner_name}"')
    if conflicts:
        raise HTTPException(
            status_code=409,
            detail="Section(s) already in a gate: " + "; ".join(conflicts) +
                   ". A section can only belong to one gate.",
        )

    # ── Resolve / create the choice-point group ──────────────────────────────
    group = None
    if cp_existing_id:
        group = db.query(BodyOptionGroup).filter_by(id=int(cp_existing_id)).first()
        if not group:
            raise HTTPException(status_code=404, detail="Choice point not found")
    if not group:
        # Reuse a group with the same name if it already exists (groups are global),
        # otherwise create a fresh one. Don't link bom_section_id — that's the legacy
        # 1:1 link; we use body_option_master_id for the new model.
        group = db.query(BodyOptionGroup).filter_by(name=cp_label).first()
        if not group:
            group = BodyOptionGroup(name=cp_label, sort_order=0)
            db.add(group)
            db.flush()  # so group.id is available

    # ── Resolve / create the master row for the option ───────────────────────
    master = None
    if opt_existing_id:
        master = (
            db.query(BillOfMaterial)
            .filter_by(id=int(opt_existing_id), trailer_type_id=trailer.id, is_body_option=True)
            .first()
        )
        if not master:
            raise HTTPException(status_code=404, detail="Option (master row) not found on this trailer")
    if not master:
        # Reuse a Material with the matching name if one exists; otherwise create one.
        mat = db.query(Material).filter_by(name=opt_name).first()
        if not mat:
            mat = Material(name=opt_name, unit_of_measure="each", price_per_unit=0.0)
            db.add(mat)
            db.flush()
        master = BillOfMaterial(
            trailer_type_id=trailer.id,
            material_id=mat.id,
            is_body_option=True,
            body_option_default=False,
            body_option_group_id=group.id,
            # Mirror the FK name into the legacy string fields so the costing
            # page's renderBodyOptions (which buckets by body_option_group str)
            # groups these masters under the gate name instead of "MISC".
            body_option_group=group.name,
            body_option_subgroup=group.name,
            selection_mode="single",  # choice-point options are single-select
            selection_group=cp_label or group.name,
            sort_order=0,
        )
        db.add(master)
        db.flush()

    # If this is the first option in the group on this trailer, make it ★ default.
    siblings = (
        db.query(BillOfMaterial)
        .filter_by(trailer_type_id=trailer.id, body_option_group_id=group.id, is_body_option=True)
        .all()
    )
    if not any(s.body_option_default for s in siblings):
        master.body_option_default = True

    # ── DRD ↔ SRD legacy mutex pair: wire body_option_linked_id both ways ───
    pair_key = (opt_name or "").upper()
    pair_other_name = _LINKED_PREFIXES.get(pair_key)
    if pair_other_name:
        other_master = (
            db.query(BillOfMaterial)
            .join(Material, Material.id == BillOfMaterial.material_id, isouter=True)
            .filter(BillOfMaterial.trailer_type_id == trailer.id)
            .filter(BillOfMaterial.is_body_option == True)
            .filter(
                (Material.name == pair_other_name)
                | (BillOfMaterial.body_option_linked == pair_other_name)
            )
            .first()
        )
        if other_master and other_master.material_id:
            master.body_option_linked_id = other_master.material_id
            master.body_option_linked = pair_other_name
            # And the inverse — so the legacy calculator pre-filter sees the pair.
            if master.material_id:
                other_master.body_option_linked_id = master.material_id
                other_master.body_option_linked = opt_name

    # ── Link the moved sections to this master ───────────────────────────────
    moved_ids = []
    for sid in target_ids:
        if sid not in own_secs:
            continue  # ignore "related" sections that have no items on this trailer
        sec = sections_by_id[sid]
        sec.body_option_master_id = master.id
        moved_ids.append(sid)

    db.commit()

    return {
        "ok": True,
        "movedSectionIds": moved_ids,
        "groupId": group.id,
        "groupLabel": group.name,
        "masterId": master.id,
        "masterName": opt_name or (master.material.name if master.material else ""),
        "linkedPairOther": pair_other_name,
    }


@router.patch("/api/configurator/sections/{section_id}")
async def configurator_rename_section(
    section_id: int, payload: dict, request: Request, db: Session = Depends(get_db)
):
    """Rename a BOMSection. Mirrors the new name into BillOfMaterial.bom_section
    (the legacy string column) so the calculator's DRD/SRD prefix pre-filter
    keeps working on existing rows."""
    _require_admin_api(request, db)
    new_name = (payload.get("name") or "").strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="name required")
    if len(new_name) > 200:
        raise HTTPException(status_code=400, detail="name too long")

    sec = db.query(BOMSection).filter_by(id=section_id).first()
    if not sec:
        raise HTTPException(status_code=404, detail="Section not found")

    if sec.name == new_name:
        return {"id": sec.id, "name": sec.name}

    conflict = (
        db.query(BOMSection)
        .filter(BOMSection.name == new_name, BOMSection.id != section_id)
        .first()
    )
    if conflict:
        raise HTTPException(
            status_code=409, detail=f"Another section already uses the name {new_name!r}"
        )

    sec.name = new_name
    # Keep the legacy string column in sync — calculator code reads either.
    db.query(BillOfMaterial).filter_by(bom_section_id=section_id).update(
        {"bom_section": new_name}, synchronize_session=False
    )
    db.commit()
    return {"id": sec.id, "name": sec.name}


def _scan_draft_for_category(payload_json: str, section_key: str) -> tuple[int, dict]:
    """Inspect a ConfiguratorDraft.payload JSON string. Returns (node_count,
    cleaned_payload_dict) — node_count is how many `category` nodes reference
    section_key (uppercase match); cleaned_payload_dict has those nodes removed
    along with any references to them in rootIds / childIds. Returns (0, {})
    if the payload doesn't parse."""
    try:
        draft = json.loads(payload_json or "{}")
    except (ValueError, TypeError):
        return 0, {}
    if not isinstance(draft, dict):
        return 0, {}
    nodes = draft.get("nodes") or {}
    if not isinstance(nodes, dict):
        return 0, draft

    key = (section_key or "").strip().upper()
    if not key:
        return 0, draft

    orphan_ids = set()
    for node_id, node in nodes.items():
        if not isinstance(node, dict):
            continue
        if node.get("type") != "category":
            continue
        src = (node.get("sourceCategoryKey") or "").strip().upper()
        if src == key:
            orphan_ids.add(node_id)

    if not orphan_ids:
        return 0, draft

    # Strip the orphan nodes and clean up any parent-child references
    new_nodes = {nid: n for nid, n in nodes.items() if nid not in orphan_ids}
    for n in new_nodes.values():
        if isinstance(n, dict) and isinstance(n.get("childIds"), list):
            n["childIds"] = [c for c in n["childIds"] if c not in orphan_ids]
    new_root = [r for r in (draft.get("rootIds") or []) if r not in orphan_ids]
    cleaned = dict(draft)
    cleaned["nodes"] = new_nodes
    cleaned["rootIds"] = new_root
    return len(orphan_ids), cleaned


def _find_draft_category_usage(db: Session, section_name: str) -> list[dict]:
    """Walk every configurator draft and return the trailers whose drafts
    reference this section's name as a category. Used by the delete-section
    preview so we can warn users before they break Settings-page configs."""
    if not section_name:
        return []
    key = section_name.strip().upper()
    if not key:
        return []
    out = []
    rows = db.query(ConfiguratorDraft).all()
    for row in rows:
        node_count, _cleaned = _scan_draft_for_category(row.payload, key)
        if node_count > 0:
            tt = db.query(TrailerType).filter_by(id=row.trailer_type_id).first()
            out.append({
                "trailer_type_id": row.trailer_type_id,
                "trailer_name": tt.name if tt else f"#{row.trailer_type_id}",
                "node_count": node_count,
            })
    return out


@router.get("/api/configurator/sections/{section_id}/usage")
async def configurator_section_usage(
    section_id: int, request: Request, db: Session = Depends(get_db),
):
    """Preview what would be impacted if this section/category were deleted.
    Returns the list of trailers whose Settings-page configurator drafts
    reference this section as a category node."""
    _require_admin_api(request, db)
    sec = db.query(BOMSection).filter_by(id=section_id).first()
    if not sec:
        raise HTTPException(status_code=404, detail="Section not found")
    drafts_affected = _find_draft_category_usage(db, sec.name)
    return {
        "section_id": section_id,
        "section_name": sec.name,
        "drafts_affected": drafts_affected,
        "draft_count": len(drafts_affected),
        "node_count": sum(d["node_count"] for d in drafts_affected),
    }


@router.delete("/api/configurator/sections/{section_id}")
async def configurator_delete_section(
    section_id: int, request: Request, db: Session = Depends(get_db),
    mode: str = "unassign",
):
    """Delete a section. `mode=unassign` (default) sends it to the Unassigned tray
    (items preserved, section excluded from costing). `mode=destroy` permanently
    deletes the section and every BillOfMaterial row that lives in it.

    For mode=destroy we also walk every ConfiguratorDraft.payload and strip
    `category` nodes whose sourceCategoryKey matches this section's name —
    otherwise the Settings page would render ghost nodes for the deleted key.
    Snapshots are left untouched; restore tolerates orphan keys gracefully.
    """
    _require_admin_api(request, db)
    if mode not in ("unassign", "destroy"):
        raise HTTPException(status_code=400, detail="mode must be 'unassign' or 'destroy'")
    sec = db.query(BOMSection).filter_by(id=section_id).first()
    if not sec:
        raise HTTPException(status_code=404, detail="Section not found")
    section_name_for_cleanup = sec.name

    drafts_cleaned = 0
    nodes_cleaned = 0
    if mode == "destroy":
        # Wipe BOM rows that live in this section, then the section itself.
        db.query(BillOfMaterial).filter_by(bom_section_id=section_id).delete(synchronize_session=False)
        db.delete(sec)

        # Cascade cleanup: strip ghost category nodes from every draft.
        key = (section_name_for_cleanup or "").strip().upper()
        for draft_row in db.query(ConfiguratorDraft).all():
            n, cleaned = _scan_draft_for_category(draft_row.payload, key)
            if n > 0:
                draft_row.payload = json.dumps(cleaned)
                drafts_cleaned += 1
                nodes_cleaned += n
    else:
        # Park it in the Unassigned tray. Strip any gate ownership so it doesn't
        # render under a master if the user restored its owner later.
        sec.archived_at = datetime.now(timezone.utc)
        sec.body_option_master_id = None
    db.commit()
    return {
        "ok": True,
        "mode": mode,
        "sectionId": section_id,
        "draftsCleaned": drafts_cleaned,
        "nodesCleaned": nodes_cleaned,
    }


@router.post("/api/configurator/sections/{section_id}/restore")
async def configurator_restore_section(
    section_id: int, payload: dict, request: Request, db: Session = Depends(get_db),
):
    """Bring a section back from the Unassigned tray. Payload picks the destination:
      {"masterId": <id>}  → restore under an option (gate). Section starts owning items again.
      {"masterId": null}  → restore to Always-include (no gate ownership).
    """
    _require_admin_api(request, db)
    sec = db.query(BOMSection).filter_by(id=section_id).first()
    if not sec:
        raise HTTPException(status_code=404, detail="Section not found")

    master_id = payload.get("masterId")
    if master_id is not None:
        try:
            master_id = int(master_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="masterId must be an integer or null")
        master = db.query(BillOfMaterial).filter_by(id=master_id, is_body_option=True).first()
        if not master:
            raise HTTPException(status_code=404, detail="Target option (master row) not found")
        sec.body_option_master_id = master_id
    else:
        sec.body_option_master_id = None

    sec.archived_at = None
    db.commit()
    return {"ok": True, "sectionId": section_id, "masterId": master_id}


@router.patch("/api/configurator/options/{master_id}/set-default")
async def configurator_set_option_default(
    master_id: int, request: Request, db: Session = Depends(get_db),
):
    """Mark this option (master row) as the ★ default for its gate. Clears the
    default flag on every sibling master in the same BodyOptionGroup."""
    _require_admin_api(request, db)
    master = db.query(BillOfMaterial).filter_by(id=master_id, is_body_option=True).first()
    if not master:
        raise HTTPException(status_code=404, detail="Option (master row) not found")
    if master.body_option_group_id:
        db.query(BillOfMaterial).filter_by(
            body_option_group_id=master.body_option_group_id,
            trailer_type_id=master.trailer_type_id,
            is_body_option=True,
        ).update({"body_option_default": False}, synchronize_session=False)
    master.body_option_default = True
    db.commit()
    return {"ok": True, "masterId": master_id, "groupId": master.body_option_group_id}


def _find_condition_references(db, trailer_id: int, option_name: str) -> list[dict]:
    """Return every non-master BOM row on this trailer whose bom_conditions
    references the given option name. The returned shape carries enough info
    for the configurator UI to show the user which items would be affected."""
    import json as _json
    if not option_name:
        return []
    name = option_name.strip()
    rows = (
        db.query(BillOfMaterial)
        .filter_by(trailer_type_id=trailer_id, is_body_option=False)
        .filter(BillOfMaterial.bom_conditions.isnot(None))
        .all()
    )
    out = []
    for r in rows:
        raw = r.bom_conditions
        if not raw:
            continue
        try:
            parsed = _json.loads(raw)
        except (ValueError, TypeError):
            continue
        items = parsed if isinstance(parsed, list) else (parsed.get("all") or [] if isinstance(parsed, dict) else [])
        for c in items:
            if isinstance(c, dict) and (c.get("option") or "").strip() == name:
                out.append({
                    "item_id": r.id,
                    "item_name": r.material.name if r.material else "?",
                    "section": r.bom_section,
                })
                break
    return out


def _strip_condition_option(db, item_ids: list[int], option_name: str) -> None:
    """Remove every condition entry matching `option_name` from the given items'
    bom_conditions JSON. When the resulting list is empty, the column is set
    to NULL (= "always include")."""
    import json as _json
    if not item_ids or not option_name:
        return
    name = option_name.strip()
    rows = db.query(BillOfMaterial).filter(BillOfMaterial.id.in_(item_ids)).all()
    for r in rows:
        raw = r.bom_conditions
        if not raw:
            continue
        try:
            parsed = _json.loads(raw)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, list):
            kept = [c for c in parsed if not (isinstance(c, dict) and (c.get("option") or "").strip() == name)]
            r.bom_conditions = _json.dumps(kept) if kept else None
        elif isinstance(parsed, dict):
            inner = parsed.get("all") or []
            kept = [c for c in inner if not (isinstance(c, dict) and (c.get("option") or "").strip() == name)]
            parsed["all"] = kept
            r.bom_conditions = _json.dumps(parsed) if kept else None


@router.get("/api/configurator/trailers/{trailer_id}/orphan-conditions")
async def configurator_orphan_conditions(
    trailer_id: int, request: Request, db: Session = Depends(get_db),
):
    """Return every bom_conditions reference on this trailer whose option name
    no longer matches a live body-option master. Useful for auditing data drift
    after manual edits or imports."""
    _require_admin_api(request, db)
    trailer = db.query(TrailerType).filter_by(id=trailer_id, is_active=True).first()
    if not trailer:
        raise HTTPException(status_code=404, detail="Trailer not found")
    masters = db.query(BillOfMaterial).filter_by(
        trailer_type_id=trailer.id, is_body_option=True,
    ).all()
    known = {m.material.name.strip() for m in masters if m.material and m.material.name}
    import json as _json
    items = db.query(BillOfMaterial).filter_by(
        trailer_type_id=trailer.id, is_body_option=False,
    ).filter(BillOfMaterial.bom_conditions.isnot(None)).all()
    orphans = []
    for r in items:
        raw = r.bom_conditions
        try:
            parsed = _json.loads(raw)
        except (ValueError, TypeError):
            continue
        conds = parsed if isinstance(parsed, list) else (parsed.get("all") or [] if isinstance(parsed, dict) else [])
        for c in conds:
            if not isinstance(c, dict):
                continue
            opt = (c.get("option") or "").strip()
            if opt and opt not in known:
                orphans.append({
                    "itemId": r.id,
                    "itemName": r.material.name if r.material else "?",
                    "section": r.bom_section,
                    "orphanOption": opt,
                })
    return {"orphans": orphans, "count": len(orphans)}


@router.delete("/api/configurator/options/{master_id}")
async def configurator_delete_option(
    master_id: int, request: Request, db: Session = Depends(get_db),
):
    """Delete a choice-gate option (master row). Sections it owned cascade to the
    Unassigned tray (items preserved). The BodyOptionGroup is left in place
    unless it was the option's only member (then it's also removed).

    Query params:
      cleanup_references: bool (default false) — when true, also strip any
        bom_conditions on other items that reference this master's name.
        Without it, if active references exist we return 409 with the list so
        the UI can prompt the user to confirm cleanup.
    """
    _require_admin_api(request, db)
    master = db.query(BillOfMaterial).filter_by(id=master_id, is_body_option=True).first()
    if not master:
        raise HTTPException(status_code=404, detail="Option not found")

    master_name = master.material.name if master.material else ""
    trailer_id = master.trailer_type_id
    cleanup = (request.query_params.get("cleanup_references") or "").lower() in ("1", "true", "yes")

    # Pre-flight: find condition references to this master's name.
    referrers = _find_condition_references(db, trailer_id, master_name)
    if referrers and not cleanup:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "has_references",
                "message": f'"{master_name}" is referenced by {len(referrers)} item condition(s). '
                           f"Pass ?cleanup_references=true to delete the flag and strip the refs.",
                "references": [{"itemId": r["item_id"], "itemName": r["item_name"],
                                "section": r["section"]} for r in referrers],
            },
        )

    if cleanup and referrers:
        _strip_condition_option(db, [r["item_id"] for r in referrers], master_name)

    group_id = master.body_option_group_id
    # Cascade: owned sections go to Unassigned.
    owned = db.query(BOMSection).filter_by(body_option_master_id=master_id).all()
    now = datetime.now(timezone.utc)
    for s in owned:
        s.body_option_master_id = None
        s.archived_at = now

    db.delete(master)
    db.flush()

    # If the master's group is now empty, remove the group too.
    if group_id:
        still_used = (
            db.query(BillOfMaterial)
            .filter_by(body_option_group_id=group_id, is_body_option=True)
            .first()
        )
        if not still_used:
            grp = db.query(BodyOptionGroup).filter_by(id=group_id).first()
            if grp:
                db.delete(grp)
    db.commit()
    return {"ok": True, "deletedMasterId": master_id, "unassignedSectionIds": [s.id for s in owned]}


# ─── Configurator snapshots ───────────────────────────────────────────────────
# Capture the entire gating state of a trailer as a JSON blob so the user can
# restore to that point later. We snapshot what the *configurator* controls
# (section ownership/archived flags, master selection fields, item conditions,
# body-option-group names). Material rows, prices, formulas, dimensions are NOT
# snapshotted — those are managed elsewhere and shouldn't roll back.

def _serialize_configurator_state(db: Session, trailer_id: int) -> dict:
    """Capture a JSON-friendly snapshot of the trailer's configurator state."""
    rows = (
        db.query(BillOfMaterial)
        .filter_by(trailer_type_id=trailer_id)
        .all()
    )
    master_rows = [r for r in rows if r.is_body_option]
    item_rows   = [r for r in rows if not r.is_body_option]

    section_ids = {r.bom_section_id for r in rows if r.bom_section_id}
    sections = (
        db.query(BOMSection).filter(BOMSection.id.in_(section_ids)).all()
        if section_ids else []
    )
    grp_ids = {m.body_option_group_id for m in master_rows if m.body_option_group_id}
    grp_ids |= {s.body_option_master_id for s in sections if s.body_option_master_id}
    # ^ also include any groups referenced indirectly via masters owning sections
    groups = (
        db.query(BodyOptionGroup).filter(BodyOptionGroup.id.in_(
            {m.body_option_group_id for m in master_rows if m.body_option_group_id}
        )).all() if master_rows else []
    )

    return {
        "version": 1,
        "trailer_type_id": trailer_id,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "sections": [
            {
                "id": s.id,
                "name": s.name,
                "archived_at": s.archived_at.isoformat() if s.archived_at else None,
                "body_option_master_id": s.body_option_master_id,
            }
            for s in sections
        ],
        "groups": [{"id": g.id, "name": g.name} for g in groups],
        "masters": [
            {
                "id": m.id,
                "is_body_option": bool(m.is_body_option),
                "body_option_group_id": m.body_option_group_id,
                "body_option_default":  bool(m.body_option_default),
                "selection_mode":       m.selection_mode,
                "selection_group":      m.selection_group,
                "body_option_linked_id": m.body_option_linked_id,
                "body_option_linked":    m.body_option_linked,
            }
            for m in master_rows
        ],
        "items": [
            {"id": r.id, "bom_conditions": r.bom_conditions}
            for r in item_rows
        ],
    }


def _apply_configurator_snapshot(db: Session, trailer_id: int, payload: dict) -> dict:
    """Replay a snapshot onto the trailer. Existing rows have their fields reset;
    rows added since the snapshot are left alone (additive restore — never
    destructive). Returns a summary of what changed."""
    sec_updates = 0
    master_updates = 0
    item_updates = 0
    missing_sections = []
    missing_masters = []
    missing_items = []

    # Sections
    for snap_sec in payload.get("sections", []):
        sec = db.query(BOMSection).filter_by(id=snap_sec["id"]).first()
        if not sec:
            missing_sections.append(snap_sec["id"])
            continue
        sec.name = snap_sec["name"]
        sec.body_option_master_id = snap_sec.get("body_option_master_id")
        archived = snap_sec.get("archived_at")
        if archived:
            try:
                sec.archived_at = datetime.fromisoformat(archived)
            except (ValueError, TypeError):
                sec.archived_at = datetime.now(timezone.utc)
        else:
            sec.archived_at = None
        sec_updates += 1

    # Masters
    for snap_m in payload.get("masters", []):
        m = db.query(BillOfMaterial).filter_by(id=snap_m["id"]).first()
        if not m:
            missing_masters.append(snap_m["id"])
            continue
        m.is_body_option = snap_m["is_body_option"]
        m.body_option_group_id = snap_m.get("body_option_group_id")
        m.body_option_default = snap_m.get("body_option_default", False)
        m.selection_mode = snap_m.get("selection_mode") or "always"
        m.selection_group = snap_m.get("selection_group")
        m.body_option_linked_id = snap_m.get("body_option_linked_id")
        m.body_option_linked = snap_m.get("body_option_linked")
        master_updates += 1

    # Items (only the bom_conditions JSON — everything else is editorial)
    for snap_it in payload.get("items", []):
        it = db.query(BillOfMaterial).filter_by(id=snap_it["id"]).first()
        if not it:
            missing_items.append(snap_it["id"])
            continue
        it.bom_conditions = snap_it.get("bom_conditions")
        item_updates += 1

    db.commit()
    return {
        "sectionsUpdated": sec_updates,
        "mastersUpdated": master_updates,
        "itemsUpdated": item_updates,
        "missing": {
            "sections": missing_sections,
            "masters": missing_masters,
            "items": missing_items,
        },
    }


@router.get("/api/configurator/trailers/{trailer_id}/snapshots")
async def configurator_list_snapshots(
    trailer_id: int, request: Request, db: Session = Depends(get_db),
):
    _require_admin_api(request, db)
    snaps = (
        db.query(ConfiguratorSnapshot)
        .filter_by(trailer_type_id=trailer_id)
        .order_by(ConfiguratorSnapshot.created_at.desc())
        .all()
    )
    return [
        {"id": s.id, "name": s.name, "createdAt": s.created_at.isoformat() if s.created_at else None,
         "createdBy": s.created_by}
        for s in snaps
    ]


@router.post("/api/configurator/trailers/{trailer_id}/snapshots")
async def configurator_create_snapshot(
    trailer_id: int, payload: dict, request: Request, db: Session = Depends(get_db),
):
    user = _require_admin_api(request, db)
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    if len(name) > 200:
        raise HTTPException(status_code=400, detail="name too long")
    trailer = db.query(TrailerType).filter_by(id=trailer_id, is_active=True).first()
    if not trailer:
        raise HTTPException(status_code=404, detail="Trailer not found")
    state = _serialize_configurator_state(db, trailer_id)
    snap = ConfiguratorSnapshot(
        trailer_type_id=trailer_id,
        name=name,
        created_by=getattr(user, "username", None),
        payload=json.dumps(state),
    )
    db.add(snap)
    db.commit()
    db.refresh(snap)
    return {"id": snap.id, "name": snap.name, "createdAt": snap.created_at.isoformat()}


@router.post("/api/configurator/snapshots/{snapshot_id}/restore")
async def configurator_restore_snapshot(
    snapshot_id: int, request: Request, db: Session = Depends(get_db),
):
    _require_admin_api(request, db)
    snap = db.query(ConfiguratorSnapshot).filter_by(id=snapshot_id).first()
    if not snap:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    try:
        data = json.loads(snap.payload)
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=500, detail=f"Snapshot payload corrupted: {e}")
    summary = _apply_configurator_snapshot(db, snap.trailer_type_id, data)
    summary["snapshotName"] = snap.name
    summary["snapshotId"] = snap.id
    return summary


@router.delete("/api/configurator/snapshots/{snapshot_id}")
async def configurator_delete_snapshot(
    snapshot_id: int, request: Request, db: Session = Depends(get_db),
):
    _require_admin_api(request, db)
    snap = db.query(ConfiguratorSnapshot).filter_by(id=snapshot_id).first()
    if not snap:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    db.delete(snap)
    db.commit()
    return {"ok": True, "deletedId": snapshot_id}


@router.delete("/api/configurator/groups/{group_id}")
async def configurator_delete_group(
    group_id: int, request: Request, db: Session = Depends(get_db),
):
    """Delete an entire BodyOptionGroup (the gate). All its masters are removed and
    any sections they owned cascade to the Unassigned tray."""
    _require_admin_api(request, db)
    grp = db.query(BodyOptionGroup).filter_by(id=group_id).first()
    if not grp:
        raise HTTPException(status_code=404, detail="Group not found")

    masters_in_group = (
        db.query(BillOfMaterial).filter_by(body_option_group_id=group_id, is_body_option=True).all()
    )
    now = datetime.now(timezone.utc)
    unassigned_ids = []
    for m in masters_in_group:
        for s in db.query(BOMSection).filter_by(body_option_master_id=m.id).all():
            s.body_option_master_id = None
            s.archived_at = now
            unassigned_ids.append(s.id)
        db.delete(m)
    db.delete(grp)
    db.commit()
    return {"ok": True, "deletedGroupId": group_id, "unassignedSectionIds": unassigned_ids}


@router.post("/api/configurator/trailers/{trailer_id}/move-flags-to-group")
async def configurator_move_flags_to_group(
    trailer_id: int, payload: dict, request: Request, db: Session = Depends(get_db),
):
    """Move one or more flag masters into a different (or brand new) flag group.

    Payload:
      {
        "flagMasterIds":   [<int>, ...],          # masters to move
        "targetGroup": {"existingId": <int>}      # OR
                    OR {"newName":    <str>}
      }

    Behaviour:
      - existingId → update each master's body_option_group_id to that group.
      - newName    → create a new BodyOptionGroup with that name and use it.
      - Clear each master's selection_group (so it becomes an independent flag in
        the new group; user can re-bundle there if they want).
    """
    _require_admin_api(request, db)
    trailer = db.query(TrailerType).filter_by(id=trailer_id, is_active=True).first()
    if not trailer:
        raise HTTPException(status_code=404, detail="Trailer not found")

    ids = payload.get("flagMasterIds") or []
    try:
        ids = [int(x) for x in ids if x is not None]
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="flagMasterIds must be a list of ints")
    if len(ids) < 1:
        raise HTTPException(status_code=400, detail="At least one flag master id required")

    target = payload.get("targetGroup") or {}
    existing_id = target.get("existingId")
    new_name = (target.get("newName") or "").strip()

    if existing_id is not None:
        group = db.query(BodyOptionGroup).filter_by(id=int(existing_id)).first()
        if not group:
            raise HTTPException(status_code=404, detail="targetGroup.existingId not found")
    elif new_name:
        if len(new_name) > 200:
            raise HTTPException(status_code=400, detail="newName too long (max 200)")
        # Reuse a group with the same name (groups are global, so an existing
        # one with the same label is fine) — otherwise create a fresh one.
        group = db.query(BodyOptionGroup).filter_by(name=new_name).first()
        if not group:
            group = BodyOptionGroup(name=new_name, sort_order=0)
            db.add(group)
            db.flush()
    else:
        raise HTTPException(status_code=400, detail="targetGroup.existingId or targetGroup.newName required")

    masters = (
        db.query(BillOfMaterial)
        .filter(BillOfMaterial.id.in_(ids))
        .filter_by(trailer_type_id=trailer.id, is_body_option=True)
        .all()
    )
    found_ids = {m.id for m in masters}
    missing = [i for i in ids if i not in found_ids]
    if missing:
        raise HTTPException(status_code=404, detail=f"Master rows not found on this trailer: {missing}")

    for m in masters:
        m.body_option_group_id = group.id
        # Keep the legacy string columns in sync — the v2 costings page filter
        # reads `body_option_group` to decide whether a master is legacy and
        # should be hidden. Without this, a moved flag would still look
        # "legacy" and disappear from the costings body-options panel.
        m.body_option_group = group.name
        m.body_option_subgroup = group.name
        m.selection_group = None   # ungroup from any prior bundle in the source group
    db.commit()
    return {"ok": True, "movedMasterIds": [m.id for m in masters],
            "targetGroupId": group.id, "targetGroupName": group.name}


@router.post("/api/configurator/trailers/{trailer_id}/bundle-flags")
async def configurator_bundle_flags(
    trailer_id: int, payload: dict, request: Request, db: Session = Depends(get_db),
):
    """Group one or more independent flag masters into a named mutex bundle.

    Payload:
      {
        "flagMasterIds":   [<int>, ...],   # masters to bundle together
        "bundleSelectionGroup": str,        # bundle label (e.g. "INSULATION CHOICES")
      }

    Behaviour:
      - For each master, set selection_mode='single' + selection_group=<label>.
      - Tree builder buckets by (body_option_group_name, selection_group), so a
        new bundle named <label> appears within the masters' existing group.
      - Idempotent: re-running with the same label is a no-op.
    """
    _require_admin_api(request, db)
    trailer = db.query(TrailerType).filter_by(id=trailer_id, is_active=True).first()
    if not trailer:
        raise HTTPException(status_code=404, detail="Trailer not found")

    ids = payload.get("flagMasterIds") or []
    try:
        ids = [int(x) for x in ids if x is not None]
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="flagMasterIds must be a list of ints")
    if len(ids) < 1:
        raise HTTPException(status_code=400, detail="At least one flag master id required")

    label = (payload.get("bundleSelectionGroup") or "").strip()
    if not label:
        raise HTTPException(status_code=400, detail="bundleSelectionGroup required")
    if len(label) > 100:
        raise HTTPException(status_code=400, detail="bundleSelectionGroup too long (max 100)")

    masters = (
        db.query(BillOfMaterial)
        .filter(BillOfMaterial.id.in_(ids))
        .filter_by(trailer_type_id=trailer.id, is_body_option=True)
        .all()
    )
    found_ids = {m.id for m in masters}
    missing = [i for i in ids if i not in found_ids]
    if missing:
        raise HTTPException(status_code=404, detail=f"Master rows not found on this trailer: {missing}")

    for m in masters:
        m.selection_mode = "single"
        m.selection_group = label
    db.commit()
    return {"ok": True, "bundledMasterIds": [m.id for m in masters], "selectionGroup": label}


@router.post("/api/configurator/trailers/{trailer_id}/dissolve-bundle")
async def configurator_dissolve_bundle(
    trailer_id: int, payload: dict, request: Request, db: Session = Depends(get_db),
):
    """Dissolve a pick-one mutex bundle back into independent tick-style flags.

    Payload:
      {
        "originGroup":          str,   # body_option_group label
        "originSelectionGroup": str,   # selection_group label (the bundle name)
      }

    Behaviour:
      - For every master in (body_option_group=originGroup, selection_group=originSelectionGroup):
        clear selection_group (NULL) and set selection_mode='multi'.
      - The tree builder will then surface each master as an independent tick flag.
      - No bom rows are deleted.
    """
    _require_admin_api(request, db)
    trailer = db.query(TrailerType).filter_by(id=trailer_id, is_active=True).first()
    if not trailer:
        raise HTTPException(status_code=404, detail="Trailer not found")

    origin_group = (payload.get("originGroup") or "").strip()
    origin_sel   = (payload.get("originSelectionGroup") or "").strip()
    if not origin_sel:
        raise HTTPException(status_code=400, detail="originSelectionGroup required")

    # The tree builder labels each bucket by the BodyOptionGroup.name from the FK,
    # NOT the legacy body_option_group string column on bill_of_materials. Resolve
    # originGroup against the FK relationship so callers can pass the same label
    # they see in the UI.
    q = (
        db.query(BillOfMaterial)
        .filter_by(trailer_type_id=trailer.id, is_body_option=True,
                   selection_group=origin_sel)
    )
    if origin_group:
        bog = (
            db.query(BodyOptionGroup)
            .filter(BodyOptionGroup.name == origin_group)
            .first()
        )
        if bog is not None:
            q = q.filter(BillOfMaterial.body_option_group_id == bog.id)
        else:
            # Fallback to legacy string column match for trailers whose masters
            # never got their FK populated.
            q = q.filter(BillOfMaterial.body_option_group == origin_group)
    masters = q.all()
    if not masters:
        raise HTTPException(status_code=404, detail="No masters found in this bundle")

    for m in masters:
        m.selection_mode = "multi"
        m.selection_group = None
    db.commit()
    return {"ok": True, "dissolvedMasterIds": [m.id for m in masters]}


@router.patch("/api/configurator/groups/{group_id}")
async def configurator_rename_group(
    group_id: int, payload: dict, request: Request, db: Session = Depends(get_db),
):
    """Rename a BodyOptionGroup.

    Payload: { "name": <str> }

    Reflects on the configurator-tree label and on any place the server uses
    body_option_groups.name for grouping/buckets. Does NOT touch the legacy
    body_option_group string column on bill_of_materials.
    """
    _require_admin_api(request, db)
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    if len(name) > 100:
        raise HTTPException(status_code=400, detail="name too long (max 100)")

    grp = db.query(BodyOptionGroup).filter_by(id=group_id).first()
    if not grp:
        raise HTTPException(status_code=404, detail="Group not found")

    # Uniqueness is enforced at the column level; surface the conflict cleanly.
    clash = (
        db.query(BodyOptionGroup)
        .filter(BodyOptionGroup.name == name, BodyOptionGroup.id != group_id)
        .first()
    )
    if clash:
        raise HTTPException(status_code=409, detail=f'A group named "{name}" already exists')

    grp.name = name
    db.commit()
    return {"id": grp.id, "name": grp.name}


@router.patch("/api/configurator/groups/{group_id}/parent-option")
async def configurator_set_group_parent_option(
    group_id: int, payload: dict, request: Request, db: Session = Depends(get_db),
):
    """Link a flag group to a gate option, or unlink it (top-level).

    Payload:
      { "optionMasterId": <int|null> }
        - int  → set body_option_groups.parent_option_master_id = that master id
        - null → clear (group becomes top-level again)
    """
    _require_admin_api(request, db)
    grp = db.query(BodyOptionGroup).filter_by(id=group_id).first()
    if not grp:
        raise HTTPException(status_code=404, detail="Group not found")

    raw = payload.get("optionMasterId", None)
    if raw is None:
        grp.parent_option_master_id = None
        db.commit()
        return {"ok": True, "groupId": grp.id, "parentOptionMasterId": None}

    try:
        master_id = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="optionMasterId must be int or null")

    master = (
        db.query(BillOfMaterial)
        .filter_by(id=master_id, is_body_option=True)
        .first()
    )
    if not master:
        raise HTTPException(status_code=404, detail="Master option not found")

    grp.parent_option_master_id = master.id
    db.commit()
    return {"ok": True, "groupId": grp.id, "parentOptionMasterId": master.id}


@router.patch("/api/configurator/flags/{master_id}/style")
async def configurator_set_flag_style(
    master_id: int, payload: dict, request: Request, db: Session = Depends(get_db)
):
    """Persist a per-flag tick↔radio style toggle.

    Tick (independent) → selection_mode='multi', selection_group=NULL
    Radio (mutex with siblings) → selection_mode='single', selection_group='AUTO'

    The tree builder buckets masters by (body_option_group_name, selection_group),
    so the constant string 'AUTO' makes every radio-style master in the SAME
    BodyOptionGroup share one bundle — exactly the "no bundling wizard" rule.
    """
    _require_admin_api(request, db)

    style = (payload.get("style") or "").lower()
    if style not in ("tick", "radio"):
        raise HTTPException(status_code=400, detail="style must be 'tick' or 'radio'")

    row = db.query(BillOfMaterial).filter_by(id=master_id, is_body_option=True).first()
    if not row:
        raise HTTPException(status_code=404, detail="Flag (master row) not found")

    if style == "radio":
        row.selection_mode = "single"
        row.selection_group = "AUTO"
    else:
        row.selection_mode = "multi"
        row.selection_group = None
    db.commit()
    return {"id": row.id, "style": style, "selectionMode": row.selection_mode, "selectionGroup": row.selection_group}


@router.post("/api/configurator/trailers/{trailer_id}/flag-groups")
async def configurator_create_flag_group(
    trailer_id: int, payload: dict, request: Request, db: Session = Depends(get_db),
):
    """Create a new BodyOptionGroup (flag group). Optionally link it to a gate
    option in the same call.

    Payload:
      { "name": <str>, "parentOptionMasterId": <int|null> }
    """
    _require_admin_api(request, db)
    trailer = db.query(TrailerType).filter_by(id=trailer_id, is_active=True).first()
    if not trailer:
        raise HTTPException(status_code=404, detail="Trailer not found")

    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    if len(name) > 100:
        raise HTTPException(status_code=400, detail="name too long (max 100)")

    parent_master_id = payload.get("parentOptionMasterId")
    if parent_master_id is not None:
        try:
            parent_master_id = int(parent_master_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="parentOptionMasterId must be int or null")
        master = db.query(BillOfMaterial).filter_by(
            id=parent_master_id, trailer_type_id=trailer.id, is_body_option=True,
        ).first()
        if not master:
            raise HTTPException(status_code=404, detail="Parent master option not found on this trailer")

    # Names must be unique per-trailer (same name can exist on different trailers).
    # A group is "in use" by this trailer when at least one BOM row references it.
    existing = (
        db.query(BodyOptionGroup)
        .join(BillOfMaterial, BillOfMaterial.body_option_group_id == BodyOptionGroup.id)
        .filter(
            BillOfMaterial.trailer_type_id == trailer.id,
            BodyOptionGroup.name == name,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail=f'A flag group named "{name}" already exists')

    grp = BodyOptionGroup(name=name, sort_order=0, parent_option_master_id=parent_master_id)
    db.add(grp)
    db.commit()
    return {"id": grp.id, "name": grp.name, "parentOptionMasterId": grp.parent_option_master_id}


@router.post("/api/configurator/trailers/{trailer_id}/flag-groups/{group_id}/flags")
async def configurator_create_flag(
    trailer_id: int, group_id: int, payload: dict, request: Request, db: Session = Depends(get_db),
):
    """Create a new flag master in the given flag group on this trailer.

    Payload: { "name": <str> }
    """
    _require_admin_api(request, db)
    trailer = db.query(TrailerType).filter_by(id=trailer_id, is_active=True).first()
    if not trailer:
        raise HTTPException(status_code=404, detail="Trailer not found")
    grp = db.query(BodyOptionGroup).filter_by(id=group_id).first()
    if not grp:
        raise HTTPException(status_code=404, detail="Flag group not found")

    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    if len(name) > 200:
        raise HTTPException(status_code=400, detail="name too long (max 200)")

    # Reject duplicate flag names on the same trailer — two flags sharing a
    # name would make bom_conditions unpredictable (the condition string
    # would match both masters). Case + whitespace insensitive comparison so
    # "FRONT EPS" and " front eps " can't both exist on this trailer.
    target = name.strip().lower()
    existing_dupe = next((
        m for m in db.query(BillOfMaterial)
        .filter_by(trailer_type_id=trailer.id, is_body_option=True)
        .all()
        if m.material and (m.material.name or "").strip().lower() == target
    ), None)
    if existing_dupe is not None:
        raise HTTPException(
            status_code=409,
            detail=f'A flag/option named "{existing_dupe.material.name}" already exists on this trailer (master id {existing_dupe.id}).',
        )

    # Find or create the Material row so the flag has a backing material.
    mat = db.query(Material).filter(Material.name == name).first()
    if not mat:
        mat = Material(name=name, unit_of_measure="each", price_per_unit=0.0)
        db.add(mat)
        db.flush()

    flag = BillOfMaterial(
        trailer_type_id=trailer.id,
        material_id=mat.id,
        is_body_option=True,
        body_option_default=False,
        body_option_group_id=grp.id,
        body_option_group=grp.name,
        body_option_subgroup=grp.name,
        selection_mode="multi",
        selection_group=None,
        sort_order=0,
        formula_expression="1",
        waste_percentage=0,
    )
    db.add(flag)
    db.commit()
    return {"id": flag.id, "groupId": grp.id, "name": name}


@router.patch("/api/configurator/flags/{master_id}/rename")
async def configurator_rename_flag(
    master_id: int, payload: dict, request: Request, db: Session = Depends(get_db),
):
    """Rename a flag/option master (i.e. its backing Material row).

    Payload: { "name": <str> }

    Also rewrites every bom_conditions reference on this trailer from the old
    name to the new one, so existing rules keep pointing at the same toggle.
    Useful for both flag rows (inside a flag group) and gate-option masters.
    """
    _require_admin_api(request, db)
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    if len(name) > 200:
        raise HTTPException(status_code=400, detail="name too long (max 200)")

    master = db.query(BillOfMaterial).filter_by(id=master_id, is_body_option=True).first()
    if not master:
        raise HTTPException(status_code=404, detail="Flag/option master not found")
    if not master.material:
        raise HTTPException(status_code=400, detail="Master has no backing material row")

    old_name = master.material.name
    if old_name == name:
        return {"id": master.id, "name": name, "renamedConditionItemIds": []}

    # Update the material's display name. Note: if another BillOfMaterial
    # row shares this material_id, those rows show the new name too — which
    # is normally fine, since the material is the same concept.
    master.material.name = name

    # Cascade: rewrite bom_conditions on this trailer's items.
    import json as _json
    items = (
        db.query(BillOfMaterial)
        .filter_by(trailer_type_id=master.trailer_type_id, is_body_option=False)
        .filter(BillOfMaterial.bom_conditions.isnot(None))
        .all()
    )
    touched = []
    for r in items:
        raw = r.bom_conditions
        if not raw or old_name not in raw:
            continue
        try:
            parsed = _json.loads(raw)
        except (ValueError, TypeError):
            continue
        dirty = False
        if isinstance(parsed, list):
            for c in parsed:
                if isinstance(c, dict) and (c.get("option") or "").strip() == old_name:
                    c["option"] = name
                    dirty = True
        elif isinstance(parsed, dict):
            for c in (parsed.get("all") or []):
                if isinstance(c, dict) and (c.get("option") or "").strip() == old_name:
                    c["option"] = name
                    dirty = True
        if dirty:
            r.bom_conditions = _json.dumps(parsed)
            touched.append(r.id)

    db.commit()
    return {"id": master.id, "name": name, "renamedConditionItemIds": touched}


@router.patch("/api/configurator/flags/{master_id}/unbind-section")
async def configurator_unbind_flag_section(
    master_id: int, request: Request, db: Session = Depends(get_db),
):
    """Clear bom_section_id on a flag master so it returns to its flag group."""
    _require_admin_api(request, db)
    row = db.query(BillOfMaterial).filter_by(id=master_id, is_body_option=True).first()
    if not row:
        raise HTTPException(status_code=404, detail="Flag not found")
    row.bom_section_id = None
    row.bom_section = None
    db.commit()
    return {"ok": True, "id": row.id}


@router.post("/api/configurator/trailers/{trailer_id}/sections")
async def configurator_create_section(
    trailer_id: int, payload: dict, request: Request, db: Session = Depends(get_db),
):
    """Create a new BOMSection and (optionally) link it to a choice-gate option.

    Payload:
      { "name": <str>, "optionMasterId": <int|null> }

    - name: required, max 100 chars.
    - optionMasterId: when set, the section's `body_option_master_id` FK is set
      to that master id (the gate option owns the new section). When NULL,
      the section is created free-floating (will appear in Always include).
    """
    _require_admin_api(request, db)
    trailer = db.query(TrailerType).filter_by(id=trailer_id, is_active=True).first()
    if not trailer:
        raise HTTPException(status_code=404, detail="Trailer not found")

    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    if len(name) > 100:
        raise HTTPException(status_code=400, detail="name too long (max 100)")

    option_master_id = payload.get("optionMasterId")
    if option_master_id is not None:
        try:
            option_master_id = int(option_master_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="optionMasterId must be int or null")
        master = db.query(BillOfMaterial).filter_by(
            id=option_master_id, trailer_type_id=trailer.id, is_body_option=True,
        ).first()
        if not master:
            raise HTTPException(status_code=404, detail="Master option not found on this trailer")

    sec = BOMSection(
        name=name,
        sort_order=0,
        body_option_master_id=option_master_id,
    )
    db.add(sec)
    db.commit()
    return {"id": sec.id, "name": sec.name, "body_option_master_id": sec.body_option_master_id}


@router.post("/api/configurator/sections/{section_id}/move-items")
async def configurator_move_items_to_section(
    section_id: int, payload: dict, request: Request, db: Session = Depends(get_db),
):
    """Move one or more BOM item rows into this section.

    Payload: { "itemIds": [<int>, ...] }

    Updates each row's bom_section_id (the FK that drives section grouping).
    Body-option master rows are not movable — they belong to their group, not
    a section. Each itemId is silently skipped if it isn't a non-master row
    on the same trailer as the section.
    """
    _require_admin_api(request, db)

    sec = db.query(BOMSection).filter_by(id=section_id).first()
    if not sec:
        raise HTTPException(status_code=404, detail="Section not found")

    raw_ids = payload.get("itemIds") or []
    try:
        ids = [int(x) for x in raw_ids if x is not None]
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="itemIds must be ints")
    if not ids:
        raise HTTPException(status_code=400, detail="itemIds required")

    # Sections are global rows that multiple trailers can reference, so we
    # can't determine "this section's trailer" from the section alone. Instead,
    # require every item-being-moved to belong to the same trailer (so we
    # never accidentally cross-pollinate trailers in one call).
    rows = db.query(BillOfMaterial).filter(BillOfMaterial.id.in_(ids)).all()
    trailer_ids = {r.trailer_type_id for r in rows}
    if len(trailer_ids) > 1:
        raise HTTPException(status_code=400, detail="All items must be from the same trailer")

    moved = []
    for row in rows:
        # Allow body-option masters (flag rows) to be moved too — the
        # configurator now uses this endpoint both to relocate plain BOM
        # items and to attach flag masters to sections. We only update
        # bom_section_id / bom_section; is_body_option is preserved so the
        # row keeps its flag-toggle semantics in its existing group.
        row.bom_section_id = sec.id
        row.bom_section = sec.name  # legacy string column, kept in sync
        moved.append(row.id)

    db.commit()
    return {"ok": True, "sectionId": sec.id, "movedItemIds": moved}


@router.patch("/api/configurator/items/{item_id}/conditions")
async def configurator_set_item_conditions(
    item_id: int, payload: dict, request: Request, db: Session = Depends(get_db)
):
    """Persist per-item AND-conditions as JSON on bill_of_materials.bom_conditions.

    Payload: {"conditions": [{"option": "BAKERY BODY", "equals": "Y"}, ...]}
    An empty list means "always include" (column set to NULL).
    """
    _require_admin_api(request, db)

    raw = payload.get("conditions")
    mode = (payload.get("mode") or "include").lower()
    if mode not in ("include", "exclude", "always_exclude"):
        raise HTTPException(status_code=400, detail="mode must be 'include', 'exclude', or 'always_exclude'")
    if raw is None:
        raise HTTPException(status_code=400, detail="conditions required (use [] for always-include)")
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="conditions must be a list")

    # Resolve the item's trailer up-front so we can auto-attach option_id by
    # finding the matching BOM master on the same trailer (rename-safe linkage).
    target_item = db.query(BillOfMaterial).filter_by(id=item_id).first()
    target_trailer_id = target_item.trailer_type_id if target_item else None
    # Build name → preferred-master-id map (BODY OPTIONS-section masters first,
    # then any body_option master) once per request.
    auto_map: dict[str, int] = {}
    if target_trailer_id is not None:
        trailer_masters = (
            db.query(BillOfMaterial)
            .filter(BillOfMaterial.trailer_type_id == target_trailer_id,
                    BillOfMaterial.is_body_option == True)
            .all()
        )
        for r in trailer_masters:
            if r.material and r.material.name and (r.bom_section or "").upper() == "BODY OPTIONS":
                auto_map.setdefault(r.material.name, r.id)
        for r in trailer_masters:
            if r.material and r.material.name:
                auto_map.setdefault(r.material.name, r.id)

    cleaned = []
    for c in raw:
        if not isinstance(c, dict):
            raise HTTPException(status_code=400, detail="each condition must be an object")
        opt = (c.get("option") or "").strip()
        eq = (c.get("equals") or "Y").upper()
        if not opt:
            raise HTTPException(status_code=400, detail="condition.option required")
        if eq not in ("Y", "N"):
            raise HTTPException(status_code=400, detail="condition.equals must be 'Y' or 'N'")
        # option_id (BOM master row id) lets evaluation key off the master ID rather
        # than the text name — survives material renames. If the client didn't send
        # one, auto-resolve via the trailer's master-name map so newly-saved rules
        # are ID-anchored from day one.
        entry = {"option": opt, "equals": eq}
        opt_id = c.get("option_id")
        if opt_id is None:
            opt_id = auto_map.get(opt)
        if opt_id is not None:
            try:
                entry["option_id"] = int(opt_id)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="condition.option_id must be an integer")
        cleaned.append(entry)

    # Exclude mode with zero conditions would mean "always exclude" (vacuous truth) —
    # reject so a misclick doesn't silently hide the item. Use mode='always_exclude' instead.
    if mode == "exclude" and not cleaned:
        raise HTTPException(
            status_code=400,
            detail="exclude mode requires at least one condition (use mode='always_exclude' to hide unconditionally)",
        )

    row = db.query(BillOfMaterial).filter_by(id=item_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Item not found")

    if mode == "always_exclude":
        # Item is unconditionally hidden — no conditions needed.
        row.bom_conditions = json.dumps({"mode": "always_exclude"})
    elif not cleaned:
        # include mode + no conditions = "always include" → store as NULL.
        row.bom_conditions = None
    elif mode == "exclude":
        row.bom_conditions = json.dumps({"mode": "exclude", "all": cleaned})
    else:
        # Stay backwards-compatible: implicit include mode uses the legacy list form.
        row.bom_conditions = json.dumps(cleaned)
    db.commit()
    return {"id": row.id, "conditions": cleaned, "mode": mode}
