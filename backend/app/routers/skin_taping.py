import ast as _ast
import math as _math

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..database import (
    get_db,
    SkinFormula, SkinFormulaItem, SkinFormulaIngredient,
    TapingBlock, TapingBlockItem, SapItemCode,
    FloorPlate, FloorPlateItem,
    MountingCleat, MountingCleatItem,
)
from ..deps import get_current_user, require_admin, user_can
from ..services import (
    _compute_skin_formula_cost, _compute_taping_block_cost, _serialize_taping_block,
    _compute_floor_plate_cost, _serialize_floor_plate,
    _compute_mounting_cleat_cost, _serialize_mounting_cleat,
)
from ..templates_config import templates

router = APIRouter()


def _eval_qty_formula(expr: str) -> float:
    """Evaluate a simple arithmetic formula for qty_per_m2 (admin-only, AST-validated)."""
    s = str(expr).strip()
    try:
        return float(s)          # plain number fast path
    except ValueError:
        pass
    try:
        tree = _ast.parse(s, mode='eval')
    except SyntaxError as exc:
        raise ValueError(f"Invalid formula syntax: {exc}") from exc
    _allowed = {
        _ast.Expression, _ast.BinOp, _ast.UnaryOp, _ast.Constant,
        _ast.Add, _ast.Sub, _ast.Mult, _ast.Div, _ast.FloorDiv, _ast.Mod, _ast.Pow,
        _ast.UAdd, _ast.USub, _ast.Call, _ast.Name, _ast.Load,
    }
    for node in _ast.walk(tree):
        if type(node) not in _allowed:
            raise ValueError(f"Unsupported expression element: {type(node).__name__}")
    _env = {
        "__builtins__": {},
        "pi": _math.pi, "PI": _math.pi, "e": _math.e, "E": _math.e,
        "sqrt": _math.sqrt, "abs": abs, "pow": _math.pow,
        "ceil": _math.ceil, "floor": _math.floor, "round": round,
    }
    result = eval(compile(tree, "<qty_formula>", "eval"), _env)  # noqa: S307
    return float(result)


# ─── Skin Formulas ────────────────────────────────────────────────────────────

@router.get("/api/skin-formulas")
async def list_skin_formulas(db: Session = Depends(get_db)):
    formulas = (db.query(SkinFormula)
                .filter_by(is_active=True)
                .order_by(SkinFormula.sort_order, SkinFormula.name).all())
    result = []
    for f in formulas:
        result.append({
            "id": f.id, "name": f.name, "description": f.description or "",
            "sort_order": f.sort_order,
            "cost_standard": _compute_skin_formula_cost(f, "standard"),
            "cost_kzn":      _compute_skin_formula_cost(f, "kzn"),
            "cost_sap":      _compute_skin_formula_cost(f, "sap"),
            "items": [
                {
                    "id":             it.id,
                    "ingredient_id":  it.ingredient_id,
                    "ingredient_name": it.ingredient.name if it.ingredient else "",
                    "sap_code":       it.ingredient.sap_code or "" if it.ingredient else "",
                    "qty_per_m2":     it.qty_per_m2,
                    "qty_formula":    getattr(it, "qty_formula", "") or "",
                    "sort_order":     it.sort_order,
                    "price_source":   getattr(it, "price_source", "standard") or "standard",
                    "price_standard": it.ingredient.price_standard if it.ingredient else 0,
                    "price_kzn":      it.ingredient.price_kzn if it.ingredient else 0,
                    "price_sap":      (it.ingredient.sap_item.last_purch_price
                                       if it.ingredient and it.ingredient.sap_item else None),
                    "line_std":  round((it.ingredient.price_standard if it.ingredient else 0) * it.qty_per_m2, 4),
                    "line_kzn":  round((it.ingredient.price_kzn if it.ingredient else 0) * it.qty_per_m2, 4),
                    "line_sap":  round(
                        (it.ingredient.sap_item.last_purch_price
                         if it.ingredient and it.ingredient.sap_item else 0) * it.qty_per_m2, 4),
                }
                for it in f.items
            ],
        })
    return result


