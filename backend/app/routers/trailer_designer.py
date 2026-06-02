from fastapi import Request, APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..database import (
    get_db, TrailerType, Material, MaterialCategory,
    BillOfMaterial, BOMSection, BodyOptionGroup,
)
from ..deps import get_current_user, require_admin
from ..services import _resolve_bom_section, _resolve_body_option_group, _resolve_body_option_subgroup
from ..templates_config import templates

router = APIRouter()


@router.get("/admin/trailer-designer", response_class=HTMLResponse)
async def admin_trailer_designer(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or user.role != "admin":
        return RedirectResponse(url="/login")
    materials = (db.query(Material, MaterialCategory)
                 .outerjoin(MaterialCategory, Material.category_id == MaterialCategory.id)
                 .filter(Material.is_active == True)
                 .order_by(MaterialCategory.name, Material.name)
                 .all())
    cats = db.query(MaterialCategory).order_by(MaterialCategory.name).all()
    mat_list = [{
        "id": m.id, "name": m.name,
        "unit": m.unit_of_measure or "",
        "price": float(m.price_per_unit or 0),
        "category": c.name if c else "Uncategorised",
        "category_id": c.id if c else None,
    } for m, c in materials]
    cat_list = [{"id": c.id, "name": c.name} for c in cats]

    seen_ids = set()
    body_opt_list = []
    bo_rows = (db.query(BillOfMaterial, Material)
               .join(Material, BillOfMaterial.material_id == Material.id)
               .filter(BillOfMaterial.is_body_option == True, Material.is_active == True)
               .order_by(BillOfMaterial.body_option_group, Material.name)
               .all())
    for bom, mat in bo_rows:
        key = (mat.id, bom.body_option_group or "")
        if key not in seen_ids:
            seen_ids.add(key)
            body_opt_list.append({
                "id": mat.id, "name": mat.name,
                "unit": mat.unit_of_measure or "",
                "price": float(mat.price_per_unit or 0),
                "group": (bom.body_option_group or "").upper(),
                "subgroup": (bom.body_option_subgroup or "").upper(),
            })

    bog_rows = (db.query(BodyOptionGroup)
                .order_by(BodyOptionGroup.sort_order, BodyOptionGroup.name).all())
    bog_list = [{"id": g.id, "name": g.name,
                 "bom_section_id":   g.bom_section_id,
                 "bom_section_name": g.bom_section.name if g.bom_section else None}
                for g in bog_rows]

    sec_rows = (db.query(BOMSection)
                .order_by(BOMSection.sort_order, BOMSection.name).all())
    sec_list = [{"id": s.id, "name": s.name} for s in sec_rows]

    return templates.TemplateResponse("trailer_designer.html", {
        "request": request, "user": user,
        "materials": mat_list, "categories": cat_list,
        "body_opt_mats": body_opt_list,
        "body_opt_groups": bog_list,
        "bom_sections": sec_list,
    })


@router.post("/api/trailer-designer/save")
async def trailer_designer_save(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Trailer name is required")
    if db.query(TrailerType).filter_by(name=name).first():
        raise HTTPException(status_code=400, detail=f"Trailer type '{name}' already exists")

    raw_markup = body.get("markup_percentage")
    markup_pct = float(raw_markup) if raw_markup is not None else 0.0
    tt = TrailerType(
        name=name,
        description=body.get("description", ""),
        default_length=float(body.get("default_length") or 12),
        default_width=float(body.get("default_width") or 2.45),
        default_height=float(body.get("default_height") or 2.2),
        markup_percentage=markup_pct,
        is_active=True,
    )
    db.add(tt)
    db.flush()

    bom_rows_added = 0
    _body_opt_sec_id = _resolve_bom_section(db, "BODY OPTIONS")
    _zone_sec_ids: dict = {}
    _zone_grp_ids: dict = {}
    for zone_name, zone_data in body.get("zones", {}).items():
        if zone_name not in _zone_sec_ids:
            _zone_sec_ids[zone_name] = _resolve_bom_section(db, zone_name)
        if zone_name not in _zone_grp_ids:
            _zone_grp_ids[zone_name] = _resolve_body_option_group(db, zone_name)
        for opt in zone_data.get("body_options", []):
            mat = db.query(Material).filter_by(id=opt["material_id"]).first()
            if not mat:
                continue
            grp_id = _zone_grp_ids.get(zone_name)
            sub_name = (opt.get("subgroup") or "").upper() or None
            sub_id = _resolve_body_option_subgroup(db, grp_id, sub_name) if (grp_id and sub_name) else None
            row = BillOfMaterial(
                trailer_type_id=tt.id,
                material_id=mat.id,
                formula_expression="1",
                waste_percentage=0,
                bom_section="BODY OPTIONS",
                bom_section_id=_body_opt_sec_id,
                is_body_option=True,
                body_option_group=zone_name,
                body_option_group_id=grp_id,
                body_option_subgroup=sub_name,
                body_option_subgroup_id=sub_id,
                body_option_default=bool(opt.get("is_default", False)),
                sort_order=int(opt.get("sort_order") or 0),
                unit_price_snapshot=float(mat.price_per_unit or 0),
            )
            db.add(row)
            bom_rows_added += 1
        for item in zone_data.get("bom_items", []):
            mat = db.query(Material).filter_by(id=item["material_id"]).first()
            if not mat:
                continue
            linked_name = item.get("linked_option") or None
            linked_id = None
            if linked_name:
                lm = db.query(Material).filter_by(name=linked_name).first()
                linked_id = lm.id if lm else None
            row = BillOfMaterial(
                trailer_type_id=tt.id,
                material_id=mat.id,
                formula_expression=item.get("formula") or "1",
                waste_percentage=float(item.get("waste_pct") or 0),
                bom_section=zone_name,
                bom_section_id=_zone_sec_ids.get(zone_name),
                is_body_option=False,
                body_option_linked=linked_name,
                body_option_linked_id=linked_id,
                sort_order=int(item.get("sort_order") or 0),
                unit_price_snapshot=float(mat.price_per_unit or 0),
            )
            db.add(row)
            bom_rows_added += 1

    _extra_sec_ids: dict = {}
    for sec_name, sec_data in body.get("extra_sections", {}).items():
        sec_name_upper = sec_name.upper()
        if sec_name_upper not in _extra_sec_ids:
            _extra_sec_ids[sec_name_upper] = _resolve_bom_section(db, sec_name_upper)
        sec_id = _extra_sec_ids[sec_name_upper]
        for item in sec_data.get("bom_items", []):
            mat = db.query(Material).filter_by(id=item["material_id"]).first()
            if not mat:
                continue
            linked_name = item.get("linked_option") or None
            linked_id = None
            if linked_name:
                lm = db.query(Material).filter_by(name=linked_name).first()
                linked_id = lm.id if lm else None
            row = BillOfMaterial(
                trailer_type_id=tt.id,
                material_id=mat.id,
                formula_expression=item.get("formula") or "1",
                waste_percentage=float(item.get("waste_pct") or 0),
                bom_section=sec_name_upper,
                bom_section_id=sec_id,
                is_body_option=False,
                body_option_linked=linked_name,
                body_option_linked_id=linked_id,
                sort_order=int(item.get("sort_order") or 0),
                unit_price_snapshot=float(mat.price_per_unit or 0),
            )
            db.add(row)
            bom_rows_added += 1

    db.commit()
    return {"ok": True, "trailer_id": tt.id, "trailer_name": tt.name, "bom_rows": bom_rows_added}
