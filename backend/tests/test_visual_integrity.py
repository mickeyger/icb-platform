"""WO v4.36b §3.1 — visual_integrity flag-derivation service unit tests.

Pure-logic tests (no DB) pin the band/severity resolver + the spec registry. DB-backed tests seed
throwaway records (created_source_ref / job_number 'ZZVI' prefix, FK-safe teardown) and drive the
derivation deterministically via the service's `now=` injection — no dependence on wall-clock or a
particular seed state. Execution on CI/icb_test per ADR 0011.
"""
from datetime import datetime, timezone

import pytest

from app.services import visual_integrity as vi

UTC = timezone.utc
REF = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)        # the test "now"; seed timestamps precede it
_MARK = "ZZVI"


# ── pure logic (no DB) ─────────────────────────────────────────────────────────
def test_flag_specs_integrity():
    groups = {"Chassis", "Jobs", "Bays", "Sign-offs", "Stale Reviews"}
    domains = {"chassis", "jobs", "bays"}
    sevs = {"sky", "amber", "red"}
    assert len(vi.FLAG_SPECS) == 13                    # the §1 catalog
    for key, s in vi.FLAG_SPECS.items():
        assert key == s.flag
        assert s.domain in domains and s.group in groups
        assert s.bands, f"{key} has no bands"
        gts = [gt for gt, _ in s.bands]
        assert gts == sorted(gts), f"{key} bands not ascending"
        assert all(sev in sevs for _, sev in s.bands)


def test_resolve_picks_highest_exceeded_band():
    spec = vi.FLAG_SPECS["bay_post_attached_stale"]    # bands ((3,'amber'),(5,'red'))
    assert vi._resolve(spec, 2) is None                # below trigger
    assert vi._resolve(spec, 4) == "amber"
    assert vi._resolve(spec, 6) == "red"
    assert vi._resolve(spec, None) is None


def test_resolve_fires_immediately_for_no_age_flag():
    spec = vi.FLAG_SPECS["chassis_no_customer"]        # band ((-1,'red')) → fires at any age >= 0
    assert vi._resolve(spec, 0) == "red"


def test_age_days_handles_date_and_datetime():
    assert vi._age_days(REF, datetime(2026, 1, 5, tzinfo=UTC)) == 5
    assert vi._age_days(REF, REF.date().replace(day=3)) == 7    # a date basis (UTC midnight)
    assert vi._age_days(REF, None) is None


# ── DB-backed ──────────────────────────────────────────────────────────────────
def _purge(db):
    from sqlalchemy import text
    db.execute(text("DELETE FROM icb_mes.production_jobs WHERE job_number LIKE 'ZZVI%'"))
    db.execute(text("DELETE FROM icb_mes.chassis_records WHERE created_source_ref LIKE 'ZZVI%'"))
    db.commit()


@pytest.fixture
def db():
    from app.database import SessionLocal
    with SessionLocal() as s:
        _purge(s)
        try:
            yield s
        finally:
            _purge(s)


def _chassis(db, *, vin=None, customer_name=None, make=None, status="received",
             created_at=datetime(2026, 1, 1, tzinfo=UTC)):
    from app.models.mes import ChassisRecord
    c = ChassisRecord(vin=vin, customer_name=customer_name, make=make, status=status,
                      created_via="manual_chassis_menu", created_source_ref=f"{_MARK}-test",
                      created_at=created_at, created_by="t", updated_by="t")
    db.add(c)
    db.flush()
    return c.id


def _job(db, *, chassis_id=None, status="planning", chassis_eta=None,
         planning_acknowledged_at=None):
    from app.database import Branch
    from app.models.mes import ProductionJob
    branch = db.query(Branch).order_by(Branch.id).first()
    j = ProductionJob(branch_id=branch.id, source="quote", status=status, job_number="ZZVI001",
                      chassis_record_id=chassis_id, chassis_eta=chassis_eta,
                      planning_acknowledged_at=planning_acknowledged_at)
    db.add(j)
    db.flush()
    return j.id


def _flags(hits):
    return {h["flag"] for h in hits}


def _sev(hits, flag):
    return next(h["severity"] for h in hits if h["flag"] == flag)


def test_chassis_no_vin_fires_red(db):
    cid = _chassis(db, vin=None, make="X")
    hits = vi.compute_chassis_flags(db, cid, now=REF)
    assert "chassis_no_vin" in _flags(hits) and _sev(hits, "chassis_no_vin") == "red"


def test_chassis_vin_format_legacy_amber(db):
    cid = _chassis(db, vin="SHORTLEGACYVIN", make="X")     # not 17-char ISO-3779
    hits = vi.compute_chassis_flags(db, cid, now=REF)
    assert _sev(hits, "chassis_vin_format_legacy") == "amber"
    assert "chassis_no_vin" not in _flags(hits)            # has a VIN, just legacy-format


def test_chassis_no_customer_requires_linked_job(db):
    # unlinked chassis with no customer → NOT flagged no-customer (nothing to backfill from)
    lone = _chassis(db, vin="1HGCM82633A004352", make="X", customer_name=None)
    assert "chassis_no_customer" not in _flags(vi.compute_chassis_flags(db, lone, now=REF))
    # linked to a job, customer blank → red
    linked = _chassis(db, vin="1HGCM82633A004353", make="X", customer_name=None)
    _job(db, chassis_id=linked)
    hits = vi.compute_chassis_flags(db, linked, now=REF)
    assert _sev(hits, "chassis_no_customer") == "red"


def test_chassis_no_make_model_amber_on_stub(db):
    cid = _chassis(db, vin="1HGCM82633A004400", make=None, status="expected")
    hits = vi.compute_chassis_flags(db, cid, now=REF)
    assert _sev(hits, "chassis_no_make_model") == "amber"


def test_job_eta_overdue_red(db):
    jid = _job(db, chassis_id=None, status="planning",
               chassis_eta=datetime(2026, 1, 5, tzinfo=UTC))   # before REF, not received
    hits = vi.compute_job_flags(db, jid, now=REF)
    assert _sev(hits, "job_eta_overdue") == "red"


def test_job_eta_missing_amber(db):
    jid = _job(db, chassis_id=None, status="planning", chassis_eta=None,
               planning_acknowledged_at=datetime(2026, 1, 1, tzinfo=UTC))
    hits = vi.compute_job_flags(db, jid, now=REF)
    assert _sev(hits, "job_eta_missing") == "amber"
    assert "job_eta_overdue" not in _flags(hits)


def test_summary_aggregates_seeded_flags(db):
    _chassis(db, vin=None, make="X")                          # chassis_no_vin
    before = vi.compute_planning_board_flags(db, now=REF)
    cid = _chassis(db, vin=None, make=None, status="expected")  # +no_vin +no_make_model
    after = vi.compute_planning_board_flags(db, now=REF)
    assert after["by_flag"].get("chassis_no_vin", 0) >= 2
    assert after["by_flag"].get("chassis_no_make_model", 0) >= 1
    assert after["total"] > before["total"]
    assert after["by_severity"]["red"] >= 2
