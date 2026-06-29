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
    role_users,
)

import pytest  # noqa: E402


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Stash each test-phase report on the item so the ``browser_context`` fixture can tell whether
    the test failed — the Playwright trace is retained (and CI-uploaded) only on failure (WO v4.36e
    §3.1). The private ``_journey_rep_*`` attr name avoids colliding with other plugins' ``rep_*``."""
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"_journey_rep_{rep.when}", rep)
