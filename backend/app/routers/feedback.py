"""Feedback Portal API (WO v4.38).

Public (any logged-in user):
  GET    /api/feedback/health                 — {configured, model} (widget may gate AI hints on it)
  POST   /api/feedback                        — submit a report (multipart: user_text, page_url, screenshot?)
                                                → stores, classifies via Claude-Haiku, notifies, returns the ticket
  POST   /api/feedback/{ticket_id}/answer     — submit answers to the AI's clarifying questions

Admin only (the inbox):
  GET    /api/admin/feedback                  — list (filter by status)
  GET    /api/admin/feedback/{ticket_id}      — full detail
  PATCH  /api/admin/feedback/{ticket_id}      — update status / assignee / resolution notes
  GET    /api/admin/feedback/{ticket_id}/screenshot — serve the stored screenshot

The submit path NEVER fails on a downstream best-effort step: an unconfigured/failed
classifier leaves the AI fields NULL, and a delivery failure is logged — the ticket is
still stored and returned. Mirrors app/routers/help.py's defensive posture + rate limit.
"""
from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Request,
                     UploadFile)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import User, get_db
from ..deps import require_admin, require_user
from ..feedback import get_model, is_configured
from ..feedback import service as _ai
from ..models.mes import FeedbackSubmission
from ..services import notifications as _notify

logger = logging.getLogger("icb.feedback")

router = APIRouter(prefix="/api/feedback", tags=["feedback"])
admin_router = APIRouter(prefix="/api/admin/feedback", tags=["feedback-admin"])

# ── Limits ─────────────────────────────────────────────────────────────────────
_RATE_LIMIT_PER_HOUR = 30            # per user — caps cost (each submit calls Haiku)
_MAX_TEXT = 4000
_MAX_SHOT_BYTES = 5 * 1024 * 1024    # 5 MB
_SHOT_EXT = {".png", ".jpg", ".jpeg", ".webp"}
_STATUSES = ("submitted", "triaged", "in_progress", "resolved", "closed")

_rate_buckets: dict[int, deque] = {}


def _check_rate(user_id: int) -> tuple[bool, int]:
    """Sliding 1-hour window (mirrors app/routers/help.py)."""
    now = time.time()
    bucket = _rate_buckets.setdefault(user_id, deque())
    while bucket and (now - bucket[0]) > 3600.0:
        bucket.popleft()
    if len(bucket) >= _RATE_LIMIT_PER_HOUR:
        return False, int(3600.0 - (now - bucket[0])) + 1
    bucket.append(now)
    return True, 0


# ── Helpers ──────────────────────────────────────────────────────────────────
def _screenshot_dir() -> Path:
    base = (settings.FEEDBACK_SCREENSHOT_DIR or "").strip() or str(Path(settings.FILE_STORE) / "feedback")
    d = Path(base)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _summary_dict(r: FeedbackSubmission) -> dict:
    return {
        "id": r.id,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "submitter_name": r.submitter_name or "",
        "page_url": r.page_url or "",
        "issue_type": r.issue_type,
        "severity": r.severity,
        "summary": r.ai_summary or (r.user_text or "")[:80],
        "status": r.status or "submitted",
        "assigned_to": r.assigned_to or "",
        "has_screenshot": bool(r.screenshot_path),
    }


def _detail_dict(r: FeedbackSubmission) -> dict:
    d = _summary_dict(r)
    d.update({
        "user_text": r.user_text or "",
        "probable_cause": r.probable_cause or "",
        "clarifying_questions": r.clarifying_questions or [],
        "user_answers": r.user_answers,
        "ai_model": r.ai_model,
        "resolution_notes": r.resolution_notes or "",
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        "screenshot_url": f"/api/admin/feedback/{r.id}/screenshot" if r.screenshot_path else None,
        "status_history": r.status_history or [],
    })
    return d


def _append_history(row: FeedbackSubmission, by: str, to_status: str,
                    from_status: str | None = None, note: str | None = None) -> None:
    """Append an append-only audit entry to status_history. Reassigns the list (not
    in-place mutate) so SQLAlchemy detects the JSONB change."""
    entry = {
        "at": datetime.now(timezone.utc).isoformat(),
        "by": by or "system",
        "from": from_status,
        "to": to_status,
        "note": (note or "").strip()[:200] or None,
    }
    row.status_history = (row.status_history or []) + [entry]


