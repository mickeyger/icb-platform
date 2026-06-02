"""Icecold Bodies MES skin fork — Work Order v4.7.

Serves MES-skinned copies of the Dashboard and Cost Calculator at /mes/*
URLs so the React MES mockup iframe can embed them without affecting how the
live app renders at / and /calculator (which must stay bit-for-bit pristine,
dark-Icecold styling, per the user's regression report).

The templates `dashboard_mes.html` and `calculator_mes.html` are thin Jinja
wrappers that `{% extends %}` their live counterparts and append the
theme-mes.css overlay in `{% block head %}`. So this router does no more
than what the live routes do — it just renders the wrapper templates.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db, TrailerType
from ..deps import get_current_user
from ..templates_config import templates
from .dashboard import build_dashboard_context

router = APIRouter(prefix="/mes", tags=["mes-views"])


@router.get("/dashboard", response_class=HTMLResponse)
async def mes_dashboard(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login")
    ctx = build_dashboard_context(request, db, user)
    return templates.TemplateResponse("dashboard_mes.html", ctx)


@router.get("/calculator", response_class=HTMLResponse)
async def mes_calculator(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login")
    trailers = db.query(TrailerType).filter_by(is_active=True).order_by(TrailerType.name).all()
    return templates.TemplateResponse("calculator_mes.html", {
        "request": request, "user": user, "trailers": trailers,
    })
