"""AI Help assistant router.

Endpoints:
  GET    /api/help/health                  — {"configured": bool}
  POST   /api/help/chat                    — SSE stream
  POST   /api/help/attachment              — upload an Excel workbook to compare
                                             the live costing against
  DELETE /api/help/attachment/{upload_id}  — detach + delete the workbook
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..database import get_db, User, HelpRequestLog
from ..deps import require_user, user_can
from ..help import get_model, is_configured
from ..help import prompts as _prompts
from ..help import tools as _tools
from ..help import reconcile as _reconcile

logger = logging.getLogger("burtcost.help")

router = APIRouter(prefix="/api/help", tags=["help"])

# ── Rate limiting (per-process, in-memory) ────────────────────────────────────
_RATE_LIMIT_PER_HOUR = 30
_rate_buckets: dict[int, deque[float]] = {}


def _check_rate(user_id: int) -> tuple[bool, int]:
    """Returns (allowed, retry_after_seconds). Sliding 1-hour window."""
    now = time.time()
    window = 3600.0
    bucket = _rate_buckets.setdefault(user_id, deque())
    while bucket and (now - bucket[0]) > window:
        bucket.popleft()
    if len(bucket) >= _RATE_LIMIT_PER_HOUR:
        retry_after = int(window - (now - bucket[0])) + 1
        return False, max(retry_after, 1)
    bucket.append(now)
    return True, 0


# ── Health ────────────────────────────────────────────────────────────────────
@router.get("/health")
async def help_health(user: User = Depends(require_user)):
    return {
        "configured": is_configured(),
        "model": get_model() if is_configured() else None,
        "rate_limit_per_hour": _RATE_LIMIT_PER_HOUR,
    }


# ── Chat (SSE stream) ─────────────────────────────────────────────────────────
def _normalise_history(raw: Any) -> list[dict]:
    """Sanitise client-supplied history to the shape Anthropic expects.
    We only trust role + plain string content. Tool-use turns from prior
    server-side rounds are intentionally NOT replayed — the client only sees
    final assistant text, so we feed back only text-based turns here."""
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for m in raw[-12:]:  # belt-and-braces cap before truncate_history runs
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if role not in ("user", "assistant"):
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        out.append({"role": role, "content": content[:4000]})
    return out


_PAGE_CONTEXT_MAX_BYTES = 131_072  # 128 KB — comfortably fits a slimmed liveResult


def _safe_page_context(raw: Any) -> dict | None:
    """Accept only reasonably-sized JSON dicts. Reject anything that smells
    like an attempt to smuggle secrets, but be generous enough to accommodate
    a slimmed liveResult from a large body's calculator output."""
    if not isinstance(raw, dict):
        return None
    try:
        s = json.dumps(raw, default=str)
    except (TypeError, ValueError):
        return None
    if len(s) > _PAGE_CONTEXT_MAX_BYTES:
        logger.warning(
            "page_context rejected: %d bytes exceeds %d cap "
            "(keys=%s, liveResult.items=%s)",
            len(s), _PAGE_CONTEXT_MAX_BYTES, list(raw)[:10],
            len((raw.get("liveResult") or {}).get("items") or []),
        )
        return None
    return raw


def _persist_log(user_id: int, model: str, metrics: dict, page: str | None,
                 finish_reason: str, error_msg: str | None) -> None:
    """Best-effort telemetry insert. Uses its own SessionLocal to avoid
    interfering with the request-scoped session, which may already be closed
    by the time the generator finishes."""
    try:
        from ..database import SessionLocal
        with SessionLocal() as logdb:
            logdb.add(HelpRequestLog(
                user_id=user_id,
                model=model,
                input_tokens=metrics.get("in", 0),
                output_tokens=metrics.get("out", 0),
                cached_tokens=metrics.get("cached", 0),
                cache_write_tokens=metrics.get("cache_write", 0),
                ms_elapsed=metrics.get("ms", 0),
                page=str(page)[:255] if page else None,
                tool_calls=metrics.get("tool_calls", 0),
                tool_names=(",".join(metrics.get("tool_names") or []))[:500] or None,
                finish_reason=str(finish_reason)[:32],
                error=error_msg[:500] if error_msg else None,
            ))
            logdb.commit()
    except Exception:
        logger.warning("Failed to persist HelpRequestLog row", exc_info=True)


