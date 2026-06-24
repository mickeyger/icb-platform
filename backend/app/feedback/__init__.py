"""Feedback Portal AI module (WO v4.38).

Mirrors app/help/ conventions for the Claude-Haiku layer, but the use case is
*classification* of in-app issue reports, not a costing Q&A chat. Gated on
ANTHROPIC_API_KEY and degrades gracefully: a submission is always stored and
delivered even when the model is unconfigured or errors (the classification
fields just stay NULL). See docs/audit/v4_38_S3_0_feedback_portal_discovery.md.
"""
import os

DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def get_model() -> str:
    """The classification model. Honours an explicit feedback override, then the
    help feature's override (so one env var can pin both), else Haiku."""
    return (os.environ.get("ANTHROPIC_FEEDBACK_MODEL")
            or os.environ.get("ANTHROPIC_HELP_MODEL")
            or DEFAULT_MODEL)


def is_configured() -> bool:
    """True when the Anthropic key is set. The portal still works when False —
    submissions are stored + delivered, just without AI triage."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))
