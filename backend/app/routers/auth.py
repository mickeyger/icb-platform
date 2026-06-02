import os
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Request, APIRouter, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db, User, UserSession
from ..deps import (
    pwd_context,
    _login_ctx, _is_localhost, _get_client_ip,
    _is_rate_limited, _record_failed_attempt, _clear_attempts,
    _login_attempts, _LOCKOUT_SECONDS,
)
from ..templates_config import templates
from ..auth import get_auth_provider

import logging
logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    return templates.TemplateResponse("login.html", _login_ctx(request, error))


@router.post("/login")
async def login_post(request: Request, username: str = Form(...),
                     password: str = Form(...),
                     db: Session = Depends(get_db)):
    client_ip = _get_client_ip(request)
    is_local  = _is_localhost(request)  # used below for the session-cookie Secure flag

    if _is_rate_limited(client_ip):
        logger.warning(f"Login rate-limited for IP {client_ip}")
        remaining = int(_LOCKOUT_SECONDS - (time.time() - _login_attempts[client_ip][0]))
        return templates.TemplateResponse("login.html",
            _login_ctx(request, f"Too many failed attempts — try again in {remaining // 60 + 1} minutes"))

    try:
        # WO v4.12: authentication runs through the pluggable AuthProvider
        # (email/password in Phase 1). Returns the user on success, None on
        # invalid credentials; DB/infra errors propagate to the except below.
        user = get_auth_provider().authenticate(db, username, password)
    except Exception as e:
        logger.error(f"Login DB error from {client_ip}: {e}")
        return templates.TemplateResponse("login.html",
            _login_ctx(request, "Database unavailable — please try again shortly"))

    if not user:
        _record_failed_attempt(client_ip)
        logger.warning(f"Failed login attempt for '{username}' from {client_ip}")
        return templates.TemplateResponse("login.html",
            _login_ctx(request, "Invalid credentials"))

    _clear_attempts(client_ip)
    logger.info(f"Successful login: '{username}' from {client_ip}")

    sid = str(uuid.uuid4())
    now_utc = datetime.now(timezone.utc)
    db.add(UserSession(
        id           = sid,
        user_id      = user.id,
        role         = user.role,
        csrf_token   = secrets.token_hex(32),
        login_at     = now_utc,
        last_seen_at = now_utc,
        expires_at   = now_utc + timedelta(hours=8),
    ))
    user.last_login_at = now_utc
    db.commit()
    response = RedirectResponse(url="/", status_code=303)
    # ELECTRON FAILOVER - allow the session cookie to persist over a plain-HTTP
    # LAN. The desktop client reaches this server at http://<lan-ip>:8080 (no
    # TLS), so Host is not localhost and the cookie would otherwise be marked
    # Secure and silently dropped by the browser, bouncing the user back to the
    # login screen. When TCM_INSECURE_COOKIES=1 (set only on the intranet
    # failover server's .env), never mark the cookie Secure. Default behaviour is
    # unchanged, so HTTPS production is unaffected.
    _insecure_cookies = os.environ.get("TCM_INSECURE_COOKIES", "") == "1"
    response.set_cookie(
        "session_id", sid,
        httponly=True,
        secure=False if _insecure_cookies else (not is_local),
        samesite="lax",
        max_age=8 * 3600,
    )
    return response


@router.post("/login/change-password")
async def login_change_password(request: Request,
                                username: str = Form(...),
                                current_password: str = Form(...),
                                new_password: str = Form(...),
                                confirm_password: str = Form(...),
                                db: Session = Depends(get_db)):
    client_ip = _get_client_ip(request)

    if _is_rate_limited(client_ip):
        remaining = int(_LOCKOUT_SECONDS - (time.time() - _login_attempts[client_ip][0]))
        ctx = _login_ctx(request, f"Too many failed attempts — try again in {remaining // 60 + 1} minutes")
        ctx["show_change"] = True
        return templates.TemplateResponse("login.html", ctx)

    def _err(msg):
        ctx = _login_ctx(request, msg)
        ctx["show_change"] = True
        ctx["change_username"] = username
        return templates.TemplateResponse("login.html", ctx)

    if not new_password or len(new_password) < 6:
        return _err("New password must be at least 6 characters")
    if new_password != confirm_password:
        return _err("New password and confirmation do not match")
    if new_password == current_password:
        return _err("New password must be different from current password")

    try:
        user = db.query(User).filter_by(username=username).first()
    except Exception as e:
        logger.error(f"Password-change DB error from {client_ip}: {e}")
        return _err("Database unavailable — please try again shortly")

    if not user or not pwd_context.verify(current_password, user.password_hash):
        _record_failed_attempt(client_ip)
        logger.warning(f"Failed password-change for '{username}' from {client_ip}")
        return _err("Invalid username or current password")

    user.password_hash = pwd_context.hash(new_password)
    db.commit()
    _clear_attempts(client_ip)
    logger.info(f"Password changed for '{username}' from {client_ip}")

    ctx = _login_ctx(request, "")
    ctx["notice"] = "Password updated — please sign in with your new password"
    return templates.TemplateResponse("login.html", ctx)


@router.get("/logout")
async def logout(request: Request, db: Session = Depends(get_db)):
    sid = request.cookies.get("session_id")
    if sid:
        row = db.query(UserSession).filter_by(id=sid).first()
        if row:
            db.delete(row)
            db.commit()
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("session_id")
    return response
