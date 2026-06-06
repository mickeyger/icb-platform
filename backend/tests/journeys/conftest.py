"""Pytest discovers fixtures by scanning conftest module namespaces. The journey
fixtures live in ``_common.py`` (the reusable shell, per WO v4.26.1 §0.8); this
conftest puts the journeys dir on ``sys.path`` (mirroring tests/conftest.py's
style) and re-exports them so ``pytest tests/journeys/...`` finds them without
the test modules importing fixtures explicitly.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402,F401  (re-exported for fixture discovery)
    browser,
    browser_context,
    live_server,
    page,
    playwright_instance,
)
