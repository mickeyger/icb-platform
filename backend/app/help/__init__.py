"""Help assistant module.

Exposes the curated app guide via `get_app_guide()`. The guide is cached but
re-read whenever the markdown file's mtime changes — so edits to the .md
take effect without needing to restart the server (uvicorn's --reload only
watches .py by default).

APP_GUIDE remains as a module-level constant for back-compat with code that
imports it directly, but new callers should prefer `get_app_guide()`.
"""

import os
from pathlib import Path

_GUIDE_PATH = Path(__file__).parent / "app_guide.md"
_FALLBACK = "(app guide not found — help responses will be generic)"

_cache: dict = {"mtime": 0.0, "text": ""}


def get_app_guide() -> str:
    """Return the current app-guide markdown. Re-reads from disk if the file
    has been modified since the last call."""
    try:
        mtime = _GUIDE_PATH.stat().st_mtime
    except FileNotFoundError:
        return _FALLBACK
    if mtime != _cache["mtime"]:
        try:
            _cache["text"] = _GUIDE_PATH.read_text(encoding="utf-8")
            _cache["mtime"] = mtime
        except OSError:
            return _cache["text"] or _FALLBACK
    return _cache["text"]


# Back-compat shim — eagerly populates the cache so module-level
# `from app.help import APP_GUIDE` keeps working.
APP_GUIDE: str = get_app_guide()

DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def get_model() -> str:
    return os.environ.get("ANTHROPIC_HELP_MODEL", DEFAULT_MODEL)


def is_configured() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))
