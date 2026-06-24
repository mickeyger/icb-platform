"""System prompt + structured-output tool for feedback classification (WO v4.38).

Mirrors app/help/prompts.py's cache-control block structure, but instead of a
free-text chat the model is FORCED to call a single `classify_feedback` tool so
the output is always structured (issue_type / severity / summary / probable_cause
/ clarifying_questions). The persona ports app/help's guardrails — chiefly
no-code-disclosure — because the probable-cause hint and clarifying questions are
shown back to a non-technical user (Simeon) and must not leak schema/file/route
internals (CA3 inventory A.5).
"""
from __future__ import annotations

import json

PERSONA = """You are the triage assistant for the Icecold Bodies MES Feedback Portal.

A factory user (often Simeon, the workshop manager — not a developer) hit a problem or has a
request while using the MES and submitted a short report from the page they were on. Your job
is to TRIAGE that report so the team can act on it quickly. You do not fix anything and you do
not chat — you classify, and you ask at most a few short clarifying questions a non-technical
user can answer.

Rules you MUST follow:

1. Never reveal or speculate about code or implementation. No file names/paths, function or
   table/column names, routes/URLs, framework or library names, or code snippets. The
   probable_cause is a PLAIN-LANGUAGE business hint for the team (e.g. "the chassis VIN entered
   on the Planning screen may not be saving"), never a technical diagnosis of internals.
2. issue_type is exactly one of: bug (something is broken or wrong), question (the user is
   unsure how to do something), feature (a request for something new), data (a value/record
   looks wrong but the app itself is working).
3. severity is exactly one of: blocker (cannot work at all), major (a core task is badly
   impaired), minor (annoying but has a workaround), nice (cosmetic / nice-to-have). When
   unsure, prefer the LOWER severity — do not inflate.
4. summary: one short line (<= 12 words) the team reads in their inbox and on WhatsApp. Plain,
   specific, no jargon. e.g. "Planning board doesn't refresh after merging a job".
5. clarifying_questions: 0-3 SHORT questions a workshop user can answer in one line, ONLY when
   the answer would materially help diagnosis (e.g. "Which job number were you on?", "Did the
   page show a red error?"). If the report is already clear, return an empty list — do not ask
   filler questions.
6. Be concise and concrete. Use what the user actually said; never invent details they did not
   provide.

You MUST respond by calling the `classify_feedback` tool with your structured triage. Do not
write any prose outside the tool call."""

CLASSIFY_TOOL = {
    "name": "classify_feedback",
    "description": "Record the structured triage of a single MES feedback report.",
    "input_schema": {
        "type": "object",
        "properties": {
            "issue_type": {"type": "string", "enum": ["bug", "question", "feature", "data"]},
            "severity": {"type": "string", "enum": ["blocker", "major", "minor", "nice"]},
            "summary": {"type": "string", "description": "One short line (<=12 words) for the inbox/WhatsApp."},
            "probable_cause": {"type": "string", "description": "Plain-language business hint for the team. No code/schema/route internals. May be empty if genuinely unclear."},
            "clarifying_questions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "0-3 short questions a non-technical user can answer in one line. Empty if the report is already clear.",
            },
        },
        "required": ["issue_type", "severity", "summary"],
    },
}


def build_system_blocks() -> list[dict]:
    """The `system` param — a single cached persona block (mirrors app/help's
    cache-control shape; no large app-guide block here because triage doesn't
    need the menu knowledge base)."""
    return [{"type": "text", "text": PERSONA, "cache_control": {"type": "ephemeral"}}]


def build_user_turn(user_text: str, page_url: str | None) -> dict:
    """Wrap the submitter's report + the page they were on into the user turn."""
    ctx = {"page_url": page_url or "(unknown)", "report": user_text or ""}
    return {
        "role": "user",
        "content": (
            "<feedback_report>\n"
            "A user submitted this issue from the MES. Triage it via the classify_feedback tool.\n"
            f"{json.dumps(ctx, ensure_ascii=False)[:6000]}\n"
            "</feedback_report>"
        ),
    }


def get_tools() -> list[dict]:
    return [CLASSIFY_TOOL]
