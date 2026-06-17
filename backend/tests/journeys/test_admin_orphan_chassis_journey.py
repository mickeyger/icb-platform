"""WO v4.36a §3.8 — admin Find-Orphan journey.

Locks: the WIDE orphan scope catches a received-status orphan (the MICKEYTEST class the narrow Inv3 scope
misses); retrofit-link atomically sets the job FK; soft-delete a junk orphan succeeds; refuse-if-live-FK
blocks deleting a linked chassis; and the §3.5e edit add/update ETA persists onto the job. icb_test (CI);
P436A-marked.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page

from _common import admin_session
from _v436a import (api_delete, api_patch, api_post, chassis_row, job_chassis_eta, job_chassis_id,
                    make_linked_chassis, make_orphan_chassis, make_unlinked_job, purge)


@pytest.fixture(autouse=True)
def _clean():
    purge()
    yield
    purge()


def _orphan_ids(page, base):
    return [r["id"] for r in page.request.get(f"{base}/api/admin/chassis/orphans").json()]


def test_wide_scope_catches_received_orphan(page: Page, live_server: str) -> None:
    admin_session(page)
    base = live_server
    o = make_orphan_chassis(status="received")          # 'received' + no job/card — the MICKEYTEST class
    assert o["chassis_id"] in _orphan_ids(page, base), "wide scope must catch a received-status orphan"


def test_retrofit_link_atomic(page: Page, live_server: str) -> None:
    admin_session(page)
    base = live_server
    o = make_orphan_chassis()
    j = make_unlinked_job()
    r = api_post(page, base, f"/api/admin/chassis/{o['chassis_id']}/retrofit-link",
                 {"production_job_id": j["job_id"]})
    assert r.status == 200, r.text()[:200]
    assert job_chassis_id(j["job_id"]) == o["chassis_id"], "retrofit-link must atomically set the job FK"
    assert o["chassis_id"] not in _orphan_ids(page, base), "a linked chassis is no longer an orphan"


def test_softdelete_junk_then_refuse_live_fk(page: Page, live_server: str) -> None:
    admin_session(page)
    base = live_server
    o = make_orphan_chassis()
    r = api_delete(page, base, f"/api/admin/chassis/{o['chassis_id']}?reason=v4.36a-journey")
    assert r.status == 200, r.text()[:200]
    assert chassis_row(o["chassis_id"])["deleted_at"] is not None, "junk orphan should soft-delete"
    linked = make_linked_chassis()
    r2 = api_delete(page, base, f"/api/admin/chassis/{linked['chassis_id']}")
    assert r2.status == 409, f"soft-delete of a linked chassis must 409, got {r2.status}: {r2.text()[:200]}"
    assert chassis_row(linked["chassis_id"])["deleted_at"] is None, "the refused delete must not mutate"


def test_edit_add_update_eta(page: Page, live_server: str) -> None:
    """§3.5e edit assertion — set, then update, the Delivery ETA on a linked chassis (persists on the job)."""
    admin_session(page)
    base = live_server
    c = make_linked_chassis()
    assert api_patch(page, base, f"/api/chassis-records/{c['chassis_id']}", {"chassis_eta": "2026-09-01"}).status == 200
    assert job_chassis_eta(c["job_id"]) == "2026-09-01", "edit must ADD the ETA onto the job"
    assert api_patch(page, base, f"/api/chassis-records/{c['chassis_id']}", {"chassis_eta": "2026-09-15"}).status == 200
    assert job_chassis_eta(c["job_id"]) == "2026-09-15", "edit must UPDATE the ETA"
