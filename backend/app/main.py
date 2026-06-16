import json
import logging
import os
import queue
import secrets
import subprocess
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from io import BytesIO
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, Depends, Form, HTTPException, status, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text, func
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session, joinedload, selectinload
from passlib.context import CryptContext

from .database import (get_db, init_db, User, MaterialCategory, Material,
                      TrailerType, BillOfMaterial, Formula, PriceHistory,
                      CalculationRecord, Customer, PDFTemplate, AdminSetting,
                      CommodityQuote,
                      BOMSection, ReportTemplate, TrailerGroup,
                      OrphanedTemplateAssignment,
                      Permission, RolePermission, UserPermission,
                      PERMISSION_CATALOGUE, SessionLocal, QuoteCounter,
                      ChassisOption, ChassisConstant, UserSession,
                      TrailerRatio, BodyOptionGroup, BodyOptionSubgroup,
                      SkinFormulaIngredient, SkinFormula, SkinFormulaItem,
                      SapItemCode,
                      TapingBlock, TapingBlockItem)
from app.formula_engine import calculate_bom
from .seed_data import seed
from .config import settings
from .quote_numbering import (assign_quote_number, get_or_create_counter,
                              preview_template, validate_template,
                              ALLOWED_PLACEHOLDERS)
from .deps import (
    pwd_context as _pwd_context,
    _sess_get, _sess_touch, _SESS_TOUCH_INTERVAL,
    get_current_user, require_user, require_admin,
    _user_permission_set, user_can, require_perm,
    _is_localhost, _get_client_ip,
    _is_dev_mode,
    _login_attempts, _MAX_ATTEMPTS, _LOCKOUT_SECONDS,
    _is_rate_limited, _record_failed_attempt, _clear_attempts, _login_ctx,
)
from .templates_config import templates
from .services import (
    _bom_load_options,
    _compute_skin_formula_cost, _compute_taping_block_cost, _serialize_taping_block,
    _resolve_bom_section, _resolve_body_option_group, _resolve_body_option_subgroup,
    compute_chassis_cost,
    archive_trailer_template_binding, restore_orphan_for_trailer, resolve_report_template,
)
from .routers import customers as _r_customers, users as _r_users
from .routers import chassis as _r_chassis, materials as _r_materials
from .routers import chassis_register as _r_chassis_register  # WO v4.22
from .routers import chassis_records as _r_chassis_records  # WO v4.28 — chassis lifecycle
from .routers import bom_generate as _r_bom_generate  # WO v4.25 (POST /api/bom/generate, rules engine)
from .routers.admin import (  # WO v4.26 — admin CRUD for the 4 master-data tables
    bom_rules as _r_admin_rules, bom_rule_lookups as _r_admin_lookups,
    material_price_overrides as _r_admin_overrides, bom_spec_options as _r_admin_spec_options,
)
from .routers.admin import prejob_templates as _r_admin_prejob_templates  # WO v4.33 §3.3
from .routers.admin import fridge_units as _r_admin_fridge_units  # WO v4.33 — fridge DDM
from .routers import auth as _r_auth, trailers as _r_trailers
from .routers import skin_taping as _r_skin_taping, calculator as _r_calculator
from .routers import health as _r_health, formulas as _r_formulas
from .routers import dashboard as _r_dashboard
from .routers import trailer_designer as _r_trailer_designer
from .routers import admin_settings as _r_admin_settings
from .routers import import_excel as _r_import_excel
from .routers import performance as _r_performance
from .routers import pdf_templates as _r_pdf_templates
from .routers import exports as _r_exports
from .routers import bom_snapshots as _r_bom_snapshots
from .routers import help as _r_help
from .routers import pre_job_card as _r_pre_job_card
from .routers import chassis_catalogue as _r_chassis_catalogue
from .routers import mes_views as _r_mes_views  # WO v4.7 — MES skin fork at /mes/*
from .routers import production_jobs as _r_production_jobs  # WO v4.14 — /api/production-jobs/*
from .routers import production as _r_production  # WO v4.32 — /api/production/* aggregations
from .routers import prejob_cards as _r_prejob_cards  # WO v4.33 — Pre-Job Card workflow
# WO v4.15 — Materials / Buying / Stores APIs
from .routers import mes_materials as _r_mes_materials
from .routers import stock_counts as _r_stock_counts
from .routers import discrepancies as _r_discrepancies
from .routers import po_suggestions as _r_po_suggestions
from .routers import demand_lines as _r_demand_lines
from .routers import suppliers as _r_suppliers
# WO v4.16 — Planning Board + session/branch + per-role gating
from .routers import session as _r_session
from .routers import planning as _r_planning

