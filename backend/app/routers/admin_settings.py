from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import Request, APIRouter, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy import func as _sqlfunc
from sqlalchemy.orm import Session

from ..database import (
    get_db, AdminSetting, TrailerType, TrailerGroup, ReportTemplate,
    OrphanedTemplateAssignment, CommodityQuote,
)
from ..deps import get_current_user, require_admin, user_can
from ..quote_numbering import (
    get_or_create_counter, preview_template, validate_template, ALLOWED_PLACEHOLDERS,
)
from ..services import resolve_report_template
from ..templates_config import templates

router = APIRouter()

# ── Sub-category → commodity ticker mapping ───────────────────────────────────
COMMODITY_TICKERS = {
    "MILD STEEL":            ("HRC=F", "Hot-rolled coil steel futures"),
    "STAINLESS STEEL + ALU": ("ALI=F", "LME aluminium futures"),
    "ALUMINIUM":             ("ALI=F", "LME aluminium futures"),
    "RESINS + ADESIVES":     ("CL=F",  "Crude oil — feedstock proxy"),
    "PLYWOODS + TIMBER":     ("SAP.JO","Sappi (JSE) — timber sector proxy"),
    "RIVETS":                ("HRC=F", "Hot-rolled coil steel futures"),
    "BOLTS":                 ("HRC=F", "Hot-rolled coil steel futures"),
    "FITTINGS":              ("HRC=F", "Hot-rolled coil steel futures"),
}


def _commodity_enabled(db: Session) -> bool:
    row = db.query(AdminSetting).filter_by(key="commodity_trends_enabled").first()
    return bool(row and row.value == "1")


# ── Commodity ─────────────────────────────────────────────────────────────────

@router.get("/api/commodity/enabled")
async def get_commodity_enabled(db: Session = Depends(get_db)):
    return {"enabled": _commodity_enabled(db)}


