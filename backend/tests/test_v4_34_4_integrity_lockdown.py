"""WO v4.34.4 §3.5 — integrity-lockdown journeys.

Five tests, one per lockdown concern. They exercise the GUARDS and INVARIANTS directly at the service
layer rather than through the browser, because that is where the behaviour lives — the destructive
vector is a script guard, the invariants are service functions, and there is no role-gated UI surface
to drive (the one place an invariant surfaces through the API — Invariant 1 via Pre-Job sign-off — is
already covered end-to-end, as admin, by tests/test_prejob_signoff_api.py). Role mapping under Testing
Strategy v1.1: tests 1 & 5 are operator/CI concerns (no app role); tests 2–4 are pipeline invariants
whose affected roles are Sales + Planner (their sign-offs drive the state these guards protect).

Marker rows are prefixed P4344 with a self-healing purge; any real calculation a test borrows has its
status captured and restored. The whole module only runs under the §3.1 session guard — i.e. against an
isolated *_test database, never the shared dev DB.
"""
import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.config import settings
from app.database import Branch, CalculationRecord, SessionLocal
from app.db_guard import is_test_db
from app.models.mes import ChassisRecord, PrejobCard, PrejobTemplate, ProductionJob
from app.services import integrity
from scripts import _environment_guard as eg

DEV_URL = "postgresql+psycopg://icb_app:x@localhost:5432/icb"        # the shared dev DB — must be refused
TEST_URL = "postgresql+psycopg://icb_app:x@localhost:5432/icb_test"  # an isolated test DB — allowed


def _purge(db) -> None:
    db.execute(text("DELETE FROM icb_mes.prejob_cards WHERE body_description LIKE 'P4344%'"))
    db.execute(text("DELETE FROM icb_mes.production_jobs WHERE job_number LIKE 'P4344%'"))
    db.execute(text("DELETE FROM icb_mes.prejob_templates WHERE name LIKE 'P4344%'"))
    db.execute(text("DELETE FROM icb_mes.chassis_records WHERE make LIKE 'P4344%'"))  # chassis last (FK RESTRICT)
    db.commit()


@pytest.fixture
def db():
    s = SessionLocal()
    _purge(s)
    try:
        yield s
    finally:
        _purge(s)
        s.close()


def _fresh_calc(db) -> CalculationRecord:
    """A real accepted New-Build costing with no production_job and no Pre-Job Card — free to borrow."""
    taken = {j.calculation_record_id for j in db.query(ProductionJob)
             .filter(ProductionJob.calculation_record_id.isnot(None)).all()}
    carded = {c.calculation_id for c in db.query(PrejobCard).all()}
    calc = (db.query(CalculationRecord)
            .filter(~CalculationRecord.id.in_((taken | carded) or {0}),
                    CalculationRecord.status == "accepted",
                    CalculationRecord.quote_number.isnot(None),
                    CalculationRecord.is_repair.isnot(True))
            .order_by(CalculationRecord.id).first())
    if calc is None:
        pytest.skip("no job-free, card-free accepted New-Build calculation on this DB")
    return calc


def _branch_id(db) -> int:
    return db.query(Branch).order_by(Branch.id).first().id


# ── 1. destructive-vector isolation ─────────────────────────────────────────────
def test_destructive_vector_isolation(monkeypatch):
    """The seed re-seed TRUNCATE — the exact vector that contaminated the dev DB — is gated to a
    *_test DB, and the suite itself runs isolated. We SIMULATE the dangerous condition (a dev-DB URL)
    and prove the truncate refuses before touching anything; db=None is never dereferenced."""
    # The suite is genuinely isolated (this is the §3.1 guarantee, live):
    assert is_test_db(settings.DATABASE_URL), "the test suite must run against a *_test database"

    import scripts.seed_from_mockup as seed
    monkeypatch.setattr(eg, "_url", lambda: DEV_URL)            # pretend DATABASE_URL points at shared dev
    with pytest.raises(RuntimeError) as exc:
        seed._truncate_mes(None)                               # guard fires first; None never used
    assert "REFUSED" in str(exc.value) and "icb" in str(exc.value)

    monkeypatch.setattr(eg, "_url", lambda: TEST_URL)          # a *_test DB clears the guard
    eg.require_test_db("seed truncate")                        # no raise


# ── 2. calc.status revert when its backing is removed (Invariant 2) ──────────────
def test_calc_status_rollback_on_card_delete(db):
    """A calc may sit at pre_job_confirmed only while a card/job backs it. Remove the backing (the
    deferred card-delete, simulated) and the reconciler walks the stray BACK to 'accepted' — but only
    with allow_revert=True; the forward-only default never downgrades."""
    calc = _fresh_calc(db)
    calc_id, calc_orig = calc.id, calc.status
    try:
        tpl = PrejobTemplate(name="P4344 TPL", body_type="chiller", product_line="standard",
                             header_format="P4344 header", is_active=True,
                             sections=[{"name": "S", "items": [{"text": "x"}]}], created_by="t")
        db.add(tpl); db.flush()
        card = PrejobCard(calculation_id=calc_id, template_id=tpl.id, body_description="P4344 header",
                          status="pre_job_confirmed", sales_rep_signoff_at=None)
        job = ProductionJob(calculation_record_id=calc_id, branch_id=_branch_id(db), source="quote",
                            status="pre_job_confirmed", job_number="P4344J2")
        db.add_all([card, job]); calc.status = "pre_job_confirmed"; db.commit()

        # backing present → derive agrees, nothing to revert
        assert integrity.derive_calc_status(db, calc_id) == "pre_job_confirmed"

        # simulate the (deferred) card-delete + its job going away
        db.delete(card); db.delete(job); db.commit()
        assert integrity.derive_calc_status(db, calc_id) is None    # nothing backs the status now

        # forward-only default refuses to downgrade the stray
        assert integrity.reconcile_calc_status(db, calc_id, allow_revert=False) is None
        assert db.get(CalculationRecord, calc_id).status == "pre_job_confirmed"

        # revert-enabled reconcile walks it back to the 'accepted' floor
        assert integrity.reconcile_calc_status(db, calc_id, allow_revert=True) == "accepted"
        db.commit()
        assert db.get(CalculationRecord, calc_id).status == "accepted"
    finally:
        c = db.get(CalculationRecord, calc_id)
        if c is not None:
            c.status = calc_orig
            db.commit()