# ─── Logging setup ───────────────────────────────────────────────────────────
_log_dir = os.path.join(os.path.dirname(__file__), '..', 'logs')
os.makedirs(_log_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(_log_dir, 'app.log')),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger("burtcost")

app = FastAPI(title="Trailer Costing System")

# WO v4.26 — map admin CRUD domain errors to HTTP status codes (422 validation, 409 conflict).
from .services.admin_bom import AdminConflictError, AdminValidationError  # noqa: E402


@app.exception_handler(AdminValidationError)
async def _admin_validation_handler(request: Request, exc: AdminValidationError):
    return JSONResponse({"detail": str(exc)}, status_code=422)


@app.exception_handler(AdminConflictError)
async def _admin_conflict_handler(request: Request, exc: AdminConflictError):
    return JSONResponse({"detail": str(exc)}, status_code=409)
app.add_middleware(GZipMiddleware, minimum_size=1000)
# CORS for the Icecold Bodies MES React mockup (Vite dev 5173, Vite preview 4173).
# Lets the mockup fetch /api/calculations + the new pre-job-card endpoints during
# the demo. Credentials must be allowed so the costing-app session cookie travels.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
pwd_context = _pwd_context  # backward-compat alias for routes still in this file

# ── Domain routers ────────────────────────────────────────────────────────────
app.include_router(_r_auth.router)
app.include_router(_r_customers.router)
app.include_router(_r_users.router)
app.include_router(_r_chassis.router)
app.include_router(_r_materials.router)
app.include_router(_r_trailers.router)
app.include_router(_r_skin_taping.router)
app.include_router(_r_calculator.router)
app.include_router(_r_health.router)
app.include_router(_r_formulas.router)
app.include_router(_r_dashboard.router)
app.include_router(_r_trailer_designer.router)
app.include_router(_r_admin_settings.router)
app.include_router(_r_import_excel.router)
app.include_router(_r_performance.router)
app.include_router(_r_pdf_templates.router)
app.include_router(_r_exports.router)
app.include_router(_r_bom_snapshots.router)
app.include_router(_r_help.router)
app.include_router(_r_pre_job_card.router)
app.include_router(_r_pre_job_card.demo_router)
app.include_router(_r_chassis_catalogue.router)
app.include_router(_r_chassis_register.router)  # WO v4.22 — chassis register API
app.include_router(_r_chassis_records.router)  # WO v4.28 — chassis lifecycle API
app.include_router(_r_mes_views.router)  # WO v4.7 — /mes/dashboard + /mes/calculator
app.include_router(_r_production_jobs.router)  # WO v4.14 — production-jobs API
app.include_router(_r_production.router)  # WO v4.32 — team-worksheet aggregation
app.include_router(_r_prejob_cards.router)  # WO v4.33 — Pre-Job Card workflow API
# WO v4.15 — Materials / Buying / Stores APIs (12 endpoints across 6 routers)
app.include_router(_r_mes_materials.router)
app.include_router(_r_stock_counts.router)
app.include_router(_r_discrepancies.router)
app.include_router(_r_po_suggestions.router)
app.include_router(_r_demand_lines.router)
app.include_router(_r_suppliers.router)
# WO v4.16 — Planning Board + session/branch + per-role gating
app.include_router(_r_session.router)
app.include_router(_r_planning.board_router)
app.include_router(_r_planning.router)
app.include_router(_r_bom_generate.router)  # WO v4.25 — /api/bom/generate (rules engine)
# WO v4.26 — admin CRUD for the 4 master-data tables + OITM autocomplete
app.include_router(_r_admin_rules.router)
app.include_router(_r_admin_lookups.router)
app.include_router(_r_admin_overrides.router)
app.include_router(_r_admin_spec_options.router)
app.include_router(_r_admin_spec_options.search_router)
app.include_router(_r_admin_prejob_templates.router)  # WO v4.33 §3.3 — template review/approve
app.include_router(_r_admin_fridge_units.router)  # WO v4.33 — fridge DDM CRUD

# ─── Diagnostics: crash capture + request logging ───────────────────────────
# Installed early so they wrap everything below. /debug/health is registered
# at the bottom of this file (after _APP_VERSION is computed).
from . import diagnostics
diagnostics.install_crash_handler(app)
diagnostics.install_request_logger(app)


