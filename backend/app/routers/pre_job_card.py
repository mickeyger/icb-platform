"""Pre-Job Card + Repair-phase + Sign-off + Planning-ack endpoints for the
Icecold Bodies MES integration.

Addendum v1.2.1 endpoints:
  POST /api/calculations/{id}/pre-job-card    accepted -> pre_job_sent
  POST /api/calculations/{id}/pre-job-confirm pre_job_sent -> pre_job_confirmed
                                              (assigns job_number_assigned)
  POST /api/calculations/{id}/schedule-repair store phase plan for a Repair quote

Work Order v4 endpoints:
  POST /api/calculations/{id}/pre-job-signoff records a role sign-off; when BOTH
                                              roles have signed, auto-progresses
                                              status through pre_job_confirmed
                                              (transient) to 'planning' in one
                                              transaction.
  POST /api/calculations/{id}/planning-ack    Planning role acknowledges receipt
                                              of the new job on the Planning Board.

Plus one demo-only convenience endpoint:
  POST /api/mes/autologin                     issue a session for a configured user
                                              (gated to MES origins; demo only).

Each endpoint is additive: existing /accept and /decline endpoints continue to
behave exactly as before.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .. import database as _dbmod
from ..database import CalculationRecord, User, UserSession, get_db
from ..deps import get_current_user, _is_localhost

logger = logging.getLogger("burtcost")

# Origins permitted to call /api/mes/autologin. Mirrors the CORS list in main.py.
_MES_ORIGINS = {
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
}


def _mes_autologin_user() -> str | None:
    """Return the username the MES iframe should auto-log-in as, or None if
    auto-login is disabled. Defaults to 'admin' on localhost dev so the demo
    works out of the box; can be overridden or disabled via env."""
    explicit = os.environ.get("MES_DEMO_AUTOLOGIN_USER")
    if explicit is not None:
        return explicit or None  # empty string disables
    # Implicit default: enabled in dev (no PASSENGER env vars).
    if os.environ.get("PASSENGER_APP_ENV") or os.environ.get("PASSENGER_BASE_URI"):
        return None
    return "admin"

router = APIRouter(prefix="/api/calculations", tags=["pre-job-card"])


def _record_or_404(record_id: int, db: Session) -> CalculationRecord:
    rec = db.query(CalculationRecord).filter_by(id=record_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Calculation not found")
    return rec


def _require_user(request: Request, db: Session):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@router.post("/{record_id}/pre-job-card")
async def api_pre_job_card_sent(record_id: int, request: Request, db: Session = Depends(get_db)):
    """Fire the Pre-Job Card event — Step 3 of the Icecold Bodies process.
    Transitions an Accepted costing to Pre-Job Sent and timestamps the send."""
    _require_user(request, db)
    rec = _record_or_404(record_id, db)
    if rec.status != "accepted":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot send Pre-Job Card from status '{rec.status}'. Costing must be Accepted.",
        )
    rec.status = "pre_job_sent"
    rec.pre_job_sent_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(rec)
    return {
        "ok": True,
        "id": rec.id,
        "quote_number": rec.quote_number,
        "status": rec.status,
        "mes_status": "Pre-Job Sent",
        "pre_job_sent_at": rec.pre_job_sent_at.strftime("%Y-%m-%d %H:%M"),
    }


@router.post("/{record_id}/pre-job-confirm")
async def api_pre_job_card_confirmed(record_id: int, request: Request, db: Session = Depends(get_db)):
    """Confirm the Pre-Job Card — recipients (Sales Rep + Production Manager) have
    reviewed and approved. Status moves to Pre-Job Confirmed and a production
    Job Number is assigned (mirrors the quote_number but in the production series)."""
    _require_user(request, db)
    rec = _record_or_404(record_id, db)
    if rec.status != "pre_job_sent":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot confirm from status '{rec.status}'. Pre-Job Card must be Sent first.",
        )
    rec.status = "pre_job_confirmed"
    rec.pre_job_confirmed_at = datetime.now(timezone.utc)
    # Simple deterministic job-number scheme for the demo: strip the Q- prefix from
    # the quote number, else fall back to the record id.
    if not rec.job_number_assigned:
        qn = (rec.quote_number or "").lstrip("Q-").strip()
        rec.job_number_assigned = qn or str(rec.id)
    db.commit()
    db.refresh(rec)
    return {
        "ok": True,
        "id": rec.id,
        "quote_number": rec.quote_number,
        "status": rec.status,
        "mes_status": "Pre-Job Confirmed",
        "job_number_assigned": rec.job_number_assigned,
        "pre_job_confirmed_at": rec.pre_job_confirmed_at.strftime("%Y-%m-%d %H:%M"),
    }


@router.post("/{record_id}/schedule-repair")
async def api_schedule_repair(record_id: int, request: Request, db: Session = Depends(get_db)):
    """Store the planner-selected Phase Entry Points for a Repair quote.
    Body: {"phases": [{"phase": "VACUUM", "bay_id": "VAC-2", "estimated_hours": 6}, ...]}
    """
    _require_user(request, db)
    rec = _record_or_404(record_id, db)
    if not rec.is_repair:
        raise HTTPException(
            status_code=409,
            detail="schedule-repair is only valid for Repair quotes (is_repair=True).",
        )
    body = await request.json()
    phases = body.get("phases")
    if not isinstance(phases, list) or not phases:
        raise HTTPException(status_code=400, detail="`phases` must be a non-empty list")
    # Light validation per phase entry.
    cleaned = []
    for p in phases:
        if not isinstance(p, dict) or "phase" not in p:
            raise HTTPException(status_code=400, detail="Each phase needs at least a `phase` key")
        cleaned.append({
            "phase":           str(p["phase"]),
            "bay_id":          str(p.get("bay_id", "")),
            "estimated_hours": float(p.get("estimated_hours", 0) or 0),
        })
    rec.repair_phases_json = json.dumps(cleaned)
    db.commit()
    db.refresh(rec)
    return {
        "ok": True,
        "id": rec.id,
        "quote_number": rec.quote_number,
        "repair_phases": cleaned,
    }


# ---------------------------------------------------------------------------
# Work Order v4 — Pre-Job sign-off + Planning acknowledge
# ---------------------------------------------------------------------------

def _record_snapshot(rec: CalculationRecord) -> dict:
    """Common JSON snapshot of a CalculationRecord for the signoff + ack endpoints."""
    def _ts(v): return v.strftime("%Y-%m-%d %H:%M") if v else None
    return {
        "id": rec.id,
        "quote_number": rec.quote_number,
        "status": rec.status,
        "pre_job_sent_at":      _ts(rec.pre_job_sent_at),
        "pre_job_confirmed_at": _ts(rec.pre_job_confirmed_at),
        "job_number_assigned":  rec.job_number_assigned,
        "pre_job_signoff_sales_at":      _ts(rec.pre_job_signoff_sales_at),
        "pre_job_signoff_sales_by":      rec.pre_job_signoff_sales_by,
        "pre_job_signoff_production_at": _ts(rec.pre_job_signoff_production_at),
        "pre_job_signoff_production_by": rec.pre_job_signoff_production_by,
        "planning_acknowledged_at":      _ts(rec.planning_acknowledged_at),
        "planning_acknowledged_by":      rec.planning_acknowledged_by,
    }


@router.post("/{record_id}/pre-job-signoff")
async def api_pre_job_signoff(record_id: int, request: Request, db: Session = Depends(get_db)):
    """Record one of the two Pre-Job Card sign-offs. When BOTH are recorded the
    status auto-progresses through pre_job_confirmed (transient) to 'planning'
    in a single transaction, with job_number_assigned populated."""
    user = _require_user(request, db)
    rec = _record_or_404(record_id, db)
    if rec.status != "pre_job_sent":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot sign off from status '{rec.status}'. Costing must be Pre-Job Sent.",
        )
    body = await request.json()
    role = str(body.get("role", "")).lower().strip()
    if role not in ("sales", "production"):
        raise HTTPException(status_code=400, detail="`role` must be 'sales' or 'production'")
    attestation = str(body.get("attestation") or "").strip()
    if not attestation:
        raise HTTPException(status_code=400, detail="`attestation` text is required")
    now_utc = datetime.now(timezone.utc)
    if role == "sales":
        if rec.pre_job_signoff_sales_at is not None:
            raise HTTPException(status_code=409, detail="Sales sign-off already recorded for this quote")
        rec.pre_job_signoff_sales_at          = now_utc
        rec.pre_job_signoff_sales_by          = user.username
        rec.pre_job_signoff_sales_attestation = attestation
    else:
        if rec.pre_job_signoff_production_at is not None:
            raise HTTPException(status_code=409, detail="Production sign-off already recorded for this quote")
        rec.pre_job_signoff_production_at          = now_utc
        rec.pre_job_signoff_production_by          = user.username
        rec.pre_job_signoff_production_attestation = attestation
    # If both signoffs are now in, atomically progress pre_job_sent -> pre_job_confirmed
    # -> planning in one transaction. The pre_job_confirmed state is transient — the
    # MES dashboard only ever shows Pre-Job Sent then Planning.
    auto_progressed = False
    if rec.pre_job_signoff_sales_at is not None and rec.pre_job_signoff_production_at is not None:
        rec.status               = "pre_job_confirmed"
        rec.pre_job_confirmed_at = now_utc
        if not rec.job_number_assigned:
            qn = (rec.quote_number or "").lstrip("Q-").strip()
            rec.job_number_assigned = qn or str(rec.id)
        rec.status = "planning"
        auto_progressed = True
    db.commit()
    db.refresh(rec)
    snap = _record_snapshot(rec)
    snap["role_signed"]     = role
    snap["auto_progressed"] = auto_progressed
    snap["mes_status"]      = "Planning" if auto_progressed else "Pre-Job Sent"
    return snap


@router.post("/{record_id}/chassis-eta")
async def api_chassis_eta(record_id: int, request: Request, db: Session = Depends(get_db)):
    """Capture the chassis-arrival ETA (Work Order v4.2). Gates the Planning
    Acknowledge button — without an ETA, planning-ack stays unreachable.

    Body: {chassis_eta: ISO8601, chassis_vin?, chassis_model?, customer_dealer?,
           tail_lift_code?, chassis_inhouse_bom?: [{category, description, item_code}]}.
    """
    user = _require_user(request, db)
    rec = _record_or_404(record_id, db)
    if rec.status != "planning":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot capture chassis ETA from status '{rec.status}'. Costing must be Planning.",
        )
    body = await request.json()
    eta_raw = body.get("chassis_eta")
    if not eta_raw:
        raise HTTPException(status_code=400, detail="`chassis_eta` (ISO8601) is required")
    try:
        # Accept either "YYYY-MM-DD" or full ISO8601.
        rec.chassis_eta = datetime.fromisoformat(str(eta_raw).replace("Z", "+00:00"))
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"`chassis_eta` is not a valid ISO date: {e}")
    rec.chassis_eta_captured_at = datetime.now(timezone.utc)
    rec.chassis_eta_captured_by = user.username
    # Stash the rest of the chassis payload as a JSON blob (matches repair_phases_json pattern).
    payload = {}
    for k in ("chassis_vin", "chassis_model", "customer_dealer", "tail_lift_code"):
        v = body.get(k)
        if v is not None:
            payload[k] = str(v)
    bom = body.get("chassis_inhouse_bom")
    if isinstance(bom, list) and bom:
        clean_bom = []
        for row in bom:
            if not isinstance(row, dict):
                continue
            clean_bom.append({
                "category":    str(row.get("category", "")),
                "description": str(row.get("description", "")),
                "item_code":   str(row.get("item_code", "")),
            })
        payload["chassis_inhouse_bom"] = clean_bom
    rec.chassis_data_json = json.dumps(payload) if payload else None
    db.commit()
    db.refresh(rec)
    return {
        "ok": True,
        "id": rec.id,
        "quote_number": rec.quote_number,
        "chassis_eta": rec.chassis_eta.strftime("%Y-%m-%d %H:%M") if rec.chassis_eta else None,
        "chassis_eta_captured_at": rec.chassis_eta_captured_at.strftime("%Y-%m-%d %H:%M"),
        "chassis_eta_captured_by": rec.chassis_eta_captured_by,
        "chassis_data": payload,
    }


@router.post("/{record_id}/chassis-received")
async def api_chassis_received(record_id: int, request: Request, db: Session = Depends(get_db)):
    """Confirm the chassis has physically arrived at Icecold (Work Order v4.3).
    Tick box on the job card. Records receipt date + the user who confirmed.

    Body: {received_at?: ISO date — defaults to now; received?: bool — false to UN-tick}.
    Gated: chassis_eta must have been captured first (the ETA flow had to run).
    """
    user = _require_user(request, db)
    rec = _record_or_404(record_id, db)
    if rec.chassis_eta is None:
        raise HTTPException(
            status_code=409,
            detail="Capture the chassis ETA first before marking it received.",
        )
    body = await request.json() if (await request.body()) else {}
    received_flag = body.get("received", True)
    if not received_flag:
        # Un-tick (mistake correction)
        rec.chassis_received_at = None
        rec.chassis_received_by = None
        db.commit(); db.refresh(rec)
        return {
            "ok": True, "id": rec.id, "quote_number": rec.quote_number,
            "chassis_received_at": None, "chassis_received_by": None,
        }
    raw = body.get("received_at")
    if raw:
        try:
            rec.chassis_received_at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except (ValueError, TypeError) as e:
            raise HTTPException(status_code=400, detail=f"`received_at` is not a valid ISO date: {e}")
    else:
        rec.chassis_received_at = datetime.now(timezone.utc)
    rec.chassis_received_by = user.username
    db.commit(); db.refresh(rec)
    return {
        "ok": True,
        "id": rec.id,
        "quote_number": rec.quote_number,
        "chassis_received_at": rec.chassis_received_at.strftime("%Y-%m-%d %H:%M"),
        "chassis_received_by": rec.chassis_received_by,
    }


@router.post("/{record_id}/planning-ack")
async def api_planning_ack(record_id: int, request: Request, db: Session = Depends(get_db)):
    """Planning role acknowledges receipt of the new job on the Planning Board.
    Stops the pulsing card + dashboard pill."""
    user = _require_user(request, db)
    rec = _record_or_404(record_id, db)
    if rec.status != "planning":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot acknowledge from status '{rec.status}'. Costing must be Planning.",
        )
    if rec.planning_acknowledged_at is not None:
        raise HTTPException(status_code=409, detail="Planning acknowledgement already recorded for this quote")
    rec.planning_acknowledged_at = datetime.now(timezone.utc)
    rec.planning_acknowledged_by = user.username
    db.commit()
    db.refresh(rec)
    snap = _record_snapshot(rec)
    snap["mes_status"] = "Planning"
    return snap


# ---------------------------------------------------------------------------
# Demo-only MES auto-login (Addendum v1.2.1)
# ---------------------------------------------------------------------------
# The React MES mockup embeds /calculator in an iframe. Without a session the
# iframe shows the login form, forcing the demo presenter to sign in twice.
# This endpoint lets the MES app fetch a session cookie for the calculator
# domain on startup. Gated by:
#   1. Request Origin must be one of the four whitelisted MES dev origins.
#   2. MES_DEMO_AUTOLOGIN_USER env var (defaults to 'admin' on localhost dev;
#      set to empty string to disable, or to a specific username to override).
# In production (Passenger) the implicit default is *disabled* — set the env
# var explicitly to enable.

demo_router = APIRouter(prefix="/api/mes", tags=["mes-demo"])


@demo_router.post("/autologin")
async def api_mes_autologin(request: Request, db: Session = Depends(get_db)):
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    # Allow startswith for referer (which includes a path) or exact match for origin.
    if not any(origin == o or origin.startswith(o + "/") for o in _MES_ORIGINS):
        raise HTTPException(status_code=403, detail="Origin not permitted for autologin")
    username = _mes_autologin_user()
    if not username:
        raise HTTPException(status_code=403, detail="MES autologin disabled (set MES_DEMO_AUTOLOGIN_USER)")

    # Mirror /login's db_choice swap so the MES sees the same database the
    # interactive login form would: dev = SQLITE_URL, prod = MYSQL_URL.
    # Default 'dev' matches the form's default for local users. Whichever auth
    # path (form or autologin) ran last sets the process-wide engine — so when
    # both converge on the same db_choice the iframe and direct browser see
    # identical data. Localhost gate matches /login (line 46 of auth.py).
    db_choice = os.environ.get("MES_DEMO_AUTOLOGIN_DB", "dev").lower()
    if db_choice in ("dev", "prod") and _is_localhost(request):
        target_url = os.environ.get(
            "SQLITE_URL" if db_choice == "dev" else "MYSQL_URL", ""
        )
        if target_url:
            _dbmod.switch_db(target_url)
            db = next(_dbmod.get_db())  # use the new engine for the lookup below
    # If an existing session is already valid, no need to mint a new one.
    sid = request.cookies.get("session_id")
    if sid:
        existing = db.query(UserSession).filter_by(id=sid).first()
        if existing and existing.expires_at and existing.expires_at > datetime.now(timezone.utc):
            user = db.query(User).filter_by(id=existing.user_id).first()
            if user:
                return JSONResponse({"ok": True, "already": True, "user": user.username, "role": user.role})
    user = db.query(User).filter_by(username=username).first()
    if not user:
        raise HTTPException(status_code=500, detail=f"Autologin user '{username}' not found in DB")
    new_sid = str(uuid.uuid4())
    now_utc = datetime.now(timezone.utc)
    db.add(UserSession(
        id           = new_sid,
        user_id      = user.id,
        role         = user.role,
        csrf_token   = secrets.token_hex(32),
        login_at     = now_utc,
        last_seen_at = now_utc,
        expires_at   = now_utc + timedelta(hours=8),
    ))
    user.last_login_at = now_utc
    db.commit()
    logger.info(f"MES autologin: '{username}' from {origin}")
    response = JSONResponse({"ok": True, "already": False, "user": user.username, "role": user.role})
    # SameSite=Lax works for cross-port same-site iframes (localhost:5173 ->
    # localhost:8000 share eTLD+1 'localhost' under the SameSite spec). The
    # cookie is therefore sent when the MES iframe loads /calculator.
    response.set_cookie(
        "session_id", new_sid,
        httponly=True,
        secure=False,        # plain HTTP on localhost
        samesite="lax",
        max_age=8 * 3600,
    )
    # WO v4.7 — Sticky `mes_skin` cookie REMOVED. It was leaking the MES skin
    # into direct browser visits of the live app at / and /calculator. The MES
    # mockup now embeds /mes/dashboard and /mes/calculator (forked templates
    # with the skin baked in), so a marker cookie is no longer needed. We also
    # delete any previously-set cookie so existing browsers self-heal.
    response.delete_cookie("mes_skin")
    return response


