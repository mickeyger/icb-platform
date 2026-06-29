"""TEMP — WO v4.36e §3.1 Playwright trace-infra validation.

This journey DELIBERATELY FAILS to prove the Playwright trace uploads as a CI artifact on a journey
failure (the trace-upload hook added in conftest.py + _common.py + ci.yml §3.1). It drives a real
autologin + shell render FIRST so the captured trace contains genuine DOM snapshots + network +
screenshots — exactly what a real CI-only regression (ADR 0011) would need to diagnose.

THROWAWAY BRANCH ONLY (``ztrace-validation``). DELETE the branch + its PR before §3.1 close. This
file must NEVER reach feat/v4.36e-dispatch-zone.
"""
from _common import admin_session


def test_ztrace_deliberate_failure(page, live_server):
    # Real autologin + shell render, so the retained trace captures DOM/network/screenshots (not a blank tab).
    admin_session(page)
    title = page.title()
    # Guaranteed-false assertion -> the test fails -> browser_context retains + saves the trace zip.
    assert title == "ZTRACE_CANARY_TITLE_THAT_CANNOT_EXIST", (
        f"deliberate v4.36e §3.1 trace-validation failure (EXPECTED). Actual title={title!r}. "
        "If you are reading this in CI, the trace-upload infra is being validated."
    )
