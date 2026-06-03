"""Shared FastAPI dependencies: auth, sessions, permissions."""

import secrets
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .database import (
    get_db, SessionLocal,
    User, UserSession, Branch,
    Permission, RolePermission, UserPermission,
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ── DB-backed session helpers ─────────────────────────────────────────────────
_SESS_TOUCH_INTERVAL = timedelta(seconds=60)


def _sess_get(db, sid: str):
    """Return the UserSession row if it exists and has not expired, else None."""
    if not sid:
        return None
    now = datetime.now(timezone.utc)
    row = db.query(UserSession).filter_by(id=sid).first()
    if not row:
        return None
    exp = row.expires_at
    if exp:
        if not exp.tzinfo:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < now:
            db.delete(row)
            db.commit()
            return None
    return row


def _sess_touch(db, row) -> None:
    """Update last_seen_at, throttled to at most once per _SESS_TOUCH_INTERVAL."""
    now = datetime.now(timezone.utc)
    last = row.last_seen_at
    if last:
        if not last.tzinfo:
            last = last.replace(tzinfo=timezone.utc)
        if (now - last) < _SESS_TOUCH_INTERVAL:
            return
    row.last_seen_at = now
    db.commit()


# ── Auth helpers ──────────────────────────────────────────────────────────────

def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    sid = request.cookies.get("session_id")
    row = _sess_get(db, sid)
    if not row:
        return None
    _sess_touch(db, row)
    return db.query(User).filter_by(id=row.user_id).first()


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = get_current_user(request, db)
    if not user:
        if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
            raise HTTPException(status_code=401, detail="Session expired — please log in again")
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


def require_admin(request: Request, db: Session = Depends(get_db)) -> User:
    user = require_user(request, db)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# ── Permissions ────────────────────────────────────────────────────────────────

def _user_permission_set(user: User, db: Session) -> set[str]:
    rows = (db.query(Permission.name)
              .join(RolePermission, RolePermission.permission_id == Permission.id)
              .filter(RolePermission.role == user.role)
              .all())
    perms = {r[0] for r in rows}
    overrides = (db.query(Permission.name, UserPermission.effect)
                   .join(UserPermission, UserPermission.permission_id == Permission.id)
                   .filter(UserPermission.user_id == user.id)
                   .all())
    for name, effect in overrides:
        if effect == "allow":
            perms.add(name)
        elif effect == "deny":
            perms.discard(name)
    return perms


def user_can(user: Optional[User], permission: str, db: Optional[Session] = None) -> bool:
    if user is None:
        return False
    if user.role == "admin":
        return True
    cached = getattr(user, "_perm_cache", None)
    if cached is None:
        own_db = db is None
        if own_db:
            db = SessionLocal()
        try:
            cached = _user_permission_set(user, db)
        finally:
            if own_db:
                db.close()
        try:
            user._perm_cache = cached
        except Exception:
            pass
    return permission in cached


def require_perm(permission: str):
    """FastAPI dependency factory: gate a route on a named permission.

    Uses `Depends(require_user)` (not a direct call) so the single auth path is
    reused AND test overrides of `require_user` propagate through the gate.
    Behaviour in production is identical (require_user still resolves the session)."""
    def _dep(user: User = Depends(require_user), db: Session = Depends(get_db)) -> User:
        if not user_can(user, permission, db):
            raise HTTPException(status_code=403, detail=f"Permission denied: {permission}")
        return user
    return _dep


# WO v4.16: the spec names the gate `require_permission`; it is the existing
# `require_perm` factory above (reused, not duplicated — see ADR 0010). Routers
# may import either name.
require_permission = require_perm


# ── Active branch (WO v4.16, ADR 0010) ────────────────────────────────────────

def current_session_id(request: Request) -> Optional[str]:
    """The raw session cookie id. A dependency so tests can override it."""
    return request.cookies.get("session_id")


def active_branch(session_id: Optional[str] = Depends(current_session_id),
                  db: Session = Depends(get_db)) -> Optional[Branch]:
    """The branch the session switched to, or None (lists then show all accessible).
    Session-held; default JHB is only a display default in GET /api/session — lists
    filter solely once a branch is explicitly chosen. See ADR 0010."""
    from .services import session as _sess
    return _sess.get_switched_branch(db, session_id)


# ── Network / request helpers ─────────────────────────────────────────────────

def _is_localhost(request: Request) -> bool:
    host = request.headers.get("host", "")
    return host.startswith("127.0.0.1") or host.startswith("localhost")


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ── Brute-force protection ─────────────────────────────────────────────────────
_login_attempts: dict[str, list[float]] = defaultdict(list)
_MAX_ATTEMPTS = 5
_LOCKOUT_SECONDS = 300


def _is_rate_limited(ip: str) -> bool:
    now = time.time()
    _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < _LOCKOUT_SECONDS]
    return len(_login_attempts[ip]) >= _MAX_ATTEMPTS


def _record_failed_attempt(ip: str):
    _login_attempts[ip].append(time.time())


def _clear_attempts(ip: str):
    _login_attempts.pop(ip, None)


def _login_ctx(request: Request, error: str = "") -> dict:
    from .database import get_db_info
    db_env, db_detail, db_is_prod = get_db_info()
    is_local = _is_localhost(request)
    return {
        "request": request, "error": error,
        "db_env": db_env, "db_detail": db_detail, "db_is_prod": db_is_prod,
        "is_local": is_local,
    }


def _is_dev_mode() -> bool:
    import os
    db_url = os.getenv("DATABASE_URL", "")
    if "sqlite" in db_url.lower() or db_url == "":
        return True
    return os.getenv("DEBUG", "").lower() in ("1", "true", "yes")
