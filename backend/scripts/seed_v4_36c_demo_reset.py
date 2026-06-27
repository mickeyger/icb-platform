"""WO v4.36c §3.7 — demo reseed for the Kenny QC + Dispatch sprint.

Builds on the v4.36b curated demo (reused verbatim: v4.36a `_wipe`+`_reseed` + v4.36b `_curate`), then
layers a §3.7 `_qc_overlay()` in the SAME transaction behind the SAME v4.34.4 invariant gate
(run_health_checks → rollback if dirty). The overlay turns the visual-integrity demo into the QC demo:

  1. Seed Kenny — one user with role 'qc_inspector' (migration 0028 already grants that role
     qc.inspect + qc.signoff; we only add the user row). Idempotent (users are preserved master data).
  2. Two FRESH chassis in 'awaiting_qa' (moved to QA TODAY → green AgeingPill, no prior inspections) to
     light up Kenny's inbox. Job-linked (Invariant-3 safe), mirroring the v4.36a Stage-G2 lifecycle.
  3. A full PASS QC history on the EXISTING dispatched _vin(700): 5 'pass' qc_inspections (one per active
     category) + an immutable 'pass' qc_signoff, so the customer collection-note PDF regenerates on demand
     (without a pass signoff it 409s) and the audit history shows a clean pass for the §6 screenshots.

The 5 defect categories are MIGRATION-seeded (created_by='migration_0028') and are LEFT UNTOUCHED — the
reseed neither wipes nor re-adds them. The qc rows hang off chassis_records via ondelete=CASCADE, so the
existing `_wipe` (which deletes chassis_records) clears them for free — the overlay rebuilds them each run.

Tier-2 discipline: run AFTER the pg_dump snapshot; ICB_ALLOW_SHARED_DB_WRITE=1; --commit to apply.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, text                                   # noqa: E402

from app.database import (                                            # noqa: E402
    Branch, CalculationRecord, Customer, SessionLocal, User,
)
from app.deps import pwd_context                                      # noqa: E402
from app.models.mes import (                                          # noqa: E402
    AssemblyBay, ChassisLifecycleEvent, ChassisRecord, DefectCategory,
    ProductionJob, QcInspection, QcSignoff,
)
from app.services import integrity                                    # noqa: E402
from app.services import visual_integrity as vi                       # noqa: E402

# Reuse the v4.36a canonical reseed + the v4.36b curation verbatim (no transcription risk).
from scripts.seed_v4_36a_demo_reset import (                          # noqa: E402
    _MASTER_PROBE, _counts, _dt, _reseed, _vin, _wipe,
)
from scripts.seed_v4_36b_demo_reset import _LEGACY_VIN, _curate       # noqa: E402

_KENNY = "kenny"
_KENNY_PW = "kenny123"   # demo convention (cf. seed_data.py admin123/user123)


def _qc_overlay(db) -> dict:
    """The v4.36c QC layer, applied AFTER v4.36b `_curate` (so _vin(700)'s customer is already back-filled
    and the fresh chassis below set their own). The 5 migration-seeded categories are read, never written."""
    out = {"kenny": "exists", "awaiting_qa_added": 0, "qc_inspections": 0, "qc_signoffs": 0}

    # ── 1. Kenny — the qc_inspector. 0028 grants the ROLE its perms; we only seed the user row. Idempotent. ──
    kenny = db.execute(select(User).where(User.username == _KENNY)).scalars().first()
    if kenny is None:
        kenny = User(username=_KENNY, password_hash=pwd_context.hash(_KENNY_PW), role="qc_inspector")
        db.add(kenny); db.flush()
        out["kenny"] = "created"
    elif kenny.role != "qc_inspector":
        kenny.role = "qc_inspector"
        out["kenny"] = "role-fixed"

    branch = db.execute(select(Branch).order_by(Branch.id)).scalars().first()
    bays = db.execute(select(AssemblyBay).order_by(AssemblyBay.sort_order)).scalars().all()
    custs = db.execute(select(Customer).order_by(Customer.id).limit(20)).scalars().all()
    bid, bay1 = branch.id, bays[0].id
    ci = iter(custs[8:] + custs)        # offset so these names don't collide with the reseed's first 14

    # ── 2. Two FRESH awaiting_qa chassis (moved to QA today → 0d green AgeingPill) for Kenny's inbox. ──
    #    Mirrors Stage-G2: VCL → assembly_assigned → body_attached → moved_to_awaiting_qa. Job-linked
    #    (Inv-3 safe). Status 'awaiting_qa' occupies NO bay (current_occupants gates on in_assembly), so
    #    the historical assembly_assigned to bay-1 doesn't double-book _vin(600)'s occupancy.
    for i in range(2):
        cu = next(ci)
        calc = CalculationRecord(quote_number=f"D49{10 + i}/06/2026", customer_id=cu.id, branch_id=bid,
                                 status="in_production", created_at=_dt(14), approved_at=_dt(12),
                                 dimensions_json='{"body_type": "6.0m Freezer Body", "requires_chassis": true}',
                                 result_json='{"selling_zar": 310000.0, "cost_zar": 220000.0}')
        db.add(calc); db.flush()
        ch = ChassisRecord(make="Isuzu", model="FVR 900", vin=_vin(810 + i), status="awaiting_qa",
                           source="manual", created_via="planning_job_create",
                           created_source_ref="demo v4.36c §3.7", customer_name=cu.name, body_gap_mm=120,
                           created_by="demo-seed", created_at=_dt(7))
        db.add(ch); db.flush()
        db.add(ProductionJob(calculation_record_id=calc.id, branch_id=bid, job_number=f"4910{i}",
                             job_number_source="quote_derived", source="quote", status="in_production",
                             accepted_at=_dt(12), chassis_record_id=ch.id))
        for etype, days in (("VCL", 9), ("assembly_assigned", 5), ("body_attached", 1),
                            ("moved_to_awaiting_qa", 0)):
            db.add(ChassisLifecycleEvent(
                chassis_record_id=ch.id, cycle_number=1, event_type=etype,
                assembly_bay_id=(bay1 if etype == "assembly_assigned" else None),
                event_date=_dt(days).date(), created_by="demo-seed", created_at=_dt(days)))
        db.flush()   # SessionLocal is autoflush=False — flush the job+events so Inv2's derive_calc_status
        out["awaiting_qa_added"] += 1   # (a SELECT for the calc's job) sees them before the health gate

    # ── 3. Full PASS QC history on the EXISTING dispatched _vin(700) → collection-note PDF works. ──
    d = db.execute(select(ChassisRecord).where(ChassisRecord.vin == _vin(700))).scalars().first()
    cats = db.execute(select(DefectCategory).where(DefectCategory.is_active.is_(True))
                      .order_by(DefectCategory.sort_order)).scalars().all()
    if d is not None and cats:
        for cat in cats:
            db.add(QcInspection(chassis_record_id=d.id, cycle_number=1, category_id=cat.id,
                                category_name=cat.name, inspector_user_id=kenny.id, verdict="pass",
                                notes=None, created_by=_KENNY, created_at=_dt(1)))
            out["qc_inspections"] += 1
        db.add(QcSignoff(chassis_record_id=d.id, cycle_number=1, inspector_user_id=kenny.id,
                         overall_verdict="pass", notes="All categories pass — released for collection.",
                         created_by=_KENNY, created_at=_dt(1)))
        out["qc_signoffs"] += 1

    db.flush()   # autoflush=False — flush the qc rows so the distribution counts in main() see them
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--commit", action="store_true",
                    help="actually commit. Without it, DRY-RUNs (wipe+reseed+curate+qc then ROLLBACK).")
    args = ap.parse_args()

    from scripts._environment_guard import confirm_if_shared_db
    confirm_if_shared_db("seed_v4_36c_demo_reset",
                         destroys="WIPE all workflow data and RESEED the v4.36b curated demo, then OVERLAY "
                                  "the v4.36c QC layer (Kenny qc_inspector + 2 fresh awaiting_qa chassis + a "
                                  "pass QC history on the dispatched _vin(700)). The 5 migration-seeded "
                                  "defect categories are LEFT UNTOUCHED. Master data preserved.")

    db = SessionLocal()
    try:
        before = _counts(db, list(_MASTER_PROBE) + ["icb_mes.production_jobs", "icb_costings.calculations",
                                                    "icb_mes.chassis_records", "icb_mes.defect_categories"])
        print("[v4.36c] BEFORE:", {k.split('.')[-1]: v for k, v in before.items()})

        _wipe(db)
        master_after = _counts(db, list(_MASTER_PROBE))
        for t in _MASTER_PROBE:
            assert master_after[t] == before[t], f"MASTER DATA CHANGED on {t}"
        # the migration-seeded categories must survive the wipe untouched (they are NOT in _WIPE_ORDER)
        cats_after_wipe = _counts(db, ["icb_mes.defect_categories"])["icb_mes.defect_categories"]
        assert cats_after_wipe == before["icb_mes.defect_categories"] == 5, \
            f"defect_categories must survive the wipe at 5, got {cats_after_wipe}"

        base = _reseed(db)
        cur = _curate(db)
        qc = _qc_overlay(db)
        print("[v4.36c] reseed:", base, "| curate:", cur, "| qc:", qc)

        # INVARIANT GATE — on the uncommitted session; commit only if clean.
        health = integrity.run_health_checks(db)
        print("[v4.36c] health:", {"inv1": health["invariant_1_confirmed_cards_without_job"],
                                    "inv2": len(health["invariant_2_calc_status_strays"]),
                                    "inv3": len(health["invariant_3_anchorless_chassis"]),
                                    "clean": health["clean"]})
        if not health["clean"]:
            db.rollback()
            raise SystemExit(f"[v4.36c] ABORTED — invariant violation; ROLLED BACK (icb untouched). {health}")

        # VIN conformance: every VIN strict EXCEPT the one deliberate legacy VIN.
        from app.services import chassis_integrity as cint
        vins = db.execute(select(ChassisRecord.vin).where(ChassisRecord.vin.isnot(None))).scalars().all()
        bad = [v for v in vins if v != _LEGACY_VIN and not cint.VIN_RE.match(v)]
        assert not bad, f"unexpected non-conformant VIN(s): {bad}"

        # Distribution evidence (verify-cycle-close, on the uncommitted session).
        status_dist = dict(db.execute(text(
            "SELECT status, count(*) FROM icb_mes.chassis_records GROUP BY status ORDER BY status")).all())
        print("[v4.36c] CHASSIS BY STATUS:", status_dist)
        qc_rows = _counts(db, ["icb_mes.qc_inspections", "icb_mes.qc_signoffs", "icb_mes.defect_categories"])
        print("[v4.36c] QC ROWS:", {k.split('.')[-1]: v for k, v in qc_rows.items()})
        kenny_role = db.execute(select(User.role).where(User.username == _KENNY)).scalar()
        print(f"[v4.36c] kenny role = {kenny_role!r}")
        flags = vi.compute_planning_board_flags(db, role="admin")
        print("[v4.36c] FLAG DISTRIBUTION (admin):", flags["total"], "items |", flags["by_group"])

        if args.commit:
            db.commit()
            print("[v4.36c] COMMITTED — icb now holds the v4.36c QC demo dataset.")
        else:
            db.rollback()
            print("[v4.36c] DRY-RUN — rolled back. Re-run with --commit to apply.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