# ─── Performance instrumentation ─────────────────────────────────────────────
# Times the costing-critical requests and appends them to logs/perf.jsonl for
# the admin Performance page. Best-effort — perf.record swallows all errors.
from . import perf as _perf

_PERF_EXACT_PATHS = {"/api/calculate", "/calculator", "/calculator2"}

@app.middleware("http")
async def perf_middleware(request: Request, call_next):
    _path = request.url.path
    _track = (_path in _PERF_EXACT_PATHS
              or (_path.startswith("/api/trailers/") and _path.endswith("/bom")))
    if not _track:
        return await call_next(request)
    _t0 = time.monotonic()
    _response = await call_next(request)
    _dur_ms = (time.monotonic() - _t0) * 1000.0
    # Endpoints can opt into stage-level breakdown by setting request.state.perf_extra
    # to a dict of {stage_name: duration_ms}. Picked up here so the perf log has
    # both the total and the per-stage timings for that record.
    _extra = getattr(request.state, "perf_extra", None) if hasattr(request, "state") else None
    _perf.record("server", _path, _dur_ms, cold=_perf.is_cold(), extra=_extra)
    return _response


# ─── CSRF protection middleware ──────────────────────────────────────────────
_CSRF_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
_CSRF_EXEMPT_PATHS = {"/login", "/logout", "/login/change-password"}

@app.middleware("http")
async def csrf_middleware(request: Request, call_next):
    # Inject CSRF token into request.state for every request (templates read it)
    sid = request.cookies.get("session_id")
    csrf_token = ""
    if sid:
        _mdb = SessionLocal()
        try:
            row = _sess_get(_mdb, sid)
            if row:
                csrf_token = row.csrf_token or ""
        except Exception:
            pass
        finally:
            _mdb.close()
    request.state.csrf_token = csrf_token

    # Only validate on state-changing methods
    if request.method in _CSRF_SAFE_METHODS:
        return await call_next(request)

    # Exempt pre-auth and logout paths
    if request.url.path in _CSRF_EXEMPT_PATHS:
        return await call_next(request)

    # If there's no session the endpoint will reject the request via require_user/require_admin
    if not csrf_token:
        return await call_next(request)

    submitted = request.headers.get("X-CSRF-Token", "")

    # Fallback: classic HTML <form> POSTs carry the token as a form field
    # named "csrf_token". Read the body once, cache it, and replace the
    # receive channel so the downstream handler can re-read it normally.
    if not submitted:
        ctype = request.headers.get("content-type", "")
        if ctype.startswith("application/x-www-form-urlencoded") or ctype.startswith("multipart/form-data"):
            try:
                body_bytes = await request.body()
                async def _replay_receive(_b=body_bytes):
                    return {"type": "http.request", "body": _b, "more_body": False}
                request._receive = _replay_receive
                if ctype.startswith("application/x-www-form-urlencoded"):
                    from urllib.parse import parse_qs
                    fields = parse_qs(body_bytes.decode("utf-8", errors="replace"))
                    submitted = (fields.get("csrf_token") or [""])[0]
                else:
                    # multipart — only parse if not too large
                    if len(body_bytes) < 5 * 1024 * 1024:
                        form = await request.form()
                        submitted = form.get("csrf_token", "") or ""
            except Exception as e:
                logger.warning(f"CSRF form-field fallback failed on {request.url.path}: {e}")

    if not submitted:
        logger.warning(f"CSRF token missing on {request.method} {request.url.path}")
        return JSONResponse({"detail": "CSRF token missing"}, status_code=403)

    if not secrets.compare_digest(csrf_token, submitted):
        logger.warning(f"CSRF token mismatch on {request.method} {request.url.path}")
        return JSONResponse({"detail": "CSRF token invalid"}, status_code=403)

    return await call_next(request)


# ─── Security headers middleware ─────────────────────────────────────────────
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    # Clickjacking protection. The Icecold Bodies MES mockup embeds /calculator
    # in an iframe from localhost:5173 / localhost:4173, so we rely on CSP
    # frame-ancestors (below) — which modern browsers honour over the legacy
    # X-Frame-Options header — to allow those origins and nothing else.
    # Prevent MIME-type sniffing
    response.headers["X-Content-Type-Options"] = "nosniff"
    # XSS protection (legacy browsers)
    response.headers["X-XSS-Protection"] = "1; mode=block"
    # Strict Transport Security — force HTTPS for 1 year, include subdomains
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # Referrer policy — send origin only on cross-origin requests
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # Permissions policy — disable unnecessary browser features
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    # Content Security Policy — allow own resources, inline styles/scripts (needed for Jinja2 templates)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
        "worker-src 'self' blob: https://cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "font-src 'self'; "
        # Allow the Icecold Bodies MES React mockup to embed /calculator
        # (and any other page) in an iframe during the discovery phase.
        "frame-ancestors 'self' http://localhost:5173 http://127.0.0.1:5173 http://localhost:4173 http://127.0.0.1:4173"
    )
    # Hide server identity
    response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
    return response