@router.put("/api/commodity/enabled")
async def set_commodity_enabled(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    val = "1" if body.get("enabled") else "0"
    row = db.query(AdminSetting).filter_by(key="commodity_trends_enabled").first()
    if row:
        row.value = val
    else:
        db.add(AdminSetting(key="commodity_trends_enabled", value=val))
    db.commit()
    return {"ok": True, "enabled": val == "1"}


@router.get("/api/commodity/sub-category-trend")
async def commodity_trend(sub_category: str, db: Session = Depends(get_db)):
    if not _commodity_enabled(db):
        return {"enabled": False}
    mapping = COMMODITY_TICKERS.get((sub_category or "").upper().strip())
    if not mapping:
        return {"enabled": True, "ticker": None}
    ticker, desc = mapping
    cutoff = datetime.now(timezone.utc) - timedelta(days=45)
    rows = (db.query(CommodityQuote)
              .filter(CommodityQuote.ticker == ticker, CommodityQuote.date >= cutoff)
              .order_by(CommodityQuote.date.asc()).all())
    if len(rows) < 2:
        return {"enabled": True, "ticker": ticker, "description": desc, "points": []}
    points = [{"date": r.date.strftime("%Y-%m-%d"), "close": r.close} for r in rows]
    first, last = rows[0].close, rows[-1].close
    pct = ((last - first) / first * 100) if first else 0
    return {
        "enabled": True,
        "ticker": ticker,
        "description": desc,
        "currency": rows[-1].currency,
        "first": first,
        "last": last,
        "pct_change": round(pct, 2),
        "points": points,
    }


# ── Nav Group Names ───────────────────────────────────────────────────────────

@router.put("/api/admin/nav-groups")
async def update_nav_groups(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    allowed_keys = {
        "nav_group_bodies", "nav_group_chassis", "nav_group_pricing", "nav_group_bom",
        "nav_group_2", "nav_group_3",
    }
    updated = {}
    for key in allowed_keys:
        value = (body.get(key) or "").strip()
        if not value:
            continue
        row = db.query(AdminSetting).filter_by(key=key).first()
        if row:
            row.value = value
        else:
            db.add(AdminSetting(key=key, value=value))
        updated[key] = value
    db.commit()
    return {"ok": True, "groups": updated}


# ── Themes ────────────────────────────────────────────────────────────────────

@router.get("/admin/themes", response_class=HTMLResponse)
async def admin_themes(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login")
    if not user_can(user, "menu.themes", db):
        raise HTTPException(status_code=403, detail="Not authorized")
    from ..database import Theme
    try:
        theme_list = db.query(Theme).order_by(Theme.name).all()
    except (OperationalError, ProgrammingError):
        theme_list = []
    return templates.TemplateResponse("admin_themes.html", {
        "request": request, "user": user, "themes": theme_list,
    })


@router.post("/admin/themes")
async def admin_add_theme(request: Request,
                          name: str = Form(...),
                          description: str = Form(""),
                          css_path: str = Form(...),
                          is_default: Optional[bool] = Form(False),
                          db: Session = Depends(get_db)):
    require_admin(request, db)
    from ..database import Theme
    if is_default:
        db.query(Theme).update({Theme.is_default: False, Theme.is_active: False})
    theme = Theme(name=name.strip(), description=description.strip(),
                  css_path=css_path.strip(), is_active=is_default, is_default=is_default)
    db.add(theme)
    db.commit()
    return RedirectResponse(url="/admin/themes", status_code=303)


@router.post("/admin/themes/{theme_id}/activate")
async def admin_activate_theme(theme_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    from ..database import Theme
    theme = db.query(Theme).filter_by(id=theme_id).first()
    if not theme:
        raise HTTPException(status_code=404)
    db.query(Theme).update({Theme.is_active: False})
    theme.is_active = True
    db.commit()
    # bust the in-process cache so the new theme loads on the next request
    try:
        from ..main import _theme_cache
        _theme_cache["expires"] = 0.0
    except Exception:
        pass
    return RedirectResponse(url="/admin/themes", status_code=303)


@router.post("/admin/themes/{theme_id}/edit")
async def admin_edit_theme(theme_id: int, request: Request,
                           name: str = Form(...),
                           description: str = Form(""),
                           css_path: str = Form(...),
                           is_default: Optional[bool] = Form(False),
                           db: Session = Depends(get_db)):
    require_admin(request, db)
    from ..database import Theme
    theme = db.query(Theme).filter_by(id=theme_id).first()
    if not theme:
        raise HTTPException(status_code=404)
    theme.name = name.strip()
    theme.description = description.strip()
    theme.css_path = css_path.strip()
    if is_default:
        db.query(Theme).update({Theme.is_default: False, Theme.is_active: False})
        theme.is_default = True
        theme.is_active = True
    db.commit()
    return RedirectResponse(url="/admin/themes", status_code=303)


@router.post("/admin/themes/{theme_id}/delete")
async def admin_delete_theme(theme_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    from ..database import Theme
    theme = db.query(Theme).filter_by(id=theme_id).first()
    if not theme:
        raise HTTPException(status_code=404)
    db.delete(theme)
    db.commit()
    return RedirectResponse(url="/admin/themes", status_code=303)


# ── Quote Numbering ───────────────────────────────────────────────────────────

@router.get("/admin/quote-numbering", response_class=HTMLResponse)
async def admin_quote_numbering(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login")
    if not user_can(user, "menu.quote_numbering", db):
        raise HTTPException(status_code=403, detail="Not authorized")
    qc = get_or_create_counter(db)
    db.commit()
    return templates.TemplateResponse("admin_quote_numbering.html", {
        "request": request, "user": user,
        "counter": qc,
        "placeholders": sorted(ALLOWED_PLACEHOLDERS),
    })


@router.get("/api/quote-numbering")
async def api_quote_numbering_get(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    qc = get_or_create_counter(db)
    db.commit()
    return {
        "next_value":      qc.next_value,
        "format_template": qc.format_template,
        "preview":         preview_template(qc.format_template),
        "placeholders":    sorted(ALLOWED_PLACEHOLDERS),
    }


@router.post("/api/quote-numbering/preview")
async def api_quote_numbering_preview(payload: dict, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    template = (payload or {}).get("format_template", "")
    ok, msg = validate_template(template)
    if not ok:
        return {"ok": False, "error": msg}
    return {"ok": True, "preview": preview_template(template)}


@router.put("/api/quote-numbering")
async def api_quote_numbering_update(payload: dict, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    qc = get_or_create_counter(db)

    new_template = (payload or {}).get("format_template")
    new_next     = (payload or {}).get("next_value")

    if new_template is not None:
        ok, msg = validate_template(new_template)
        if not ok:
            raise HTTPException(status_code=400, detail=msg)
        qc.format_template = new_template

    if new_next is not None:
        try:
            n = int(new_next)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="next_value must be an integer")
        if n < 1:
            raise HTTPException(status_code=400, detail="next_value must be >= 1")
        qc.next_value = n

    db.commit()
    return {
        "ok": True,
        "next_value": qc.next_value,
        "format_template": qc.format_template,
        "preview": preview_template(qc.format_template),
    }


# ── Quote Templates (report templates + trailer groups) ──────────────────────

@router.get("/admin/quote-templates", response_class=HTMLResponse)
async def admin_quote_templates(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login")
    if not user_can(user, "menu.templates", db):
        raise HTTPException(status_code=403, detail="Not authorized")

    templates_list = db.query(ReportTemplate).order_by(ReportTemplate.name).all()
    groups         = db.query(TrailerGroup).order_by(TrailerGroup.name).all()
    trailers       = db.query(TrailerType).filter_by(is_active=True).order_by(TrailerType.name).all()
    orphans        = db.query(OrphanedTemplateAssignment).order_by(OrphanedTemplateAssignment.archived_at.desc()).all()

    template_by_id = {t.id: t for t in templates_list}
    group_by_id    = {g.id: g for g in groups}

    template_usage = {t.id: 0 for t in templates_list}
    for g in groups:
        if g.report_template_id in template_usage:
            template_usage[g.report_template_id] += sum(
                1 for tt in trailers if tt.group_id == g.id and not tt.override_report_template_id
            )
    for tt in trailers:
        if tt.override_report_template_id in template_usage:
            template_usage[tt.override_report_template_id] += 1

    group_members = {g.id: [tt for tt in trailers if tt.group_id == g.id] for g in groups}
    resolved_map  = {tt.id: resolve_report_template(tt) for tt in trailers}

    orphan_group_name    = {o.id: (group_by_id[o.group_id].name if o.group_id in group_by_id else None) for o in orphans}
    orphan_override_name = {o.id: (template_by_id[o.override_report_template_id].name
                                   if o.override_report_template_id in template_by_id else None) for o in orphans}

    return templates.TemplateResponse("admin_quote_templates.html", {
        "request": request, "user": user,
        "templates_list": templates_list,
        "groups": groups,
        "trailers": trailers,
        "orphans": orphans,
        "template_usage": template_usage,
        "group_members": group_members,
        "resolved_map": resolved_map,
        "orphan_group_name": orphan_group_name,
        "orphan_override_name": orphan_override_name,
    })


@router.post("/admin/quote-templates/groups/new")
async def admin_quote_group_new(request: Request,
                                name: str = Form(...),
                                description: str = Form(""),
                                report_template_id: Optional[str] = Form(None),
                                db: Session = Depends(get_db)):
    require_admin(request, db)
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Group name required.")
    if db.query(TrailerGroup).filter_by(name=name).first():
        raise HTTPException(status_code=400, detail=f"Group '{name}' already exists.")
    g = TrailerGroup(
        name=name,
        description=description.strip(),
        report_template_id=int(report_template_id) if report_template_id else None,
    )
    db.add(g); db.commit()
    return RedirectResponse(url="/admin/quote-templates", status_code=303)


@router.post("/admin/quote-templates/groups/{group_id}/edit")
async def admin_quote_group_edit(group_id: int, request: Request,
                                 name: str = Form(...),
                                 description: str = Form(""),
                                 report_template_id: Optional[str] = Form(None),
                                 db: Session = Depends(get_db)):
    require_admin(request, db)
    g = db.query(TrailerGroup).filter_by(id=group_id).first()
    if not g:
        raise HTTPException(status_code=404)
    g.name = name.strip()
    g.description = description.strip()
    g.report_template_id = int(report_template_id) if report_template_id else None
    db.commit()
    return RedirectResponse(url="/admin/quote-templates", status_code=303)


@router.post("/admin/quote-templates/groups/{group_id}/delete")
async def admin_quote_group_delete(group_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    g = db.query(TrailerGroup).filter_by(id=group_id).first()
    if not g:
        raise HTTPException(status_code=404)
    db.query(TrailerType).filter_by(group_id=group_id).update({"group_id": None})
    db.delete(g); db.commit()
    return RedirectResponse(url="/admin/quote-templates", status_code=303)


@router.post("/admin/quote-templates/trailer/{trailer_id}/assign")
async def admin_quote_trailer_assign(trailer_id: int, request: Request,
                                     group_id: Optional[str] = Form(None),
                                     override_report_template_id: Optional[str] = Form(None),
                                     db: Session = Depends(get_db)):
    require_admin(request, db)
    tt = db.query(TrailerType).filter_by(id=trailer_id).first()
    if not tt:
        raise HTTPException(status_code=404)
    tt.group_id = int(group_id) if group_id else None
    tt.override_report_template_id = int(override_report_template_id) if override_report_template_id else None
    db.commit()
    return RedirectResponse(url="/admin/quote-templates", status_code=303)


@router.post("/admin/quote-templates/orphans/{orphan_id}/restore")
async def admin_quote_orphan_restore(orphan_id: int, request: Request,
                                     trailer_id: Optional[str] = Form(None),
                                     db: Session = Depends(get_db)):
    require_admin(request, db)
    o = db.query(OrphanedTemplateAssignment).filter_by(id=orphan_id).first()
    if not o:
        raise HTTPException(status_code=404)
    tt = None
    if trailer_id:
        tt = db.query(TrailerType).filter_by(id=int(trailer_id), is_active=True).first()
    else:
        from sqlalchemy import func as _fn
        tt = (db.query(TrailerType)
                .filter(TrailerType.is_active == True,
                        _fn.lower(TrailerType.name) == o.trailer_name.lower())
                .first())
    if not tt:
        raise HTTPException(status_code=400, detail="No matching active trailer to restore onto.")
    if o.group_id and db.query(TrailerGroup).filter_by(id=o.group_id).first():
        tt.group_id = o.group_id
    if o.override_report_template_id and db.query(ReportTemplate).filter_by(id=o.override_report_template_id).first():
        tt.override_report_template_id = o.override_report_template_id
    db.delete(o); db.commit()
    return RedirectResponse(url="/admin/quote-templates", status_code=303)


@router.post("/admin/quote-templates/orphans/{orphan_id}/discard")
async def admin_quote_orphan_discard(orphan_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    o = db.query(OrphanedTemplateAssignment).filter_by(id=orphan_id).first()
    if not o:
        raise HTTPException(status_code=404)
    db.delete(o); db.commit()
    return RedirectResponse(url="/admin/quote-templates", status_code=303)


# ── Customers admin page ──────────────────────────────────────────────────────

@router.get("/admin/customers", response_class=HTMLResponse)
async def admin_customers_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login")
    if not user_can(user, "menu.customers", db):
        raise HTTPException(status_code=403, detail="Not authorized")
    return templates.TemplateResponse("admin_customers.html", {"request": request, "user": user})