@router.post("/api/skin-formulas")
async def create_skin_formula(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    f = SkinFormula(
        name=body["name"].strip(),
        description=body.get("description", ""),
        sort_order=body.get("sort_order", 0),
        is_active=True,
    )
    db.add(f)
    db.flush()
    for item in body.get("items", []):
        raw_formula = str(item.get("qty_formula") or "").strip()
        try:
            qty = _eval_qty_formula(raw_formula) if raw_formula else float(item["qty_per_m2"])
        except (ValueError, ZeroDivisionError):
            qty = float(item["qty_per_m2"])
        db.add(SkinFormulaItem(
            formula_id=f.id,
            ingredient_id=item["ingredient_id"],
            qty_per_m2=qty,
            qty_formula=raw_formula or None,
            sort_order=item.get("sort_order", 0),
            price_source=item.get("price_source", "standard"),
        ))
    db.commit()
    db.refresh(f)
    return {"id": f.id}


@router.put("/api/skin-formulas/{f_id}")
async def update_skin_formula(f_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    f = db.query(SkinFormula).filter_by(id=f_id).first()
    if not f:
        raise HTTPException(status_code=404)
    for k in ["name", "description", "sort_order", "is_active"]:
        if k in body:
            setattr(f, k, body[k])
    if "items" in body:
        for old in list(f.items):
            db.delete(old)
        db.flush()
        for item in body["items"]:
            raw_formula = str(item.get("qty_formula") or "").strip()
            try:
                qty = _eval_qty_formula(raw_formula) if raw_formula else float(item["qty_per_m2"])
            except (ValueError, ZeroDivisionError):
                qty = float(item["qty_per_m2"])
            db.add(SkinFormulaItem(
                formula_id=f.id,
                ingredient_id=item["ingredient_id"],
                qty_per_m2=qty,
                qty_formula=raw_formula or None,
                sort_order=item.get("sort_order", 0),
                price_source=item.get("price_source", "standard"),
            ))
    db.commit()
    return {"ok": True}


@router.delete("/api/skin-formulas/{f_id}")
async def delete_skin_formula(f_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    f = db.query(SkinFormula).filter_by(id=f_id).first()
    if f:
        f.is_active = False
        db.commit()
    return {"ok": True}


# ─── Skin Formula Ingredients ─────────────────────────────────────────────────

@router.get("/api/skin-formula-ingredients")
async def list_skin_formula_ingredients(db: Session = Depends(get_db)):
    rows = (db.query(SkinFormulaIngredient)
            .filter_by(is_active=True)
            .order_by(SkinFormulaIngredient.sort_order, SkinFormulaIngredient.name).all())
    return [
        {
            "id": r.id, "name": r.name, "sap_code": r.sap_code or "",
            "price_standard": r.price_standard, "price_kzn": r.price_kzn,
            "sort_order": r.sort_order,
            "sap_item_code_id": r.sap_item_code_id,
            "sap_last_purch_price": r.sap_item.last_purch_price if r.sap_item else None,
            "sap_item_code": r.sap_item.item_code if r.sap_item else None,
        }
        for r in rows
    ]


@router.post("/api/skin-formula-ingredients")
async def create_skin_formula_ingredient(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    ing = SkinFormulaIngredient(
        name=body["name"].strip(),
        sap_code=body.get("sap_code", ""),
        price_standard=float(body.get("price_standard", 0)),
        price_kzn=float(body.get("price_kzn", 0)),
        sort_order=body.get("sort_order", 0),
        is_active=True,
    )
    db.add(ing)
    db.commit()
    db.refresh(ing)
    return {"id": ing.id}


@router.put("/api/skin-formula-ingredients/{ing_id}")
async def update_skin_formula_ingredient(ing_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    ing = db.query(SkinFormulaIngredient).filter_by(id=ing_id).first()
    if not ing:
        raise HTTPException(status_code=404)
    for k in ["name", "sap_code", "price_standard", "price_kzn", "sort_order", "is_active"]:
        if k in body:
            setattr(ing, k, body[k])
    if "sap_item_code_id" in body:
        ing.sap_item_code_id = int(body["sap_item_code_id"]) if body["sap_item_code_id"] else None
    if "sap_last_purch_price" in body and ing.sap_item:
        ing.sap_item.last_purch_price = float(body["sap_last_purch_price"])
    db.commit()
    return {"ok": True}


@router.put("/api/skin-formula-ingredients/{ing_id}/inline-price")
async def inline_update_skin_ingredient_price(ing_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user_can(user, "recipes.edit_inline", db):
        raise HTTPException(status_code=403, detail="Permission denied")
    body = await request.json()
    ing = db.query(SkinFormulaIngredient).filter_by(id=ing_id).first()
    if not ing:
        raise HTTPException(status_code=404)
    if "price_standard" in body:
        ing.price_standard = float(body["price_standard"])
    if "price_kzn" in body:
        ing.price_kzn = float(body["price_kzn"])
    db.commit()
    return {"ok": True}


@router.post("/api/skin-formula-ingredients/{ing_id}/sync-sap")
async def sync_ingredient_from_sap(ing_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    ing = db.query(SkinFormulaIngredient).filter_by(id=ing_id).first()
    if not ing:
        raise HTTPException(status_code=404, detail="Ingredient not found")
    if not ing.sap_item_code_id:
        raise HTTPException(status_code=400, detail="No SAP item code linked to this ingredient")
    sap = db.query(SapItemCode).filter_by(id=ing.sap_item_code_id).first()
    if not sap:
        raise HTTPException(status_code=404, detail="SAP item code not found")
    ing.price_kzn = sap.last_purch_price
    db.commit()
    return {"ok": True, "price_kzn": ing.price_kzn, "item_code": sap.item_code}


@router.patch("/api/skin-formula-items/{item_id}/price-source")
async def update_recipe_item_price_source(item_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    source = body.get("price_source", "standard")
    if source not in ("standard", "sap"):
        raise HTTPException(status_code=400, detail="price_source must be 'standard' or 'sap'")
    item = db.query(SkinFormulaItem).filter_by(id=item_id).first()
    if not item:
        raise HTTPException(status_code=404)
    item.price_source = source
    db.commit()
    return {"ok": True}


# ─── SAP Item Codes ───────────────────────────────────────────────────────────

@router.get("/api/sap-item-codes")
async def list_sap_item_codes(
    q: str = "", page: int = 1, per_page: int = 50,
    db: Session = Depends(get_db)
):
    query = db.query(SapItemCode)
    if q.strip():
        query = query.filter(SapItemCode.item_code.ilike(f"%{q.strip()}%"))
    total = query.count()
    rows = query.order_by(SapItemCode.item_code).offset((page - 1) * per_page).limit(per_page).all()
    return {
        "total": total, "page": page, "per_page": per_page,
        "items": [{"id": r.id, "item_code": r.item_code,
                   "last_purch_price": r.last_purch_price, "is_active": r.is_active} for r in rows],
    }


@router.get("/api/sap-item-codes/{sap_id}")
async def get_sap_item_code(sap_id: int, db: Session = Depends(get_db)):
    r = db.query(SapItemCode).filter_by(id=sap_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Not found")
    return {"id": r.id, "item_code": r.item_code,
            "last_purch_price": r.last_purch_price, "is_active": r.is_active}


@router.put("/api/sap-item-codes/{sap_id}")
async def update_sap_item_code(sap_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    r = db.query(SapItemCode).filter_by(id=sap_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Not found")
    body = await request.json()
    if "last_purch_price" in body:
        r.last_purch_price = float(body["last_purch_price"])
    if "is_active" in body:
        r.is_active = bool(body["is_active"])
    db.commit()
    return {"ok": True}


@router.post("/api/sap-item-codes")
async def create_sap_item_code(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    code = body.get("item_code", "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="item_code required")
    existing = db.query(SapItemCode).filter_by(item_code=code).first()
    if existing:
        raise HTTPException(status_code=409, detail="Item code already exists")
    r = SapItemCode(item_code=code, last_purch_price=float(body.get("last_purch_price", 0)), is_active=True)
    db.add(r)
    db.commit()
    db.refresh(r)
    return {"id": r.id}


# ─── Taping Blocks ────────────────────────────────────────────────────────────

@router.get("/api/taping-blocks")
async def list_taping_blocks(db: Session = Depends(get_db)):
    blocks = (db.query(TapingBlock)
              .filter_by(is_active=True)
              .order_by(TapingBlock.sort_order, TapingBlock.name).all())
    return [_serialize_taping_block(b) for b in blocks]


@router.post("/api/taping-blocks")
async def create_taping_block(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    b = TapingBlock(
        name=body["name"].strip(),
        description=body.get("description", ""),
        size_mm=body.get("size_mm"),
        sort_order=body.get("sort_order", 0),
        is_active=True,
    )
    db.add(b)
    db.flush()
    for idx, item in enumerate(body.get("items", [])):
        db.add(TapingBlockItem(
            block_id=b.id,
            item_name=item["item_name"],
            sap_code=item.get("sap_code") or None,
            sap_item_code_id=item.get("sap_item_code_id"),
            length=float(item.get("length", 0)),
            width=float(item.get("width", 0)),
            m2=float(item.get("m2", 0)),
            price_per_unit=float(item.get("price_per_unit", 0)),
            price_source=item.get("price_source", "standard"),
            quantity=float(item.get("quantity", 1)),
            sort_order=item.get("sort_order", idx * 10),
        ))
    db.commit()
    db.refresh(b)
    return {"id": b.id}


@router.put("/api/taping-blocks/{b_id}")
async def update_taping_block(b_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    b = db.query(TapingBlock).filter_by(id=b_id).first()
    if not b:
        raise HTTPException(status_code=404)
    for k in ["name", "description", "size_mm", "sort_order", "is_active"]:
        if k in body:
            setattr(b, k, body[k])
    if "items" in body:
        for old in list(b.items):
            db.delete(old)
        db.flush()
        for idx, item in enumerate(body["items"]):
            db.add(TapingBlockItem(
                block_id=b.id,
                item_name=item["item_name"],
                sap_code=item.get("sap_code") or None,
                sap_item_code_id=item.get("sap_item_code_id"),
                length=float(item.get("length", 0)),
                width=float(item.get("width", 0)),
                m2=float(item.get("m2", 0)),
                price_per_unit=float(item.get("price_per_unit", 0)),
                price_source=item.get("price_source", "standard"),
                quantity=float(item.get("quantity", 1)),
                sort_order=item.get("sort_order", idx * 10),
            ))
    db.commit()
    return {"ok": True}


@router.delete("/api/taping-blocks/{b_id}")
async def delete_taping_block(b_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    b = db.query(TapingBlock).filter_by(id=b_id).first()
    if b:
        b.is_active = False
        db.commit()
    return {"ok": True}


@router.put("/api/taping-block-items/{item_id}/inline-price")
async def inline_update_taping_item_price(item_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user_can(user, "recipes.edit_inline", db):
        raise HTTPException(status_code=403, detail="Permission denied")
    body = await request.json()
    it = db.query(TapingBlockItem).filter_by(id=item_id).first()
    if not it:
        raise HTTPException(status_code=404)
    if "price_per_unit" in body:
        it.price_per_unit = float(body["price_per_unit"])
    if "quantity" in body:
        it.quantity = float(body["quantity"])
    db.commit()
    return {"ok": True}


@router.patch("/api/taping-block-items/{item_id}/price-source")
async def update_taping_block_item_price_source(item_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    it = db.query(TapingBlockItem).filter_by(id=item_id).first()
    if not it:
        raise HTTPException(status_code=404)
    src = body.get("price_source", "standard")
    if src not in ("standard", "sap"):
        raise HTTPException(status_code=400, detail="price_source must be 'standard' or 'sap'")
    if src == "sap" and not it.sap_item_code_id:
        raise HTTPException(status_code=400, detail="No SAP item code linked to this item")
    it.price_source = src
    db.commit()
    block = db.query(TapingBlock).filter_by(id=it.block_id).first()
    return {"ok": True, "cost": _compute_taping_block_cost(block) if block else 0}


# ─── Admin pages ─────────────────────────────────────────────────────────────

@router.get("/admin/taping-blocks", response_class=HTMLResponse)
async def admin_taping_blocks(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login")
    if not user_can(user, "menu.pricing_formulas", db):
        raise HTTPException(status_code=403, detail="Not authorized")
    return templates.TemplateResponse("admin_taping_blocks.html", {"request": request, "user": user})


@router.get("/admin/sap-prices", response_class=HTMLResponse)
async def admin_sap_prices(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login")
    if not user_can(user, "menu.pricing_formulas", db):
        raise HTTPException(status_code=403, detail="Not authorized")
    return templates.TemplateResponse("admin_sap_prices.html", {"request": request, "user": user})


@router.get("/admin/skin-formulas", response_class=HTMLResponse)
async def admin_skin_formulas(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login")
    if not user_can(user, "menu.pricing_formulas", db):
        raise HTTPException(status_code=403, detail="Not authorized")
    return templates.TemplateResponse("admin_skin_formulas.html", {"request": request, "user": user})


# ─── Floor Plates ─────────────────────────────────────────────────────────────

@router.get("/api/floor-plates")
async def list_floor_plates(db: Session = Depends(get_db)):
    plates = (db.query(FloorPlate)
              .filter_by(is_active=True)
              .order_by(FloorPlate.sort_order, FloorPlate.name).all())
    return [_serialize_floor_plate(p) for p in plates]


@router.post("/api/floor-plates")
async def create_floor_plate(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    p = FloorPlate(
        name=body["name"].strip(),
        description=body.get("description", ""),
        sort_order=body.get("sort_order", 0),
        is_active=True,
        price_formula=body.get("price_formula") or None,
    )
    db.add(p)
    db.flush()
    for idx, item in enumerate(body.get("items", [])):
        db.add(FloorPlateItem(
            plate_id=p.id,
            side=item.get("side", "left"),
            item_name=item["item_name"],
            sap_code=item.get("sap_code") or None,
            sap_item_code_id=item.get("sap_item_code_id"),
            length=float(item.get("length", 0)),
            width=float(item.get("width", 0)),
            m2=float(item.get("m2", 0)),
            price_per_unit=float(item.get("price_per_unit", 0)),
            price_source=item.get("price_source", "standard"),
            quantity=float(item.get("quantity", 1)),
            sort_order=item.get("sort_order", idx * 10),
        ))
    db.commit()
    db.refresh(p)
    return {"id": p.id}


@router.put("/api/floor-plates/{p_id}")
async def update_floor_plate(p_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    p = db.query(FloorPlate).filter_by(id=p_id).first()
    if not p:
        raise HTTPException(status_code=404)
    for k in ["name", "description", "sort_order", "is_active", "price_formula"]:
        if k in body:
            setattr(p, k, body[k])
    if "items" in body:
        for old in list(p.items):
            db.delete(old)
        db.flush()
        for idx, item in enumerate(body["items"]):
            db.add(FloorPlateItem(
                plate_id=p.id,
                side=item.get("side", "left"),
                item_name=item["item_name"],
                sap_code=item.get("sap_code") or None,
                sap_item_code_id=item.get("sap_item_code_id"),
                length=float(item.get("length", 0)),
                width=float(item.get("width", 0)),
                m2=float(item.get("m2", 0)),
                price_per_unit=float(item.get("price_per_unit", 0)),
                price_source=item.get("price_source", "standard"),
                quantity=float(item.get("quantity", 1)),
                sort_order=item.get("sort_order", idx * 10),
            ))
    db.commit()
    return {"ok": True}


@router.delete("/api/floor-plates/{p_id}")
async def delete_floor_plate(p_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    p = db.query(FloorPlate).filter_by(id=p_id).first()
    if p:
        p.is_active = False
        db.commit()
    return {"ok": True}


@router.put("/api/floor-plate-items/{item_id}/inline-price")
async def inline_update_floor_plate_item_price(item_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user_can(user, "recipes.edit_inline", db):
        raise HTTPException(status_code=403, detail="Permission denied")
    body = await request.json()
    it = db.query(FloorPlateItem).filter_by(id=item_id).first()
    if not it:
        raise HTTPException(status_code=404)
    if "price_per_unit" in body:
        it.price_per_unit = float(body["price_per_unit"])
    if "quantity" in body:
        it.quantity = float(body["quantity"])
    db.commit()
    return {"ok": True}


@router.patch("/api/floor-plate-items/{item_id}/price-source")
async def update_floor_plate_item_price_source(item_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    it = db.query(FloorPlateItem).filter_by(id=item_id).first()
    if not it:
        raise HTTPException(status_code=404)
    src = body.get("price_source", "standard")
    if src not in ("standard", "sap"):
        raise HTTPException(status_code=400, detail="price_source must be 'standard' or 'sap'")
    if src == "sap" and not it.sap_item_code_id:
        raise HTTPException(status_code=400, detail="No SAP item code linked to this item")
    it.price_source = src
    db.commit()
    plate = db.query(FloorPlate).filter_by(id=it.plate_id).first()
    return {"ok": True, "cost": _compute_floor_plate_cost(plate) if plate else 0}


@router.get("/admin/floor-plates", response_class=HTMLResponse)
async def admin_floor_plates(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login")
    if not user_can(user, "menu.pricing_formulas", db):
        raise HTTPException(status_code=403, detail="Not authorized")
    return templates.TemplateResponse("admin_floor_plates.html", {"request": request, "user": user})


# ── Mounting Cleats ──────────────────────────────────────────────────────────

@router.get("/api/mounting-cleats")
async def list_mounting_cleats(db: Session = Depends(get_db)):
    cleats = db.query(MountingCleat).order_by(MountingCleat.sort_order).all()
    return [_serialize_mounting_cleat(c) for c in cleats]


@router.post("/api/mounting-cleats")
async def create_mounting_cleat(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    sap_map = {r.item_code: r.id for r in db.query(SapItemCode).all()}
    cleat = MountingCleat(
        name=body["name"].strip(),
        group=(body.get("group") or "MOUNTING CLEATS").strip().upper(),
        description=body.get("description", "").strip(),
        is_active=True,
        sort_order=body.get("sort_order", 0),
    )
    db.add(cleat)
    db.flush()
    for it in body.get("items", []):
        isap = (it.get("sap_code") or "").strip() or None
        db.add(MountingCleatItem(
            cleat_id=cleat.id,
            item_name=it["item_name"],
            sap_code=isap,
            sap_item_code_id=sap_map.get(isap) if isap else None,
            length=float(it.get("length") or 0),
            width=float(it.get("width") or 0),
            m2=float(it.get("m2") or 0),
            price_per_unit=float(it.get("price_per_unit") or 0),
            quantity=float(it.get("quantity") or 1),
            sort_order=int(it.get("sort_order") or 0),
            price_source="standard",
        ))
    db.commit()
    db.refresh(cleat)
    return _serialize_mounting_cleat(cleat)


@router.put("/api/mounting-cleats/{c_id}")
async def update_mounting_cleat(c_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    cleat = db.query(MountingCleat).filter_by(id=c_id).first()
    if not cleat:
        raise HTTPException(status_code=404)
    body = await request.json()
    sap_map = {r.item_code: r.id for r in db.query(SapItemCode).all()}
    cleat.name        = body["name"].strip()
    cleat.group       = (body.get("group") or cleat.group).strip().upper()
    cleat.description = body.get("description", "").strip()
    cleat.sort_order  = body.get("sort_order", cleat.sort_order)
    for old in list(cleat.items):
        db.delete(old)
    db.flush()
    for it in body.get("items", []):
        isap = (it.get("sap_code") or "").strip() or None
        db.add(MountingCleatItem(
            cleat_id=cleat.id,
            item_name=it["item_name"],
            sap_code=isap,
            sap_item_code_id=sap_map.get(isap) if isap else None,
            length=float(it.get("length") or 0),
            width=float(it.get("width") or 0),
            m2=float(it.get("m2") or 0),
            price_per_unit=float(it.get("price_per_unit") or 0),
            quantity=float(it.get("quantity") or 1),
            sort_order=int(it.get("sort_order") or 0),
            price_source="standard",
        ))
    db.commit()
    db.refresh(cleat)
    return _serialize_mounting_cleat(cleat)


@router.delete("/api/mounting-cleats/{c_id}")
async def delete_mounting_cleat(c_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    cleat = db.query(MountingCleat).filter_by(id=c_id).first()
    if not cleat:
        raise HTTPException(status_code=404)
    db.delete(cleat)
    db.commit()
    return {"ok": True}


@router.patch("/api/mounting-cleat-items/{item_id}/price-source")
async def update_mounting_cleat_item_price_source(item_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    it = db.query(MountingCleatItem).filter_by(id=item_id).first()
    if not it:
        raise HTTPException(status_code=404)
    body = await request.json()
    it.price_source = body.get("price_source", "standard")
    db.commit()
    cleat = db.query(MountingCleat).filter_by(id=it.cleat_id).first()
    from ..services import _serialize_mounting_cleat as _ser
    return {"ok": True, "cost": _compute_mounting_cleat_cost(cleat) if cleat else 0}


@router.get("/admin/mounting-cleats", response_class=HTMLResponse)
async def admin_mounting_cleats(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login")
    if not user_can(user, "menu.pricing_formulas", db):
        raise HTTPException(status_code=403, detail="Not authorized")
    return templates.TemplateResponse("admin_mounting_cleats.html", {"request": request, "user": user})
