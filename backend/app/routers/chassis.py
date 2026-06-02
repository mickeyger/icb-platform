from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db, ChassisOption, ChassisConstant
from ..deps import get_current_user, user_can
from ..templates_config import templates

router = APIRouter()


def _option_to_dict(o: ChassisOption) -> dict:
    return {
        "id": o.id, "kind": o.kind, "label": o.label,
        "axle_count": o.axle_count, "tyre_style": o.tyre_style,
        "price": float(o.price or 0), "sort_order": o.sort_order,
        "is_active": bool(o.is_active),
    }


def _constant_to_dict(c: ChassisConstant) -> dict:
    return {
        "id": c.id, "category": c.category, "name": c.name,
        "qty_per_metre": float(c.qty_per_metre or 0),
        "qty_constant":  float(c.qty_constant or 0),
        "unit_price":    float(c.unit_price or 0),
        "sort_order": c.sort_order,
        "is_active": bool(c.is_active),
    }


@router.get("/admin/chassis", response_class=HTMLResponse)
async def admin_chassis(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login")
    if not user_can(user, "menu.chassis", db):
        raise HTTPException(status_code=403, detail="Not authorized")
    options   = db.query(ChassisOption).order_by(
        ChassisOption.kind, ChassisOption.sort_order, ChassisOption.label).all()
    constants = db.query(ChassisConstant).order_by(
        ChassisConstant.category, ChassisConstant.sort_order, ChassisConstant.name).all()
    return templates.TemplateResponse("admin_chassis.html", {
        "request": request, "user": user,
        "options": options, "constants": constants,
    })


@router.get("/api/chassis/options")
async def api_chassis_options(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401)
    rows = db.query(ChassisOption).filter_by(is_active=True).order_by(
        ChassisOption.kind, ChassisOption.sort_order, ChassisOption.label).all()
    by_kind: dict = {}
    for r in rows:
        by_kind.setdefault(r.kind, []).append(_option_to_dict(r))
    return by_kind


@router.get("/api/chassis/constants")
async def api_chassis_constants(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401)
    if not user_can(user, "menu.chassis", db):
        raise HTTPException(status_code=403)
    rows = db.query(ChassisConstant).order_by(
        ChassisConstant.category, ChassisConstant.sort_order, ChassisConstant.name).all()
    return [_constant_to_dict(c) for c in rows]


@router.post("/api/chassis/options")
async def api_chassis_option_create(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user_can(user, "menu.chassis", db):
        raise HTTPException(status_code=403)
    body = await request.json()
    kind = (body.get("kind") or "").strip()
    if kind not in ("suspension", "brake", "tyre", "rim", "lifting_axle"):
        raise HTTPException(status_code=400, detail="Invalid kind")
    label = (body.get("label") or "").strip()
    if not label:
        raise HTTPException(status_code=400, detail="Label is required")
    o = ChassisOption(
        kind=kind, label=label,
        axle_count=body.get("axle_count"),
        tyre_style=body.get("tyre_style"),
        price=float(body.get("price") or 0),
        sort_order=int(body.get("sort_order") or 0),
        is_active=bool(body.get("is_active", True)),
    )
    db.add(o); db.commit(); db.refresh(o)
    return _option_to_dict(o)


@router.put("/api/chassis/options/{oid}")
async def api_chassis_option_update(oid: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user_can(user, "menu.chassis", db):
        raise HTTPException(status_code=403)
    o = db.query(ChassisOption).filter_by(id=oid).first()
    if not o:
        raise HTTPException(status_code=404)
    body = await request.json()
    for f in ("label", "tyre_style"):
        if f in body and body[f] is not None:
            setattr(o, f, str(body[f]).strip() or None)
    if "axle_count" in body:
        o.axle_count = int(body["axle_count"]) if body["axle_count"] not in (None, "") else None
    if "price" in body:
        o.price = float(body["price"] or 0)
    if "sort_order" in body:
        o.sort_order = int(body["sort_order"] or 0)
    if "is_active" in body:
        o.is_active = bool(body["is_active"])
    db.commit(); db.refresh(o)
    return _option_to_dict(o)


@router.delete("/api/chassis/options/{oid}")
async def api_chassis_option_delete(oid: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user_can(user, "menu.chassis", db):
        raise HTTPException(status_code=403)
    o = db.query(ChassisOption).filter_by(id=oid).first()
    if not o:
        raise HTTPException(status_code=404)
    db.delete(o); db.commit()
    return {"ok": True}


@router.post("/api/chassis/constants")
async def api_chassis_constant_create(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user_can(user, "menu.chassis", db):
        raise HTTPException(status_code=403)
    body = await request.json()
    category = (body.get("category") or "").strip()
    if category not in ("steel", "running_gear"):
        raise HTTPException(status_code=400, detail="Invalid category")
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    c = ChassisConstant(
        category=category, name=name,
        qty_per_metre=float(body.get("qty_per_metre") or 0),
        qty_constant=float(body.get("qty_constant") or 0),
        unit_price=float(body.get("unit_price") or 0),
        sort_order=int(body.get("sort_order") or 0),
        is_active=bool(body.get("is_active", True)),
    )
    db.add(c); db.commit(); db.refresh(c)
    return _constant_to_dict(c)


@router.put("/api/chassis/constants/{cid}")
async def api_chassis_constant_update(cid: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user_can(user, "menu.chassis", db):
        raise HTTPException(status_code=403)
    c = db.query(ChassisConstant).filter_by(id=cid).first()
    if not c:
        raise HTTPException(status_code=404)
    body = await request.json()
    if "name" in body:
        c.name = str(body["name"]).strip()
    for f in ("qty_per_metre", "qty_constant", "unit_price"):
        if f in body:
            setattr(c, f, float(body[f] or 0))
    if "sort_order" in body:
        c.sort_order = int(body["sort_order"] or 0)
    if "is_active" in body:
        c.is_active = bool(body["is_active"])
    db.commit(); db.refresh(c)
    return _constant_to_dict(c)


@router.delete("/api/chassis/constants/{cid}")
async def api_chassis_constant_delete(cid: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user_can(user, "menu.chassis", db):
        raise HTTPException(status_code=403)
    c = db.query(ChassisConstant).filter_by(id=cid).first()
    if not c:
        raise HTTPException(status_code=404)
    db.delete(c); db.commit()
    return {"ok": True}