async def _stream_chat(
    request: Request,
    user: User,
    db: Session,
    message: str,
    history: list[dict],
    page_context: dict | None,
    reconciliation: dict | None = None,
):
    """Async generator yielding SSE events.

    Tool-use loop: stream from Anthropic; if stop_reason=='tool_use', run the
    tools and continue with their results appended; otherwise finish.

    Telemetry is recorded after the stream closes (or on exception) via
    `_persist_log` — never inside `finally` to avoid yielding into a
    closed generator on client disconnect.
    """
    # Local import so the app still starts if `anthropic` isn't installed
    # in some environment (e.g. CI without the help dep).
    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        yield {"event": "error", "data": json.dumps({"message": "anthropic SDK not installed on the server."})}
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        yield {"event": "error", "data": json.dumps({"message": "ANTHROPIC_API_KEY is not configured on the server."})}
        return

    t0 = time.monotonic()
    client = AsyncAnthropic(api_key=api_key)

    system_blocks = _prompts.build_system_blocks()
    tools = _prompts.get_tools()
    model = get_model()

    history = _prompts.truncate_history(history)
    messages: list[dict] = list(history) + [
        _prompts.build_user_turn(message, page_context, reconciliation)
    ]

    # Debug: confirm propose_actions reaches the model and suggest_actions
    # flag is in page_context. Logged at INFO so it appears in dev console.
    _tool_names = [t.get("name") for t in (tools or [])]
    _sa_flag = (page_context or {}).get("suggest_actions")
    logger.info(
        "help chat: tools=%s suggest_actions=%r page=%s",
        _tool_names, _sa_flag, (page_context or {}).get("page"),
    )

    metrics: dict = {"in": 0, "out": 0, "cached": 0, "cache_write": 0,
                     "tool_calls": 0, "tool_names": [], "ms": 0}
    finish_reason = "error"
    error_msg: str | None = None
    page = (page_context or {}).get("page") if page_context else None

    try:
        MAX_ITERATIONS = 6
        for _ in range(MAX_ITERATIONS):
            if await request.is_disconnected():
                finish_reason = "client_disconnect"
                break

            async with client.messages.stream(
                model=model,
                max_tokens=1024,
                system=system_blocks,
                tools=tools,
                messages=messages,
            ) as stream:
                async for chunk in stream.text_stream:
                    if await request.is_disconnected():
                        finish_reason = "client_disconnect"
                        break
                    if chunk:
                        yield {"event": "token", "data": json.dumps({"text": chunk})}
                if finish_reason == "client_disconnect":
                    break
                final = await stream.get_final_message()

            usage = final.usage
            metrics["in"] += getattr(usage, "input_tokens", 0) or 0
            metrics["out"] += getattr(usage, "output_tokens", 0) or 0
            metrics["cached"] += getattr(usage, "cache_read_input_tokens", 0) or 0
            metrics["cache_write"] += getattr(usage, "cache_creation_input_tokens", 0) or 0

            if final.stop_reason != "tool_use":
                finish_reason = final.stop_reason or "end_turn"
                break

            # Tool-use turn — append the assistant message and run each tool.
            messages.append({"role": "assistant", "content": final.content})
            tool_results: list[dict] = []
            terminate_for_actions = False
            for block in final.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                metrics["tool_calls"] += 1
                metrics["tool_names"].append(block.name)
                yield {"event": "tool", "data": json.dumps({"name": block.name})}

                # propose_actions is a side-channel tool: validated server-side,
                # emitted to the browser as an `actions` SSE event, NOT fed back
                # to the model. The assistant's text reply (already streamed)
                # stands as the final answer; the buttons appear under it.
                if block.name == "propose_actions":
                    validated = _tools.validate_actions(dict(block.input or {}))
                    if validated.get("ok"):
                        yield {"event": "actions", "data": json.dumps({
                            "intro":   validated.get("intro"),
                            "actions": validated["actions"],
                        })}
                    else:
                        logger.info("propose_actions rejected: %s", validated)
                    terminate_for_actions = True
                    continue

                result = _tools.dispatch(block.name, dict(block.input or {}), user, db)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, default=str)[:8000],
                })

            if terminate_for_actions:
                # End the loop — no further model turn needed. (If the model
                # ALSO called data tools in the same turn we drop their results
                # silently; it didn't need them to render the buttons.)
                finish_reason = "actions"
                break
            messages.append({"role": "user", "content": tool_results})
        else:
            finish_reason = "max_iterations"
            yield {"event": "error", "data": json.dumps({"message": "Help loop exceeded max iterations."})}

    except Exception as e:
        error_msg = str(e)[:400]
        logger.exception("help chat stream failed")
        try:
            yield {"event": "error", "data": json.dumps({"message": error_msg})}
        except Exception:
            pass

    metrics["ms"] = int((time.monotonic() - t0) * 1000)

    # Done event — may not be delivered on client_disconnect; that's fine.
    if finish_reason != "client_disconnect":
        try:
            yield {"event": "done", "data": json.dumps({
                "finish_reason": finish_reason,
                "input_tokens": metrics["in"],
                "output_tokens": metrics["out"],
                "cached_tokens": metrics["cached"],
                "ms_elapsed": metrics["ms"],
            })}
        except Exception:
            pass

    # Non-yielding cleanup — safe even if the generator is being closed.
    _persist_log(user.id, model, metrics, page, finish_reason, error_msg)