def _notify_answers(row: FeedbackSubmission) -> None:
    """Best-effort follow-up email when the submitter answers the AI's clarifying
    questions — closes the loop so the BA sees the clarifications. Never raises."""
    try:
        answers = row.user_answers or []
        lines = [f"Q: {qa.get('q', '')}\nA: {qa.get('a', '')}"
                 for qa in answers if isinstance(qa, dict)] if isinstance(answers, list) else []
        body = (f"The submitter answered the clarifying questions on MES feedback #{row.id}.\n\n"
                + ("\n\n".join(lines) if lines else str(answers)))
        _notify.send_email(f"[MES feedback #{row.id}] submitter answered clarifying questions", body)
    except Exception:  # noqa: BLE001
        logger.warning("feedback answer-notify failed", exc_info=True)


async def _save_screenshot(screenshot: UploadFile) -> str | None:
    """Stream the upload to the screenshot dir under a uuid name. Returns the
    absolute path, or None if absent/rejected. Best-effort — a bad screenshot
    must not sink the whole report."""
    if screenshot is None or not screenshot.filename:
        return None
    suffix = Path(screenshot.filename).suffix.lower()
    if suffix not in _SHOT_EXT:
        logger.info("feedback screenshot rejected (ext=%s)", suffix)
        return None
    dest = _screenshot_dir() / f"{uuid.uuid4().hex}{suffix}"
    total = 0
    try:
        with dest.open("wb") as fh:
            while True:
                chunk = await screenshot.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_SHOT_BYTES:
                    fh.close()
                    dest.unlink(missing_ok=True)
                    logger.info("feedback screenshot too large — dropped")
                    return None
                fh.write(chunk)
    except Exception as e:  # noqa: BLE001
        logger.warning("feedback screenshot save failed: %s", str(e)[:200])
        return None
    finally:
        await screenshot.close()
    return str(dest)


def _notify_ticket(r: FeedbackSubmission, request: Request) -> None:
    """Best-effort email + WhatsApp. Never raises."""
    try:
        base = str(request.base_url).rstrip("/")
        link = f"{base}/mes-app/admin/feedback/{r.id}"
        sev = (r.severity or "unclassified").upper()
        summary = r.ai_summary or (r.user_text or "")[:80]
        subject = f"[MES feedback #{r.id}] {sev} · {summary}"
        cq = r.clarifying_questions or []
        body = (
            f"New MES feedback ticket #{r.id}\n"
            f"From:      {r.submitter_name or 'unknown'}\n"
            f"Severity:  {sev}\n"
            f"Type:      {r.issue_type or 'unclassified'}\n"
            f"Page:      {r.page_url or '(unknown)'}\n"
            f"When:      {r.created_at.isoformat() if r.created_at else ''}\n\n"
            f"Report:\n{r.user_text or ''}\n\n"
            f"AI summary:        {summary}\n"
            f"AI probable cause: {r.probable_cause or '(none)'}\n"
            + (f"AI asked the user: {', '.join(cq)}\n" if cq else "")
            + f"\nOpen the ticket: {link}\n"
        )
        _notify.send_email(subject, body)
        _notify.send_whatsapp(
            f"\U0001F514 MES Feedback #{r.id}\n{sev} · {r.issue_type or 'unclassified'}\n"
            f"{summary}\nPage: {r.page_url or '(unknown)'}\n→ {link}"
        )
    except Exception:  # noqa: BLE001
        logger.warning("feedback notify failed", exc_info=True)


# ── Public endpoints ─────────────────────────────────────────────────────────
@router.get("/health")
async def feedback_health(user: User = Depends(require_user)):
    return {"configured": is_configured(), "model": get_model() if is_configured() else None,
            "rate_limit_per_hour": _RATE_LIMIT_PER_HOUR}


