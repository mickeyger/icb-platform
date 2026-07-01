from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta

from ..database import get_db, User, UserSession, Permission, RolePermission, UserPermission
from ..deps import (
    get_current_user, require_user, require_admin,
    user_can, pwd_context,
)
from ..templates_config import templates

router = APIRouter()

# Roles the admin UI may assign. Broadened in v1.39.3 (CA10): the legacy list was
# {user,full,admin} only — but the Phase-1 operational roles (sales/planner and the
# workshop-floor roles) are real, so editing a sales/planner user must not be forced to
# reset them to a legacy value. Kept permissive (free-string role column); this is the
# admin-UI guard, not a DB constraint.
_ASSIGNABLE_ROLES = ["user", "full", "admin", "sales", "planner",
                     "production", "workshop", "qc_inspector"]


@router.get("/api/users")
async def get_users(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    users = db.query(User).order_by(User.username).all()
    return [{
        "id": u.id,
        "username": u.username,
        "role": u.role,
        "email": u.email or "",
        "can_view_full_cost": u.can_view_full_cost,
        "created_at":    u.created_at.isoformat()    if u.created_at    else None,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    } for u in users]


@router.get("/api/users/online")
async def get_online_users(request: Request, db: Session = Depends(get_db)):
    """Snapshot of active sessions from the DB — accurate across all workers."""
    require_admin(request, db)
    ACTIVE_WINDOW_MIN = 5
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=ACTIVE_WINDOW_MIN)

    rows = db.query(UserSession).filter(UserSession.last_seen_at >= cutoff).all()
    by_user = {}
    for row in rows:
        last = row.last_seen_at
        if last and not last.tzinfo:
            last = last.replace(tzinfo=timezone.utc)
        login = row.login_at
        if login and not login.tzinfo:
            login = login.replace(tzinfo=timezone.utc)
        age_min = round((now - last).total_seconds() / 60, 1) if last else 0
        existing = by_user.get(row.user_id)
        if not existing or (last and last > existing["last_seen_at"]):
            by_user[row.user_id] = {
                "user_id":      row.user_id,
                "last_seen_at": last,
                "login_at":     login,
                "age_minutes":  age_min,
            }

    if not by_user:
        return {"active_window_minutes": ACTIVE_WINDOW_MIN, "users": []}

    users = db.query(User).filter(User.id.in_(list(by_user.keys()))).all()
    user_map = {u.id: u for u in users}
    out = []
    for uid, info in by_user.items():
        u = user_map.get(uid)
        if not u:
            continue
        login_at = info["login_at"]
        session_minutes = round((info["last_seen_at"] - login_at).total_seconds() / 60, 1) if login_at else None
        out.append({
            "user_id":         uid,
            "username":        u.username,
            "age_minutes":     info["age_minutes"],
            "last_seen_at":    info["last_seen_at"].isoformat(),
            "login_at":        login_at.isoformat() if login_at else None,
            "session_minutes": session_minutes,
        })
    out.sort(key=lambda x: x["age_minutes"])
    return {"active_window_minutes": ACTIVE_WINDOW_MIN, "users": out}