# ── 3. a confirmed card must anchor a job (Invariant 1, the loud-failure guard) ──
def test_prejob_confirm_creates_job(db):
    """assert_confirmed_card_anchored is the hard guard wired into sign_off: a confirmed Pre-Job Card
    WITH a job passes; strip the job and it raises (rolling back the confirm) rather than ship a
    Planning-invisible card. (The happy API path is covered by test_prejob_signoff_api.py.)"""
    calc = _fresh_calc(db)
    calc_id, calc_orig = calc.id, calc.status
    try:
        card = PrejobCard(calculation_id=calc_id, template_id=None, body_description="P4344 anchor",
                          status="pre_job_confirmed")
        job = ProductionJob(calculation_record_id=calc_id, branch_id=_branch_id(db), source="quote",
                            status="pre_job_confirmed", job_number="P4344J3")
        db.add_all([card, job]); db.commit()

        integrity.assert_confirmed_card_anchored(db, calc_id)       # job present → no raise

        db.delete(job); db.commit()
        with pytest.raises(HTTPException) as exc:
            integrity.assert_confirmed_card_anchored(db, calc_id)   # jobless confirmed card → loud failure
        assert exc.value.status_code == 500 and "invariant 1" in exc.value.detail
    finally:
        c = db.get(CalculationRecord, calc_id)
        if c is not None:
            c.status = calc_orig
            db.commit()


# ── 4. anchorless 'expected' chassis — detect/reconcile, never block, never delete (Invariant 3) ──
def test_chassis_orphan_block(db):
    """Re-scoped (per §3.0) to a detect/reconcile health-check: an anchorless 'expected' chassis is
    detected and marked 'expected_orphaned' (forward, reversible); a job-linked one is left alone; the
    reconcile NEVER deletes (RESTRICT FK + manual/BA-gated recovery preserved)."""
    orphan = ChassisRecord(make="P4344 Orphan", status="expected", source="pre_job_card",
                           created_via="pre_job_card", created_source_ref="P4344-orphan")
    linked = ChassisRecord(make="P4344 Linked", status="expected", source="pre_job_card",
                           created_via="pre_job_card", created_source_ref="P4344-linked")
    db.add_all([orphan, linked]); db.flush()
    job = ProductionJob(branch_id=_branch_id(db), source="quote", status="accepted",
                        job_number="P4344J4", chassis_record_id=linked.id)
    db.add(job); db.commit()
    orphan_id, linked_id = orphan.id, linked.id

    flagged = {r["id"] for r in integrity.find_anchorless_chassis(db)}
    assert orphan_id in flagged and linked_id not in flagged     # detect: only the truly anchorless one

    result = integrity.reconcile_anchorless_chassis(db, apply=True)
    db.commit()
    assert orphan_id in result["marked_orphaned"]
    assert db.get(ChassisRecord, orphan_id).status == "expected_orphaned"   # forward-only, reversible
    assert db.get(ChassisRecord, orphan_id) is not None                     # NEVER deleted
    assert db.get(ChassisRecord, linked_id).status == "expected"            # linked one untouched


# ── 5. reconcile/maintenance scripts refuse the shared dev DB (§3.2 three-tier guard) ─
def test_reconcile_script_hostname_guard(monkeypatch):
    """WO §3.5 "hostname guard" — keyed on db-NAME (§3.0; dev/test/CI share localhost). Complements
    tests/test_db_guard.py (which tests the pure app.db_guard) by exercising the three script tiers."""
    # Tier 1 (reconcilers): hard refuse on dev, pass on *_test.
    monkeypatch.setattr(eg, "_url", lambda: DEV_URL)
    with pytest.raises(RuntimeError):
        eg.require_test_db("backfill")
    # Tier 2 (scoped-destructive): refuse non-interactively on dev; env opt-in clears it.
    monkeypatch.delenv("ICB_ALLOW_SHARED_DB_WRITE", raising=False)
    with pytest.raises(RuntimeError):
        eg.confirm_if_shared_db("seed_v4_28", destroys="delete mock chassis")
    monkeypatch.setenv("ICB_ALLOW_SHARED_DB_WRITE", "1")
    eg.confirm_if_shared_db("seed_v4_28", destroys="delete mock chassis")    # opt-in → no raise
    # BA ask — the env-opt-in confirm (the residual risk surface) is written to the audit trail.
    audit = eg._AUDIT_LOG.read_text(encoding="utf-8") if eg._AUDIT_LOG.exists() else ""
    assert any("script=seed_v4_28" in ln and "mode=env" in ln and "ICB_ALLOW_SHARED_DB_WRITE='1'" in ln
               for ln in audit.splitlines())
    # Tier 3 (additive): announce only, never raises even on dev.
    eg.announce_target("seed_dealers")

    # On a *_test DB every tier proceeds.
    monkeypatch.setattr(eg, "_url", lambda: TEST_URL)
    assert eg.require_test_db("backfill") == "icb_test"
    eg.confirm_if_shared_db("seed_v4_28", destroys="delete mock chassis")
    eg.announce_target("seed_dealers")
