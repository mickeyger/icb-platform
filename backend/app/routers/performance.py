"""Admin Performance page — shows the costing-flow timing profile recorded by
app.perf. Restricted to the 'admin' account. Prod-safe: this page carries NO
dev tooling (no git, no subprocess) — it only reads timing records.
"""
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_user
from ..templates_config import templates
from .. import perf

router = APIRouter()


def _require_admin_account(request: Request, db: Session):
    """Gate to the single 'admin' username (case-insensitive)."""
    user = require_user(request, db)
    if (user.username or "").strip().lower() != "admin":
        raise HTTPException(status_code=403,
                            detail="The Performance page is restricted to the admin account.")
    return user


@router.get("/admin/performance", response_class=HTMLResponse)
async def performance_page(request: Request, db: Session = Depends(get_db)):
    user = _require_admin_account(request, db)
    return templates.TemplateResponse("performance.html", {"request": request, "user": user})


@router.get("/api/performance/data")
async def performance_data(request: Request, db: Session = Depends(get_db)):
    _require_admin_account(request, db)
    records = perf.read_recent(200)

    calc = [r for r in records if r.get("kind") == "server" and r.get("path") == "/api/calculate"]
    client = [r for r in records if r.get("kind") == "client"]

    def _avg(xs):
        return round(sum(xs) / len(xs), 1) if xs else 0.0

    summary = {
        "calc_count":     len(calc),
        "avg_server_ms":  _avg([r.get("duration_ms", 0) for r in calc]),
        "cold_count":     sum(1 for r in calc if r.get("cold")),
        "avg_render_ms":  _avg([r.get("duration_ms", 0) for r in client]),
        "avg_total_ms":   _avg([r.get("total_ms", 0) for r in client if r.get("total_ms")]),
    }
    return JSONResponse({"records": records, "summary": summary})


@router.post("/api/performance/beacon")
async def performance_beacon(request: Request, db: Session = Depends(get_db)):
    """Any logged-in user's calculator reports its client-side timing here.
    Fire-and-forget from the browser; failures are harmless."""
    require_user(request, db)
    try:
        body = await request.json()
    except Exception:
        body = {}
    page = str(body.get("page") or "calculator")
    render_ms = float(body.get("render_ms") or 0)
    total_ms = float(body.get("total_ms") or 0)
    perf.record("client", page, render_ms, extra={"total_ms": round(total_ms, 1)})
    return JSONResponse({"ok": True})
