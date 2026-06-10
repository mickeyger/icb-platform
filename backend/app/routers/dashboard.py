import json
from datetime import datetime, timezone, timedelta

from fastapi import Request, APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db, TrailerType, Material, CalculationRecord, Customer
from ..deps import get_current_user, user_can
from ..templates_config import templates

router = APIRouter()


def _compute_approval_rates(db: Session, now_utc: datetime) -> dict:
    week_ago = now_utc - timedelta(days=7)
    cur_month_start = now_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if cur_month_start.month == 1:
        prev_month_start = cur_month_start.replace(year=cur_month_start.year - 1, month=12)
    else:
        prev_month_start = cur_month_start.replace(month=cur_month_start.month - 1)

    def _bucket(start, end):
        try:
            total = (db.query(CalculationRecord)
                     .filter(CalculationRecord.created_at >= start,
                             CalculationRecord.created_at < end).count())
            approved = (db.query(CalculationRecord)
                        .filter(CalculationRecord.created_at >= start,
                                CalculationRecord.created_at < end,
                                CalculationRecord.approved_at.isnot(None)).count())
        except Exception:
            total, approved = 0, 0
        pct = round((approved / total) * 100, 1) if total else 0.0
        return {"approved": approved, "total": total, "pct": pct}

    return {
        "week":  {**_bucket(week_ago, now_utc), "label": "Last 7 days"},
        "month": {**_bucket(cur_month_start, now_utc), "label": cur_month_start.strftime("%B %Y")},
        "prev":  {**_bucket(prev_month_start, cur_month_start), "label": prev_month_start.strftime("%B %Y")},
    }


@router.get("/api/dashboard/approval-rates")
async def api_approval_rates(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401)
    if not user_can(user, "dashboard.approval_rate", db):
        raise HTTPException(status_code=403)
    return _compute_approval_rates(db, datetime.now(timezone.utc))


def compute_kpis(db: Session, now_utc: datetime) -> dict:
    """The 5 dashboard METRIC values (WO v4.31 §3.4 / §0.7). Extracted from
    build_dashboard_context so the legacy Jinja dashboard and the React KPI tiles
    share ONE computation — value parity by construction (they cannot drift).
    Read-only: icb_costings read-joins only (the legacy 'Materials' tile counts
    icb_costings.materials, not icb_sap — parity keeps that source)."""
    week_ago = now_utc - timedelta(days=7)
    try:
        quotes_this_week = (db.query(CalculationRecord)
                            .filter(CalculationRecord.created_at >= week_ago).count())
    except Exception:
        quotes_this_week = 0

    total_value_quoted = 0.0
    approved_value_quoted = 0.0
    try:
        for rj, approved_at in db.query(CalculationRecord.result_json, CalculationRecord.approved_at).all():
            if rj:
                try:
                    d = json.loads(rj)
                    value = float(d.get("selling_price") or d.get("grand_total") or 0)
                    total_value_quoted += value
                    if approved_at:
                        approved_value_quoted += value
                except Exception:
                    pass
    except Exception:
        pass

    try:
        approved_count = (db.query(CalculationRecord)
                          .filter(CalculationRecord.approved_at.isnot(None)).count())
    except Exception:
        approved_count = 0

    mat_count = db.query(Material).filter_by(is_active=True).count()

    return {
        "quotes_this_week":      quotes_this_week,
        "total_value_quoted":    total_value_quoted,
        "approved_value_quoted": approved_value_quoted,
        "approved_count":        approved_count,
        "mat_count":             mat_count,
        "approval_rates":        _compute_approval_rates(db, now_utc),
    }


@router.get("/api/dashboard/kpis")
async def api_dashboard_kpis(request: Request, db: Session = Depends(get_db)):
    """WO v4.31 §3.4 — the 5 metric tiles for the React Costings dashboard. Read-only;
    require-user only (matches the legacy dashboard TILE exposure: build_dashboard_context
    renders these to any logged-in user — the stricter perm on /api/dashboard/approval-rates
    guards that standalone endpoint, not the tile). Refresh contract: fetched on page load
    only (§0.11 — no polling/websocket; tile-refresh is a v4.34 conversation)."""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401)
    now_utc = datetime.now(timezone.utc)
    return {**compute_kpis(db, now_utc), "as_of": now_utc.isoformat()}


def build_dashboard_context(request: Request, db: Session, user) -> dict:
    """Build the dashboard template context. Shared by `/` (original Icecold
    look) and `/mes/dashboard` (MES skin fork) so both views render the same
    data with different stylesheets. See WO v4.7."""
    trailers   = db.query(TrailerType).filter_by(is_active=True).order_by(TrailerType.name).all()
    calc_count = db.query(CalculationRecord).count()
    recent = (db.query(CalculationRecord)
              .order_by(CalculationRecord.created_at.desc()).limit(10).all())
    for r in recent:
        r.result_data = None
        if r.result_json:
            try:
                r.result_data = json.loads(r.result_json)
            except Exception:
                pass

    now_utc  = datetime.now(timezone.utc)
    kpis = compute_kpis(db, now_utc)   # WO v4.31 §3.4 — single source for the 5 metric tiles

    ninety_ago = now_utc - timedelta(days=90)
    try:
        outdated_count = (db.query(Material)
                          .filter(Material.is_active == True,
                                  Material.last_updated < ninety_ago).count())
    except Exception:
        outdated_count = 0

    try:
        customer_count = db.query(Customer).filter_by(is_active=True).count()
    except Exception:
        customer_count = 0

    from ..database import get_db_info
    db_env, db_detail, db_is_prod = get_db_info()
    return {
        "request": request, "user": user,
        "trailers": trailers, "mat_count": kpis["mat_count"],
        "calc_count": calc_count, "recent": recent,
        "db_env": db_env, "db_detail": db_detail, "db_is_prod": db_is_prod,
        "quotes_this_week":       kpis["quotes_this_week"],
        "total_value_quoted":     kpis["total_value_quoted"],
        "approved_value_quoted":  kpis["approved_value_quoted"],
        "outdated_count":         outdated_count,
        "customer_count":         customer_count,
        "approved_count":         kpis["approved_count"],
        "approval_rates":         kpis["approval_rates"],
    }


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login")
    ctx = build_dashboard_context(request, db, user)
    return templates.TemplateResponse("dashboard.html", ctx)