@app.on_event("startup")
def on_startup():
    from .database import get_db_info
    db_env, db_detail, db_is_prod = get_db_info()
    logger.info(f"=== BurtCost starting up === DB: {db_env} — {db_detail}")
    try:
        init_db()
        seed()
        logger.info("Database initialised and seed complete")
    except Exception as e:
        logger.error(f"Database initialization/seed failed: {e}", exc_info=True)
        print("WARNING: Database initialization/seed failed on startup; app may continue but DB may be incomplete:", e)
    try:
        from .routers.import_excel import _apply_excel_folder_setting as _aefs; _aefs()
    except Exception as e:
        logger.warning(f"Could not apply excel folder setting on startup: {e}")
    # Lazy commodity-quote refresh: if the latest quote is >24h old (or missing),
    # spin up a background thread to re-fetch from Yahoo. Only when the feature
    # is enabled. Belt-and-braces backup for prod cron; primary path for dev.
    try:
        _maybe_refresh_commodity_quotes_async()
    except Exception as e:
        logger.warning(f"Lazy commodity refresh skipped: {e}")
    try:
        _mdb = SessionLocal()
        deleted = _mdb.query(UserSession).filter(
            UserSession.expires_at < datetime.now(timezone.utc)
        ).delete()
        _mdb.commit()
        _mdb.close()
        if deleted:
            logger.info(f"Purged {deleted} expired session(s) on startup")
    except Exception as e:
        logger.warning(f"Session cleanup on startup skipped: {e}")


def _maybe_refresh_commodity_quotes_async():
    import threading
    from .database import SessionLocal as _SL
    db = _SL()
    try:
        enabled_row = db.query(AdminSetting).filter_by(key="commodity_trends_enabled").first()
        if not (enabled_row and enabled_row.value == "1"):
            return  # feature off, skip silently
        latest = db.query(CommodityQuote).order_by(CommodityQuote.date.desc()).first()
        if latest:
            age = datetime.now(timezone.utc) - (latest.date if latest.date.tzinfo else latest.date.replace(tzinfo=timezone.utc))
            if age < timedelta(hours=24):
                return  # data is fresh
    finally:
        db.close()

    def _bg():
        try:
            from tools.fetch_commodity_quotes import run_fetch
            run_fetch(verbose=False)
            logger.info("Lazy commodity refresh completed")
        except Exception as e:
            logger.warning(f"Lazy commodity refresh failed: {e}")

    threading.Thread(target=_bg, daemon=True, name="commodity-refresh").start()
    logger.info("Lazy commodity refresh kicked off in background")



BASE_DIR = os.path.dirname(__file__)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
# ── React MES single-page app (WO v4.12) ─────────────────────────────────────
# Served under /mes-app/ in unified mode. The existing Jinja /mes skin and every
# other route (/, /calculator, /api/*, /static) are untouched. Assets are mounted
# before the SPA catch-all so hashed bundles win over the index fallback.
_FRONTEND_DIST = settings.FRONTEND_DIST
_FRONTEND_INDEX = os.path.join(_FRONTEND_DIST, "index.html")
_FRONTEND_ASSETS = os.path.join(_FRONTEND_DIST, "assets")
if os.path.isdir(_FRONTEND_ASSETS):
    app.mount("/mes-app/assets", StaticFiles(directory=_FRONTEND_ASSETS), name="mes_app_assets")


