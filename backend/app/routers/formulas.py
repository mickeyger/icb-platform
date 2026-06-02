import re
from collections import defaultdict

from fastapi import Request, APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db, Formula, TrailerType, BillOfMaterial, Material, GlobalVariable
from ..deps import require_admin

_WASTE_RE = re.compile(r"(?<![.\d])0\.05(?!\d)")

router = APIRouter()


@router.get("/api/formulas")
async def get_formulas(db: Session = Depends(get_db)):
    fs = db.query(Formula).filter_by(is_active=True).order_by(Formula.name).all()
    return [{"id": f.id, "name": f.name, "description": f.description or "",
             "expression": f.expression} for f in fs]


@router.post("/api/formulas")
async def create_formula(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    f = Formula(name=body["name"], description=body.get("description", ""),
                expression=body["expression"])
    db.add(f)
    db.commit()
    db.refresh(f)
    return {"id": f.id}


@router.put("/api/formulas/{f_id}")
async def update_formula(f_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    f = db.query(Formula).filter_by(id=f_id).first()
    if not f:
        raise HTTPException(status_code=404)
    for k in ["name", "description", "expression", "is_active"]:
        if k in body:
            setattr(f, k, body[k])
    db.commit()
    return {"ok": True}


@router.delete("/api/formulas/{f_id}")
async def delete_formula(f_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    f = db.query(Formula).filter_by(id=f_id).first()
    if f:
        f.is_active = False
        db.commit()
    return {"ok": True}


@router.get("/api/formulas/apply-targets")
async def get_apply_targets(db: Session = Depends(get_db)):
    """All active body types with their BOM items, for the formula-apply checklist."""
    rows = (
        db.query(BillOfMaterial, TrailerType, Material)
        .join(TrailerType, BillOfMaterial.trailer_type_id == TrailerType.id)
        .join(Material, BillOfMaterial.material_id == Material.id)
        .filter(TrailerType.is_active == True)
        .order_by(TrailerType.name, BillOfMaterial.sort_order)
        .all()
    )
    groups: dict = defaultdict(list)
    tt_names: dict = {}
    for bom, tt, mat in rows:
        tt_names[tt.id] = tt.name
        price = float(bom.unit_price_override if bom.unit_price_override is not None
                      else (mat.price_per_unit or 0))
        groups[tt.id].append({
            "bom_id": bom.id,
            "material_name": mat.name,
            "unit_price": round(price, 4),
            "current_formula": bom.formula_expression or "1",
            "bom_section": bom.bom_section or "",
        })
    return [
        {"id": tt_id, "name": tt_names[tt_id], "items": groups[tt_id]}
        for tt_id in sorted(tt_names, key=lambda x: tt_names[x])
    ]


@router.post("/api/formulas/apply")
async def apply_formula_to_bom(request: Request, db: Session = Depends(get_db)):
    """Set formula_expression on a list of BOM item IDs."""
    require_admin(request, db)
    body = await request.json()
    expression = (body.get("expression") or "").strip()
    bom_ids = body.get("bom_ids") or []
    if not expression:
        raise HTTPException(status_code=400, detail="Expression is required")
    if not bom_ids:
        raise HTTPException(status_code=400, detail="No BOM items selected")
    updated = 0
    for bom_id in bom_ids:
        row = db.query(BillOfMaterial).filter_by(id=int(bom_id)).first()
        if row:
            row.formula_expression = expression
            updated += 1
    db.commit()
    return {"updated": updated}


# ── Global Variables ──────────────────────────────────────────────────────────

@router.get("/api/global-variables")
async def get_global_variables(db: Session = Depends(get_db)):
    rows = db.query(GlobalVariable).order_by(GlobalVariable.name).all()
    return [{"id": r.id, "name": r.name, "value": r.value,
             "description": r.description or ""} for r in rows]


@router.post("/api/global-variables")
async def create_global_variable(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    if db.query(GlobalVariable).filter_by(name=name).first():
        raise HTTPException(status_code=400, detail="Name already exists")
    gv = GlobalVariable(name=name, value=float(body.get("value") or 0),
                        description=body.get("description", ""))
    db.add(gv)
    db.commit()
    db.refresh(gv)
    return {"id": gv.id}


@router.put("/api/global-variables/{gv_id}")
async def update_global_variable(gv_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    gv = db.query(GlobalVariable).filter_by(id=gv_id).first()
    if not gv:
        raise HTTPException(status_code=404)
    if "name" in body:
        gv.name = (body["name"] or "").strip()
    if "value" in body:
        gv.value = float(body["value"])
    if "description" in body:
        gv.description = body["description"]
    db.commit()
    return {"ok": True}


@router.delete("/api/global-variables/{gv_id}")
async def delete_global_variable(gv_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    gv = db.query(GlobalVariable).filter_by(id=gv_id).first()
    if gv:
        db.delete(gv)
        db.commit()
    return {"ok": True}


@router.get("/api/global-variables/waste-migration-preview")
async def waste_migration_preview(db: Session = Depends(get_db)):
    """Count BOM formulas that contain the literal 0.05 and preview replacements."""
    rows = db.query(BillOfMaterial).filter(
        BillOfMaterial.formula_expression.isnot(None)
    ).all()
    affected = []
    for row in rows:
        expr = row.formula_expression or ""
        if _WASTE_RE.search(expr):
            affected.append({
                "bom_id": row.id,
                "before": expr,
                "after": _WASTE_RE.sub("{Waste}", expr),
            })
    return {"count": len(affected), "items": affected}


@router.post("/api/global-variables/waste-migration-apply")
async def waste_migration_apply(request: Request, db: Session = Depends(get_db)):
    """Replace literal 0.05 with {Waste} in all BOM formula expressions."""
    require_admin(request, db)
    rows = db.query(BillOfMaterial).filter(
        BillOfMaterial.formula_expression.isnot(None)
    ).all()
    updated = 0
    for row in rows:
        expr = row.formula_expression or ""
        new_expr = _WASTE_RE.sub("{Waste}", expr)
        if new_expr != expr:
            row.formula_expression = new_expr
            updated += 1
    db.commit()
    return {"updated": updated}
