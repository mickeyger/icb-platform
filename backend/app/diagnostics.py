"""
Production diagnostics — crash capture, health endpoint, request logging.

Wires into main.py via three install_* functions. Goal: when prod 500s, the
traceback lands in logs/crash.log automatically (no need to reproduce), and
admins can hit /debug/health to see what's actually running.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import platform
import sys
import time
import traceback
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from .database import get_db, User, CalculationRecord

_LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
os.makedirs(_LOG_DIR, exist_ok=True)

_CRASH_LOG = os.path.join(_LOG_DIR, "crash.log")
_REQ_LOG   = os.path.join(_LOG_DIR, "requests.log")

_STARTED_AT = time.time()


def _make_rotating(path: str, max_bytes: int = 1_000_000, backups: int = 3) -> logging.Logger:
    name = f"diag.{os.path.basename(path)}"
    lg = logging.getLogger(name)
    lg.setLevel(logging.INFO)
    lg.propagate = False
    if not lg.handlers:
        h = logging.handlers.RotatingFileHandler(
            path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
        )
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        lg.addHandler(h)
    return lg


_crash_log = _make_rotating(_CRASH_LOG, max_bytes=1_000_000, backups=3)
_req_log   = _make_rotating(_REQ_LOG,   max_bytes=2_000_000, backups=3)


def _redact_cookie(cookie: str) -> str:
    """Keep cookie names but mask values, so we know a session existed without leaking it."""
    if not cookie:
        return ""
    parts = []
    for piece in cookie.split(";"):
        if "=" in piece:
            k, v = piece.split("=", 1)
            v = v.strip()
            masked = (v[:4] + "…" + v[-2:]) if len(v) > 8 else "***"
            parts.append(f"{k.strip()}={masked}")
        else:
            parts.append(piece.strip())
    return "; ".join(parts)


def install_crash_handler(app: FastAPI) -> None:
    """Catch every unhandled exception, write traceback to logs/crash.log."""

    @app.exception_handler(Exception)
    async def _on_unhandled(request: Request, exc: Exception):
        # Don't intercept FastAPI/Starlette HTTPExceptions — those are normal
        # control flow (401/403/404 etc.) and have their own handlers.
        if isinstance(exc, (HTTPException, StarletteHTTPException)):
            raise exc
        sid = request.cookies.get("session_id", "")
        sid_short = (sid[:8] + "…") if sid else "none"
        tb = traceback.format_exc()
        msg = (
            f"\n========== UNHANDLED EXCEPTION ==========\n"
            f"when:    {datetime.now(timezone.utc).isoformat()}\n"
            f"method:  {request.method}\n"
            f"path:    {request.url.path}\n"
            f"query:   {request.url.query}\n"
            f"client:  {request.client.host if request.client else '?'}\n"
            f"ua:      {request.headers.get('user-agent', '')[:200]}\n"
            f"cookies: {_redact_cookie(request.headers.get('cookie', ''))}\n"
            f"session: {sid_short}\n"
            f"exc:     {type(exc).__name__}: {exc}\n"
            f"{tb}"
            f"=========================================\n"
        )
        _crash_log.error(msg)
        # Also surface to the main app logger so it shows in passenger logs.
        logging.getLogger("burtcost").exception(
            "Unhandled exception on %s %s", request.method, request.url.path
        )
        return JSONResponse(
            {"detail": "Internal Server Error", "ref": sid_short},
            status_code=500,
        )


def install_request_logger(app: FastAPI) -> None:
    """One log line per request: status + duration. Skip static + health probes."""

    @app.middleware("http")
    async def _log_requests(request: Request, call_next):
        start = time.perf_counter()
        try:
            response = await call_next(request)
            status = response.status_code
        except Exception:
            # crash handler will deal with it; record what we can and re-raise.
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            _req_log.info(
                f"{request.method} {request.url.path} status=500 ms={elapsed_ms} EXC"
            )
            raise
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        path = request.url.path
        if path.startswith("/static/") or path == "/favicon.ico":
            return response
        sid = request.cookies.get("session_id", "")
        sid_short = (sid[:8] + "…") if sid else "-"
        _req_log.info(
            f"{request.method} {path} status={status} ms={elapsed_ms} sid={sid_short}"
        )
        return response


def _db_health(db: Session) -> Dict[str, Any]:
    out: Dict[str, Any] = {"connected": False}
    try:
        db.execute(text("SELECT 1"))
        out["connected"] = True
        try:
            out["users"] = db.query(User).count()
            out["records"] = db.query(CalculationRecord).count()
        except Exception as e:
            out["counts_error"] = f"{type(e).__name__}: {e}"
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def _pdf_health() -> Dict[str, Any]:
    """Try a 1-line WeasyPrint render to surface Pango/Cairo/library mismatches
    early, instead of waiting for a user to click 'Generate Quote'."""
    out: Dict[str, Any] = {"ok": False}
    try:
        import weasyprint  # type: ignore
        out["weasyprint"] = getattr(weasyprint, "__version__", "?")
    except Exception as e:
        out["error"] = f"weasyprint import failed: {type(e).__name__}: {e}"
        return out
    try:
        pdf = weasyprint.HTML(string="<p>ok</p>").write_pdf()
        out["ok"] = bool(pdf and len(pdf) > 100)
        out["pdf_bytes"] = len(pdf) if pdf else 0
    except Exception as e:
        # The Pango symbol mismatch surfaces here as OSError with
        # "function/symbol '...' not found in library 'libpango-...'".
        out["error"] = f"{type(e).__name__}: {str(e)[:300]}"
    return out


def _tail(path: str, n: int = 30) -> list[str]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            chunk = min(size, 64 * 1024)
            f.seek(size - chunk)
            data = f.read().decode("utf-8", errors="replace")
        return data.splitlines()[-n:]
    except Exception as e:
        return [f"(tail error: {e})"]


def register_health_routes(app: FastAPI, app_version: str) -> None:
    """Admin-gated /debug/health endpoint with a JSON snapshot of prod state."""
    # Imported lazily to avoid circular import at module load.
    from .main import require_admin  # type: ignore

    @app.get("/debug/health")
    def health(request: Request, db: Session = Depends(get_db)):
        require_admin(request, db)
        uptime_s = int(time.time() - _STARTED_AT)
        return {
            "ok": True,
            "version": app_version,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "pid": os.getpid(),
            "uptime_seconds": uptime_s,
            "now_utc": datetime.now(timezone.utc).isoformat(),
            "db": _db_health(db),
            "pdf": _pdf_health(),
            "routes": len(app.routes),
            "env": {
                "DATABASE_URL_set": bool(os.getenv("DATABASE_URL")),
                "PYTHONPATH": os.getenv("PYTHONPATH", ""),
            },
            "logs": {
                "crash_log_size": (os.path.getsize(_CRASH_LOG) if os.path.exists(_CRASH_LOG) else 0),
                "request_log_size": (os.path.getsize(_REQ_LOG) if os.path.exists(_REQ_LOG) else 0),
                "recent_crashes": _tail(_CRASH_LOG, 50),
            },
        }

    @app.get("/debug/health/ping")
    def ping():
        """Unauthenticated cheap liveness probe — no DB hit, no auth."""
        return {"ok": True, "uptime_seconds": int(time.time() - _STARTED_AT)}
