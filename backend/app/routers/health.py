from datetime import datetime, timezone, timedelta

from fastapi import Request, APIRouter, Depends, HTTPException
from sqlalchemy import text, func
from sqlalchemy.orm import Session

from ..database import get_db, AdminSetting, CommodityQuote

router = APIRouter()


@router.get("/health")
async def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"db unreachable: {e}")


@router.get("/health/commodity")
async def health_commodity(db: Session = Depends(get_db)):
    CRON_STALE_HOURS = 36

    try:
        enabled_row = db.query(AdminSetting).filter_by(key="commodity_trends_enabled").first()
        feature_enabled = bool(enabled_row and enabled_row.value == "1")
        last_fetch_row = db.query(AdminSetting).filter_by(key="commodity_last_fetch_at").first()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"db unreachable: {e}")

    now = datetime.now(timezone.utc)
    cron_age_h = None
    cron_last_run = None
    if last_fetch_row:
        try:
            t = datetime.fromisoformat(last_fetch_row.value)
            if not t.tzinfo:
                t = t.replace(tzinfo=timezone.utc)
            cron_age_h = round((now - t).total_seconds() / 3600, 1)
            cron_last_run = t.isoformat()
        except ValueError:
            pass

    try:
        rows = db.query(
            CommodityQuote.ticker,
            func.max(CommodityQuote.date).label("latest"),
        ).group_by(CommodityQuote.ticker).all()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"db unreachable: {e}")

    tickers = [
        {
            "ticker":      ticker,
            "latest_date": (latest if latest.tzinfo else latest.replace(tzinfo=timezone.utc)).strftime("%Y-%m-%d"),
            "age_hours":   round((now - (latest if latest.tzinfo else latest.replace(tzinfo=timezone.utc))).total_seconds() / 3600, 1),
        }
        for ticker, latest in rows
    ]
    tickers.sort(key=lambda t: t["ticker"])

    if cron_age_h is None:
        status = "no_data"
    elif cron_age_h > CRON_STALE_HOURS:
        status = "cron_stale"
    else:
        status = "ok"

    return {
        "status":             status,
        "feature_enabled":    feature_enabled,
        "cron_last_run":      cron_last_run,
        "cron_age_hours":     cron_age_h,
        "cron_stale_after":   CRON_STALE_HOURS,
        "ticker_count":       len(tickers),
        "tickers":            tickers,
    }
