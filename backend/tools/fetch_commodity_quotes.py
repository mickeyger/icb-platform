"""Nightly fetcher for commodity / equity proxy quotes used by the
sub-category trend sparkline on /admin/materials.

Pulls the last ~3 months of daily close prices from Yahoo Finance's
public chart API (no key, no extra deps) and upserts via SQLAlchemy
into the commodity_quotes table. Works against both dev (SQLite)
and prod (MySQL) by using the app's existing SessionLocal.

Designed to fail soft: if a ticker fetch fails, log it and move on.
The UI hides the sparkline gracefully when no recent data exists.

Run manually:  python tools/fetch_commodity_quotes.py
Cron nightly (cPanel):
  0 2 * * *  cd ~/icecoldgrp && /home/fajecoza/virtualenv/icecoldgrp/3.11/bin/python tools/fetch_commodity_quotes.py >> ~/icecoldgrp/logs/commodity_fetch.log 2>&1
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen

# Allow running from anywhere (cron typically runs from $HOME)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, CommodityQuote, AdminSetting, init_db  # noqa: E402

# Sub-category → primary commodity / equity proxy ticker on Yahoo Finance.
# `=F` = futures, `.JO` = JSE listing, `=X` = FX rate.
TICKERS = {
    "MILD STEEL":              ("HRC=F", "Hot-rolled coil steel futures"),
    "STAINLESS STEEL + ALU":   ("ALI=F", "LME aluminium futures"),
    "ALUMINIUM":               ("ALI=F", "LME aluminium futures"),
    "RESINS + ADESIVES":       ("CL=F",  "Crude oil — feedstock proxy"),
    "PLYWOODS + TIMBER":       ("SAP.JO","Sappi (JSE) — timber sector proxy"),
    "RIVETS":                  ("HRC=F", "Hot-rolled coil steel futures"),
    "BOLTS":                   ("HRC=F", "Hot-rolled coil steel futures"),
    "FITTINGS":                ("HRC=F", "Hot-rolled coil steel futures"),
    # FX so the UI can convert USD futures to ZAR later
    "_USDZAR":                 ("ZAR=X", "USD/ZAR FX rate"),
}

YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=3mo&interval=1d"


def fetch_quotes(ticker: str) -> tuple[list[tuple[datetime, float]], str]:
    url = YAHOO_URL.format(ticker=ticker)
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read())
    result = (payload.get("chart") or {}).get("result")
    if not result:
        return [], "USD"
    res0 = result[0]
    ts_arr = res0.get("timestamp") or []
    quote = ((res0.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    currency = (res0.get("meta") or {}).get("currency") or "USD"
    out = []
    for ts, c in zip(ts_arr, closes):
        if c is None:
            continue
        out.append((datetime.fromtimestamp(ts, tz=timezone.utc), float(c)))
    return out, currency


def run_fetch(verbose: bool = True) -> dict:
    """Refresh commodity_quotes from Yahoo. Returns a per-ticker row count.
    Safe to call from a cron entrypoint or from a lazy startup hook."""
    init_db()  # ensure tables/migrations are present
    cutoff  = datetime.now(timezone.utc) - timedelta(days=70)
    fetched = {}
    seen    = set()
    db = SessionLocal()
    try:
        for sub, (ticker, desc) in TICKERS.items():
            if ticker in seen:
                continue
            seen.add(ticker)
            try:
                rows, ccy = fetch_quotes(ticker)
                rows = [(d, c) for (d, c) in rows if d >= cutoff]
                if not rows:
                    if verbose:
                        print(f"  {ticker}: no recent data", file=sys.stderr)
                    continue
                # Replace existing rows for this ticker within the window
                db.query(CommodityQuote).filter(
                    CommodityQuote.ticker == ticker,
                    CommodityQuote.date >= cutoff,
                ).delete(synchronize_session=False)
                db.add_all([
                    CommodityQuote(ticker=ticker, date=d, close=c, currency=ccy)
                    for (d, c) in rows
                ])
                fetched[ticker] = (len(rows), ccy)
                if verbose:
                    print(f"  {ticker} ({ccy}): {len(rows)} rows - {desc}")
            except Exception as e:
                if verbose:
                    print(f"  {ticker}: fetch failed - {e}", file=sys.stderr)
        # Stamp a heartbeat so /health/commodity can confirm the cron actually ran,
        # independent of whether market data published new rows today.
        if fetched:
            stamp = datetime.now(timezone.utc).isoformat()
            row = db.query(AdminSetting).filter_by(key="commodity_last_fetch_at").first()
            if row:
                row.value = stamp
            else:
                db.add(AdminSetting(key="commodity_last_fetch_at", value=stamp))
        db.commit()
    finally:
        db.close()
    if verbose:
        print(f"\nDone. Fetched {len(fetched)} tickers.")
    return fetched


if __name__ == "__main__":
    run_fetch(verbose=True)