@router.put("/api/users/{user_id}/role")
async def update_user_role(user_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    role = str(body.get("role", "")).strip().lower()
    if role not in _ASSIGNABLE_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    u = db.query(User).filter_by(id=user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    u.role = role
    db.commit()
    return {"id": u.id, "role": u.role, "can_view_full_cost": u.can_view_full_cost}


# v1.39.3 (CA10) — admin-editable email so ops can update a signer's address without SQL.
# Empty is allowed (e.g. the admin account is never a check recipient); a non-empty value must
# be email-shaped. Admin-only, mirroring the /role + /password endpoints.
import re as _re

_EMAIL_RE = _re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.put("/api/users/{user_id}/email")
async def update_user_email(user_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    email = str(body.get("email", "")).strip()
    if email and not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Enter a valid email address (or leave blank)")
    u = db.query(User).filter_by(id=user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    u.email = email
    db.commit()
    return {"id": u.id, "username": u.username, "email": u.email}


@router.post("/api/users")
async def create_user(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    username = str(body.get("username", "")).strip()
    password = str(body.get("password", "")).strip()
    role = str(body.get("role", "user")).strip().lower()
    email = str(body.get("email", "")).strip()
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password required")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    if role not in _ASSIGNABLE_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    if email and not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Enter a valid email address (or leave blank)")
    if db.query(User).filter_by(username=username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    new_user = User(username=username, password_hash=pwd_context.hash(password),
                    role=role, email=email)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"id": new_user.id, "username": new_user.username,
            "role": new_user.role, "email": new_user.email or ""}


@router.put("/api/users/{user_id}/password")
async def change_password(user_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    body = await request.json()
    new_password = str(body.get("password", "")).strip()
    if not new_password or len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    u = db.query(User).filter_by(id=user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    u.password_hash = pwd_context.hash(new_password)
    db.commit()
    return {"id": u.id, "username": u.username}


@router.delete("/api/users/{user_id}")
async def delete_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    u = db.query(User).filter_by(id=user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    current_user = get_current_user(request, db)
    if current_user and current_user.id == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    db.delete(u)
    db.commit()
    return {"success": True}


@router.get("/api/permissions")
async def api_list_permissions(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    perms = db.query(Permission).order_by(Permission.category, Permission.name).all()
    return [{"id": p.id, "name": p.name, "description": p.description, "category": p.category}
            for p in perms]


@router.get("/api/users/{user_id}/permissions")
async def api_user_permissions(user_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    target = db.query(User).filter_by(id=user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    perms = db.query(Permission).order_by(Permission.category, Permission.name).all()
    role_defaults = {r[0] for r in (
        db.query(Permission.name)
          .join(RolePermission, RolePermission.permission_id == Permission.id)
          .filter(RolePermission.role == target.role).all()
    )}
    overrides = {row[0]: row[1] for row in (
        db.query(Permission.name, UserPermission.effect)
          .join(UserPermission, UserPermission.permission_id == Permission.id)
          .filter(UserPermission.user_id == target.id).all()
    )}
    rows = []
    for p in perms:
        role_def = (target.role == "admin") or (p.name in role_defaults)
        ovr = overrides.get(p.name)
        if target.role == "admin":
            effective = True
        elif ovr == "allow":
            effective = True
        elif ovr == "deny":
            effective = False
        else:
            effective = role_def
        rows.append({
            "name": p.name, "description": p.description, "category": p.category,
            "role_default": role_def, "override": ovr, "effective": effective,
        })
    return {
        "user": {"id": target.id, "username": target.username, "role": target.role},
        "permissions": rows,
    }


@router.put("/api/users/{user_id}/permissions/{perm_name}")
async def api_set_user_permission(
    user_id: int, perm_name: str, request: Request,
    payload: dict, db: Session = Depends(get_db),
):
    require_admin(request, db)
    target = db.query(User).filter_by(id=user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    perm = db.query(Permission).filter_by(name=perm_name).first()
    if not perm:
        raise HTTPException(status_code=404, detail="Permission not found")
    effect = (payload or {}).get("effect", "reset")
    if effect not in ("allow", "deny", "reset"):
        raise HTTPException(status_code=400, detail="effect must be allow, deny, or reset")
    existing = db.query(UserPermission).filter_by(
        user_id=target.id, permission_id=perm.id
    ).first()
    if effect == "reset":
        if existing:
            db.delete(existing)
    else:
        if existing:
            existing.effect = effect
        else:
            db.add(UserPermission(user_id=target.id, permission_id=perm.id, effect=effect))
    db.commit()
    return {"ok": True, "effect": effect}


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_manage_users(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login")
    if not user_can(user, "menu.users", db):
        raise HTTPException(status_code=403, detail="Not authorized")
    return templates.TemplateResponse("admin_manage_users.html", {
        "request": request, "user": user,
    })


@router.get("/admin/user-permissions", response_class=HTMLResponse)
async def admin_user_permissions(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or user.role != "admin":
        return RedirectResponse(url="/login")
    perms = db.query(Permission).order_by(Permission.category, Permission.name).all()
    grouped: dict[str, list] = {}
    for p in perms:
        grouped.setdefault(p.category or "general", []).append(p)
    return templates.TemplateResponse("admin_user_permissions.html", {
        "request": request, "user": user,
        "permission_groups": grouped,
    })