# ── Excel-attachment helpers ──────────────────────────────────────────────────
# Workbooks live under a temp folder with a 2-hour TTL — same lifecycle as the
# importer's upload area. The user's uploads are NOT persisted to the DB; once
# the TTL elapses the file is gone.
_ATTACH_DIR = Path(tempfile.gettempdir()) / "burtcost_helpchat"
_ATTACH_TTL_SECONDS = 2 * 3600
_ATTACH_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
_ATTACH_ALLOWED_EXT = {".xlsx", ".xls"}


def _ensure_attach_dir() -> Path:
    _ATTACH_DIR.mkdir(parents=True, exist_ok=True)
    return _ATTACH_DIR


def _purge_old_attachments() -> None:
    """Best-effort GC. Runs on every upload — no separate cron needed."""
    try:
        if not _ATTACH_DIR.exists():
            return
        cutoff = time.time() - _ATTACH_TTL_SECONDS
        for child in _ATTACH_DIR.iterdir():
            try:
                if child.stat().st_mtime < cutoff:
                    shutil.rmtree(child, ignore_errors=True)
            except OSError:
                pass
    except Exception:  # noqa: BLE001
        logger.warning("attachment purge failed", exc_info=True)


def _attachment_path(upload_id: str) -> Path | None:
    """Resolve an upload_id to its workbook path, or None if missing/expired."""
    # Reject anything that isn't a hex uuid to keep path traversal at bay.
    if not upload_id or not all(c in "0123456789abcdef" for c in upload_id.lower()):
        return None
    folder = _ATTACH_DIR / upload_id
    if not folder.is_dir():
        return None
    # The first .xlsx/.xls file in the folder is the workbook.
    for child in folder.iterdir():
        if child.suffix.lower() in _ATTACH_ALLOWED_EXT:
            return child
    return None


def _safe_attachment_ref(raw: Any) -> dict | None:
    """Validate the optional `attachment` field on a chat request."""
    if not isinstance(raw, dict):
        return None
    upload_id = (raw.get("upload_id") or "").strip().lower()
    sheet = (raw.get("sheet") or "").strip()
    if not upload_id or not sheet:
        return None
    return {"upload_id": upload_id, "sheet": sheet}


