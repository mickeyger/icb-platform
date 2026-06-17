"""WO v4.36a §3.8 — admin Merge Chassis journey.

Locks: merge re-points the loser's FKs to the winner + soft-deletes the loser (deleted_at +
merged_into_id) + the restore round-trip; the double-bay refusal (§3.8 break-2); self-merge + deleted-side
blocking (before any mutation); and chain-flatten (A→B then B→C ⇒ A→C). icb_test (CI); P436A-marked.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from playwright.sync_api import Page

from _common import admin_session
from _v436a import (api_patch, api_post, chassis_row, job_chassis_id, make_linked_chassis, purge)


@pytest.fixture(autouse=True)
def _clean():
    purge()
    yield
    purge()


def _merge(page, base, loser, winner):
    return api_post(page, base, f"/api/admin/chassis/{loser}/merge", {"winner_id": winner})


def _preview(page, base, loser, winner):
    return page.request.get(f"{base}/api/admin/chassis/{loser}/merge-preview?winner_id={winner}").json()


def test_merge_repoints_softdeletes_then_restore(page: Page, live_server: str) -> None:
    admin_session(page)
    base = live_server
    loser, winner = make_linked_chassis(), make_linked_chassis()
    pv = _preview(page, base, loser["chassis_id"], winner["chassis_id"])
    assert pv["blocking"] is False, f"a clean merge should not be blocking: {pv}"
    r = _merge(page, base, loser["chassis_id"], winner["chassis_id"])
    assert r.status == 200, r.text()[:200]
    assert job_chassis_id(loser["job_id"]) == winner["chassis_id"], "loser's job FK must re-point to the winner"
    lr = chassis_row(loser["chassis_id"])
    assert lr["deleted_at"] is not None and lr["merged_into_id"] == winner["chassis_id"], lr
    rr = api_patch(page, base, f"/api/admin/chassis/{loser['chassis_id']}/restore", {})
    assert rr.status == 200, rr.text()[:200]
    assert chassis_row(loser["chassis_id"])["deleted_at"] is None, "restore must clear deleted_at"


def test_self_merge_and_deleted_winner_block(page: Page, live_server: str) -> None:
    admin_session(page)
    base = live_server
    a = make_linked_chassis()
    assert _merge(page, base, a["chassis_id"], a["chassis_id"]).status == 409, "self-merge must 409"
    b, c = make_linked_chassis(), make_linked_chassis()
    assert _merge(page, base, b["chassis_id"], c["chassis_id"]).status == 200   # b → c ⇒ b is a tombstone
    assert _merge(page, base, a["chassis_id"], b["chassis_id"]).status == 409, "merge into a deleted winner must 409"


def test_double_bay_refusal(page: Page, live_server: str) -> None:
    """§3.8 break-2 lock — two in_assembly chassis on DIFFERENT bays cannot merge (would empty a bay)."""
    admin_session(page)
    base = live_server
    from app.database import SessionLocal
    from app.models.mes import AssemblyBay, ChassisLifecycleEvent
    a = make_linked_chassis(status="in_assembly")
    b = make_linked_chassis(status="in_assembly")
    with SessionLocal() as db:
        bays = db.query(AssemblyBay).order_by(AssemblyBay.id).limit(2).all()
        now = datetime.now(timezone.utc)
        for ch, bay in ((a, bays[0]), (b, bays[1])):
            db.add(ChassisLifecycleEvent(chassis_record_id=ch["chassis_id"], cycle_number=1,
                                         event_type="assembly_assigned", assembly_bay_id=bay.id,
                                         event_date=now.date(), created_by="t"))
        db.commit()
    pv = _preview(page, base, a["chassis_id"], b["chassis_id"])
    assert pv["blocking"] is True and any("assembly bays" in w for w in pv["warnings"]), pv
    assert _merge(page, base, a["chassis_id"], b["chassis_id"]).status == 409, "double-bay merge must 409"
    # nothing mutated — the loser is still live
    assert chassis_row(a["chassis_id"])["deleted_at"] is None


def test_chain_flatten(page: Page, live_server: str) -> None:
    """A→B then B→C ⇒ A.merged_into_id resolves to C (not tombstone B) — keeps restore tractable."""
    admin_session(page)
    base = live_server
    a, b, c = make_linked_chassis(), make_linked_chassis(), make_linked_chassis()
    assert _merge(page, base, a["chassis_id"], b["chassis_id"]).status == 200
    assert _merge(page, base, b["chassis_id"], c["chassis_id"]).status == 200
    assert chassis_row(a["chassis_id"])["merged_into_id"] == c["chassis_id"], "A must re-point to C (chain flatten)"