@router.post("")
async def submit_feedback(
    request: Request,
    user_text: str = Form(...),
    page_url: str = Form(""),
    screenshot: UploadFile = File(None),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Store a report, classify it with Claude-Haiku, notify the BA, return the ticket."""
    text = (user_text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="A description is required.")
    if len(text) > _MAX_TEXT:
        text = text[:_MAX_TEXT]

    allowed, retry = _check_rate(user.id)
    if not allowed:
        raise HTTPException(status_code=429,
                            detail=f"Too many reports — try again in ~{retry // 60 + 1} min.")

    shot_path = await _save_screenshot(screenshot)

    row = FeedbackSubmission(
        user_id=user.id,
        submitter_name=user.username,
        page_url=(page_url or "").strip()[:500] or None,
        user_text=text,
        screenshot_path=shot_path,
        status="submitted",
    )

    # Classify (graceful: None when unconfigured/failed → ticket still stored).
    classification = await _ai.classify(text, page_url)
    if classification:
        row.issue_type = classification.get("issue_type")
        row.severity = classification.get("severity")
        row.ai_summary = (classification.get("summary") or "")[:255] or None
        row.probable_cause = classification.get("probable_cause") or None
        row.clarifying_questions = classification.get("clarifying_questions") or None
        row.ai_model = classification.get("_model")
        row.ai_classification = {k: v for k, v in classification.items() if not k.startswith("_")}

    _append_history(row, user.username, "submitted", note="report submitted")
    db.add(row)
    db.commit()
    db.refresh(row)

    _notify_ticket(row, request)

    return {
        "ticket_id": row.id,
        "status": row.status,
        "issue_type": row.issue_type,
        "severity": row.severity,
        "summary": row.ai_summary,
        "clarifying_questions": row.clarifying_questions or [],
        "classified": bool(classification),
    }


@router.post("/{ticket_id}/answer")
async def answer_feedback(
    ticket_id: int,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Record the submitter's answers to the AI's clarifying questions and move the
    ticket to 'triaged'. (Week-1 scaffold; the conversational polish is Week 2.)"""
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Body must be JSON.")
    answers = body.get("answers")
    if answers is None:
        raise HTTPException(status_code=400, detail="Missing 'answers'.")

    row = db.query(FeedbackSubmission).filter_by(id=ticket_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    # Only the original submitter (or an admin) may answer.
    if row.user_id and row.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Not your ticket.")

    old_status = row.status
    row.user_answers = answers
    if row.status == "submitted":
        row.status = "triaged"
    _append_history(row, user.username, row.status, from_status=old_status,
                    note="submitter answered clarifying questions")
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    _notify_answers(row)
    return {"ticket_id": row.id, "status": row.status}


# ── Admin (inbox) endpoints ──────────────────────────────────────────────────
@admin_router.get("")
async def list_feedback(
    status: str | None = None,
    limit: int = 100,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = db.query(FeedbackSubmission)
    if status and status in _STATUSES:
        q = q.filter(FeedbackSubmission.status == status)
    q = q.order_by(FeedbackSubmission.created_at.desc())
    if limit and limit > 0:
        q = q.limit(min(limit, 500))
    return [_summary_dict(r) for r in q.all()]


@admin_router.get("/{ticket_id}")
async def get_feedback(ticket_id: int, _admin: User = Depends(require_admin),
                       db: Session = Depends(get_db)):
    row = db.query(FeedbackSubmission).filter_by(id=ticket_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    return _detail_dict(row)


@admin_router.patch("/{ticket_id}")
async def update_feedback(ticket_id: int, request: Request,
                          _admin: User = Depends(require_admin),
                          db: Session = Depends(get_db)):
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Body must be JSON.")
    row = db.query(FeedbackSubmission).filter_by(id=ticket_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    old_status = row.status
    changes: list[str] = []
    if "status" in body:
        new = str(body["status"])
        if new not in _STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status (allowed: {', '.join(_STATUSES)}).")
        row.status = new
    if "assigned_to" in body:
        new_assignee = (str(body["assigned_to"]).strip() or None)
        if new_assignee != row.assigned_to:
            changes.append(f"assigned to {new_assignee}" if new_assignee else "unassigned")
            row.assigned_to = new_assignee
    if "resolution_notes" in body:
        rn = (str(body["resolution_notes"]).strip() or None)
        if rn != row.resolution_notes:
            changes.append("resolution notes updated")
            row.resolution_notes = rn
    if row.status != old_status or changes:
        _append_history(row, _admin.username, row.status, from_status=old_status,
                        note="; ".join(changes) or None)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return _detail_dict(row)


@admin_router.get("/{ticket_id}/screenshot")
async def get_feedback_screenshot(ticket_id: int, _admin: User = Depends(require_admin),
                                  db: Session = Depends(get_db)):
    row = db.query(FeedbackSubmission).filter_by(id=ticket_id).first()
    if not row or not row.screenshot_path:
        raise HTTPException(status_code=404, detail="No screenshot for this ticket.")
    # We stored this path ourselves; confirm it still lives under the screenshot dir.
    p = Path(row.screenshot_path)
    try:
        p.resolve().relative_to(_screenshot_dir().resolve())
    except (ValueError, OSError):
        raise HTTPException(status_code=404, detail="Screenshot unavailable.")
    if not p.is_file():
        raise HTTPException(status_code=404, detail="Screenshot file missing.")
    return FileResponse(str(p))