@router.post("/attachment")
async def help_attachment_upload(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Accept an Excel workbook for reconciliation. Returns an upload_id +
    sheet list so the frontend can show the chip with a sheet dropdown.

    Gated on `bom.view_prices` because a reconciliation that hides prices is
    meaningless. Admins bypass this check automatically (see deps.user_can)."""
    if not user_can(user, "bom.view_prices", db):
        raise HTTPException(
            status_code=403,
            detail="You need the 'bom.view_prices' permission to compare costings to Excel.",
        )

    # Quick extension whitelist (no MIME sniffing — clients lie about that).
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ATTACH_ALLOWED_EXT:
        raise HTTPException(status_code=400, detail="Only .xlsx or .xls files are supported.")

    _purge_old_attachments()
    upload_id = uuid.uuid4().hex
    folder = _ensure_attach_dir() / upload_id
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"workbook{suffix}"

    # Stream to disk in 1 MB chunks, enforce the size cap before exhausting RAM.
    total = 0
    try:
        with dest.open("wb") as fh:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > _ATTACH_MAX_BYTES:
                    fh.close()
                    shutil.rmtree(folder, ignore_errors=True)
                    raise HTTPException(
                        status_code=400,
                        detail=f"File too large (max {_ATTACH_MAX_BYTES // (1024 * 1024)} MB).",
                    )
                fh.write(chunk)
    finally:
        await file.close()

    # Read sheet list and auto-pick.
    try:
        sheets = _reconcile.list_sheets(str(dest))
    except Exception as e:  # noqa: BLE001
        shutil.rmtree(folder, ignore_errors=True)
        logger.warning("attachment sheet listing failed for %s: %s", file.filename, e)
        raise HTTPException(status_code=400, detail=f"Couldn't read workbook: {str(e)[:200]}")

    # Best-effort: read the body name from the request's hint header so we can
    # pre-pick the right sheet. Frontend sends it as a query param to avoid
    # multipart-body wrangling.
    body_hint = request.query_params.get("body") or ""
    picked = _reconcile.pick_sheet_for_body(sheets, body_hint or None)

    return {
        "upload_id":    upload_id,
        "filename":     file.filename,
        "size_bytes":   total,
        "sheets":       sheets,
        "picked_sheet": picked,
    }


@router.delete("/attachment/{upload_id}")
async def help_attachment_delete(
    upload_id: str,
    user: User = Depends(require_user),
):
    """Explicit detach. Best-effort — returns 200 even if the folder is gone
    so the frontend can call this fire-and-forget when the user clicks ✕."""
    if not upload_id or not all(c in "0123456789abcdef" for c in upload_id.lower()):
        raise HTTPException(status_code=400, detail="Bad upload_id.")
    folder = _ATTACH_DIR / upload_id
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    return {"ok": True}


@router.post("/chat")
async def help_chat(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    if not is_configured():
        raise HTTPException(status_code=503, detail="Help assistant is not configured on this server.")

    allowed, retry_after = _check_rate(user.id)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit reached ({_RATE_LIMIT_PER_HOUR}/hour). Try again in ~{retry_after // 60 + 1} min.",
        )

    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Body must be JSON.")

    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Missing 'message'.")
    if len(message) > 4000:
        raise HTTPException(status_code=400, detail="Message too long (4000 char max).")

    history = _normalise_history(body.get("history"))
    page_context = _safe_page_context(body.get("page_context"))

    # Optional Excel reconciliation block — produced server-side from the
    # uploaded workbook + the live calculator result the frontend stashes in
    # page_context.liveResult.
    reconciliation: dict | None = None
    attachment = _safe_attachment_ref(body.get("attachment"))
    if attachment:
        if not user_can(user, "bom.view_prices", db):
            # Soft-fail rather than blocking the whole chat turn — the AI
            # gets a permission_denied marker and tells the user.
            reconciliation = {"error": "permission_denied", "permission": "bom.view_prices"}
        else:
            wb_path = _attachment_path(attachment["upload_id"])
            if wb_path is None:
                reconciliation = {"error": "attachment_expired",
                                  "message": "The attached workbook has expired or been removed — please re-attach."}
            else:
                live_result = (page_context or {}).get("liveResult")
                live_body   = (page_context or {}).get("body")
                logger.info(
                    "help reconcile: sheet=%s live_items=%s live_grand=%s body=%s",
                    attachment["sheet"],
                    len((live_result or {}).get("items") or []),
                    (live_result or {}).get("grand_total"),
                    live_body,
                )
                reconciliation = _reconcile.build_reconciliation(
                    workbook_path=str(wb_path),
                    sheet_name=attachment["sheet"],
                    live_result=live_result,
                    live_body_name=live_body,
                )
                # The reconciliation report supersedes the raw liveResult for
                # the AI — strip it from page_context so we don't pay tokens
                # twice (and to keep the prompt under the 60 KB cap in
                # prompts.build_user_turn). Keep the lightweight scalars.
                if page_context and "liveResult" in page_context:
                    page_context = {k: v for k, v in page_context.items() if k != "liveResult"}

    # NOTE: We collect the full SSE payload in memory and return it as a single
    # Response instead of streaming with EventSourceResponse. The app's stack of
    # BaseHTTPMiddleware classes (perf, csrf, security-headers, theme) breaks
    # mid-stream and raises "Unexpected message received: http.request" on prod.
    # The browser's EventSource parser handles a fully-buffered response the
    # same way — the user just sees the reply land all at once after a few
    # seconds rather than token-by-token. Functionally identical.
    frames: list[str] = []
    async for ev in _stream_chat(request, user, db, message, history, page_context, reconciliation):
        evt = ev.get("event", "message")
        data = ev.get("data", "")
        # SSE frame: each non-empty data line is prefixed with "data: " and
        # the whole frame ends with a blank line.
        data_lines = "\n".join(f"data: {ln}" for ln in str(data).split("\n"))
        frames.append(f"event: {evt}\n{data_lines}\n\n")
    body = "".join(frames).encode("utf-8")
    return Response(
        content=body,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─── Audit panel (Excel side-by-side comparison view) ─────────────────────────
@router.post("/audit")
async def help_audit(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Run the same reconciliation engine the chat uses, but return the report
    directly as JSON. Powers the Excel Audit side panel on the calculator
    pages — section list, totals, deltas, line-level diffs.

    Body: { upload_id, sheet, live_result?, live_body? }
        live_result is optional; if omitted, the report omits per-line live
        data but still returns Excel-side sections + totals.
    """
    if not user_can(user, "bom.view_prices", db):
        raise HTTPException(
            status_code=403,
            detail="The bom.view_prices permission is required to compare costings.",
        )

    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Body must be JSON.")

    attachment = _safe_attachment_ref(body.get("attachment") or body)
    if not attachment:
        raise HTTPException(status_code=400, detail="upload_id and sheet are required.")

    wb_path = _attachment_path(attachment["upload_id"])
    if wb_path is None:
        raise HTTPException(status_code=410, detail="Attached workbook has expired — please re-attach.")

    live_result = body.get("live_result")
    if isinstance(live_result, dict):
        # Defensive: cap the size so a malicious / runaway client can't OOM
        # the worker. The page_context cap is 128 KB; mirror it.
        try:
            if len(json.dumps(live_result)) > 196_000:
                live_result = None
                logger.warning("audit: live_result too large, ignoring")
        except (TypeError, ValueError):
            live_result = None
    else:
        live_result = None
    live_body = (body.get("live_body") or "")[:200] if isinstance(body.get("live_body"), str) else None

    try:
        report = _reconcile.build_reconciliation(
            workbook_path=str(wb_path),
            sheet_name=attachment["sheet"],
            live_result=live_result,
            live_body_name=live_body,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("audit: build_reconciliation failed")
        raise HTTPException(status_code=500, detail=f"Audit failed: {str(e)[:200]}")

    return report