@app.get("/mes-app", include_in_schema=False)
@app.get("/mes-app/{full_path:path}", include_in_schema=False)
async def serve_mes_app(full_path: str = ""):
    """Serve the React MES SPA (BrowserRouter). Any non-asset path under
    /mes-app/ returns index.html so client-side routing and deep links work."""
    if os.path.isfile(_FRONTEND_INDEX):
        # no-cache (revalidate, NOT no-store): the browser re-checks index.html every load, so a rebuilt
        # SPA's new hashed bundle is always picked up — without this the browser heuristically caches
        # index.html and serves stale (potentially crashing) asset references until a hard refresh. The
        # hashed /mes-app/assets/* themselves stay immutably cacheable. (WO v4.35 §3.3b.)
        return FileResponse(_FRONTEND_INDEX, headers={"Cache-Control": "no-cache"})
    return HTMLResponse(
        "<h1>MES app not built</h1><p>Run <code>npm --prefix frontend run build</code> "
        "or <code>scripts\\setup.bat</code> to build the React app, then reload.</p>",
        status_code=503,
    )
# templates imported from .templates_config (see import block above)

# ── Theme + nav-group cache (avoids a DB round-trip on every request) ─────────
_theme_cache: dict = {"theme": None, "nav_groups": None, "expires": 0.0}
_NAV_GROUP_DEFAULTS = {
    "nav_group_bodies":  "Bodies",
    "nav_group_chassis": "Chassis",
    "nav_group_pricing": "Pricing Formulas",
    "nav_group_bom":     "BOM",
    "nav_group_2": "Form Setup",
    "nav_group_3": "User Setup",
}
_THEME_TTL = 60  # seconds — refresh at most once per minute


def _load_theme_from_db() -> tuple:
    """Query DB once and return (theme_ns, nav_groups). Cached by caller."""
    nav_groups = dict(_NAV_GROUP_DEFAULTS)
    theme = None
    db = None
    try:
        db = next(get_db())
        from .database import Theme
        from types import SimpleNamespace
        _t = db.query(Theme).filter_by(is_active=True).first()
        if _t:
            theme = SimpleNamespace(
                css_path=_t.css_path, name=_t.name, id=_t.id,
                is_active=_t.is_active, is_default=_t.is_default,
            )
        rows = db.query(AdminSetting).filter(AdminSetting.key.in_(list(_NAV_GROUP_DEFAULTS))).all()
        for row in rows:
            nav_groups[row.key] = row.value
    except Exception:
        pass
    finally:
        if db is not None:
            try: db.rollback()
            except Exception: pass
            try: db.close()
            except Exception: pass
    return theme, nav_groups


@app.middleware("http")
async def load_active_theme(request: Request, call_next):
    # Skip DB entirely for static-asset requests
    if request.url.path.startswith("/static/"):
        return await call_next(request)

    now = time.monotonic()
    if now >= _theme_cache["expires"]:
        theme, nav_groups = _load_theme_from_db()
        _theme_cache["theme"]      = theme
        _theme_cache["nav_groups"] = nav_groups
        _theme_cache["expires"]    = now + _THEME_TTL

    request.state.theme      = _theme_cache["theme"]
    request.state.nav_groups = dict(_theme_cache["nav_groups"])

    # WO v4.7 — MES skin trigger REMOVED. The skin was previously toggled here
    # via a query param / cookie / referer check, and base.html loaded the
    # overlay stylesheet conditionally. That trigger leaked into direct browser
    # visits whenever the sticky cookie was set. The MES mockup now uses the
    # forked /mes/dashboard and /mes/calculator routes whose templates load
    # theme-mes.css unconditionally, so no middleware-level toggle is needed.
    # Set the flag to False so any templates still referencing it stay dormant.
    request.state.mes_skin = False
    return await call_next(request)


# get_current_user, require_user, require_admin, user_can, require_perm,
# _resolve_*, _sess_get/_sess_touch, _login_*, _is_localhost, _get_client_ip
# are all imported from .deps and .services above.








_ROOT = Path(__file__).parent.parent  # project root


def _app_version() -> str:
    """Return the current version.
    Priority: 1) git tag (dev only)  2) VERSION file (production)  3) 'dev'
    """
    # Try git first (works locally where git is on PATH)
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            capture_output=True, text=True, cwd=_ROOT
        )
        tag = result.stdout.strip()
        if tag:
            return tag
    except Exception:
        pass
    # Fall back to VERSION file written by the release process
    version_file = _ROOT / "VERSION"
    try:
        return version_file.read_text(encoding="utf-8").strip()
    except Exception:
        return "dev"


_APP_VERSION = _app_version()  # read once at startup

# Expose as Jinja2 globals so base.html can use them everywhere
templates.env.globals["is_dev_mode"] = _is_dev_mode
templates.env.globals["app_version"] = _APP_VERSION

# Register /debug/health now that _APP_VERSION + require_admin both exist.
diagnostics.register_health_routes(app, _APP_VERSION)


