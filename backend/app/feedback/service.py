"""Calls Claude-Haiku to classify a feedback submission (WO v4.38).

A single FORCED-tool call (not a chat loop): the model must call classify_feedback,
and we return its structured input. Mirrors app/routers/help.py's defensive posture
— the anthropic import and the API key are checked inside the function so a missing
dep/key never crashes the request; on ANY failure we return None and the caller
stores the submission unclassified (graceful degradation, never raises)."""
from __future__ import annotations

import logging
import os
from typing import Any

from . import get_model
from . import prompts as _prompts

logger = logging.getLogger("icb.feedback")

_MAX_TEXT = 4000


async def classify(user_text: str, page_url: str | None) -> dict[str, Any] | None:
    """Return {issue_type, severity, summary, probable_cause, clarifying_questions,
    _model, _usage} or None if classification is unavailable/failed. Never raises."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None
    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        logger.warning("anthropic SDK not installed — feedback left unclassified")
        return None

    text = (user_text or "")[:_MAX_TEXT]
    model = get_model()
    try:
        client = AsyncAnthropic(api_key=api_key)
        resp = await client.messages.create(
            model=model,
            max_tokens=512,
            system=_prompts.build_system_blocks(),
            tools=_prompts.get_tools(),
            tool_choice={"type": "tool", "name": "classify_feedback"},
            messages=[_prompts.build_user_turn(text, page_url)],
        )
    except Exception as e:  # noqa: BLE001 — never let the model break submission
        logger.warning("feedback classify failed: %s", str(e)[:200])
        return None

    # Pull the forced tool_use block.
    payload: dict | None = None
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "classify_feedback":
            payload = dict(block.input or {})
            break
    if payload is None:
        logger.warning("feedback classify returned no tool_use block")
        return None

    usage = getattr(resp, "usage", None)
    payload["_model"] = model
    payload["_usage"] = {
        "in": getattr(usage, "input_tokens", 0) or 0,
        "out": getattr(usage, "output_tokens", 0) or 0,
    }
    # Normalise / clamp the fields we trust before they reach the DB + the user.
    cq = payload.get("clarifying_questions")
    if not isinstance(cq, list):
        cq = []
    payload["clarifying_questions"] = [str(q)[:300] for q in cq[:3] if str(q).strip()]
    return payload
