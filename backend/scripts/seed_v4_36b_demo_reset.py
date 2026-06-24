"""WO v4.36b §3.7 — demo CURATION reseed for the Visual Integrity sprint.

Builds on the v4.36a canonical reseed (reused verbatim — `_wipe` + `_reseed`), then layers a §3.7
`_curate()` in the SAME transaction, behind the SAME v4.34.4 invariant gate (run_health_checks → rollback
if dirty). The curation turns the verification-canonical state into a DEMO-curated state for the §0.20
click-through + the §6 screenshots:

  1. Kill the chassis_no_customer NOISE — back-fill every demo chassis's customer from its linked job
     (the v4.36a reseed leaves chassis.customer_name NULL; customer lives on the job). Exactly ONE
     deliberate chassis_no_customer remains (Stage I).
  2. Rebalance occupied-bay ages so the AgeingPill day-counter spans all three §0.6 bands:
     ~1d (green) / ~4d (amber) / ~6d (red).
  3. One bay made ready_to_merge (panels_arrived_in_bay >1d) → bay_ready_to_merge_stale (2nd bay flag type).
  4. Stage I — deliberate, invariant-safe flag records lighting the rest of the catalog:
     chassis_no_vin, chassis_no_make_model, chassis_vin_format_legacy, chassis_no_customer,
     job_eta_overdue ×2, job_eta_missing, and ONE aged sent_for_check card lighting three sign-off flags.

chassis_no_production_job is DELIBERATELY NOT seeded — it IS Invariant 3 (anchorless expected chassis),
which the reseed's gate refuses (correct; that flag's home is real-data admin Find-Orphan recovery).

Tier-2 discipline: run AFTER the pg_dump snapshot; ICB_ALLOW_SHARED_DB_WRITE=1; --commit to apply.
"""
import argparse
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, text                                    # noqa: E402

from app.database import Branch, CalculationRecord, Customer, SessionLocal  # noqa: E402
from app.models.mes import (                                           # noqa: E402
    AssemblyBay, ChassisLifecycleEvent, ChassisRecord, PrejobCard, PrejobTemplate,
    ProductionJob, ProductionJobBayEvent,
)
from app.services import integrity                                     # noqa: E402
from app.services import visual_integrity as vi                        # noqa: E402

# Reuse the v4.36a canonical reseed verbatim (no transcription risk).
from scripts.seed_v4_36a_demo_reset import (                           # noqa: E402
    _MASTER_PROBE, _NOW, _TODAY, _counts, _dt, _reseed, _vin, _wipe,
)

_LEGACY_VIN = "LEGACY436VIN1"   # deliberately NON-conformant (has 'I', not 17 chars) → chassis_vin_format_legacy


def _curate(db) -> dict:
    branch = db.execute(select(Branch).order_by(Branch.id)).scalars().first()
    tpl = db.execute(select(PrejobTemplate).where(PrejobTemplate.is_active.is_(True))
                     .order_by(PrejobTemplate.id)).scalars().first()
    bays = db.execute(select(AssemblyBay).order_by(AssemblyBay.sort_order)).scalars().all()
    custs = db.execute(select(Customer).order_by(Customer.id).limit(30)).scalars().all()
    bid = branch.id
    ci = iter(custs * 3)                                               # plenty of names for Stage I
    cur = {"backfilled": 0, "stage_i": 0}

    # ── 1. Back-fill chassis customers from the linked job (kill the chassis_no_customer noise) ──
    for ch in db.execute(select(ChassisRecord)).scalars().all():
        job = db.execute(select(ProductionJob)
                         .where(ProductionJob.chassis_record_id == ch.id)).scalars().first()
        name = None
        if job is not None and job.calculation_record_id:
            calc = db.get(CalculationRecord, job.calculation_record_id)
            if calc and calc.customer_id:
                cu = db.get(Customer, calc.customer_id)
                name = cu.name if cu else None
        ch.customer_name = name or "Icecold Demo Co"
        cur["backfilled"] += 1

    # ── 2. Rebalance Stage-E occupied-bay ages → AgeingPill green(1d)/amber(4d); add ready_to_merge ──
    # Stage E chassis are _vin(401) (bay-2) and _vin(402) (bay-3), assembly_assigned 2d ago.
    e1 = db.execute(select(ChassisRecord).where(ChassisRecord.vin == _vin(401))).scalars().first()
    e2 = db.execute(select(ChassisRecord).where(ChassisRecord.vin == _vin(402))).scalars().first()
    for ch, days in ((e1, 1), (e2, 4)):                               # 1d green, 4d amber on the day-counter
        if ch is None:
            continue
        ev = db.execute(select(ChassisLifecycleEvent).where(
            ChassisLifecycleEvent.chassis_record_id == ch.id,
            ChassisLifecycleEvent.event_type == "assembly_assigned")).scalars().first()
        if ev is not None:
            ev.event_date = _dt(days).date()
            ev.created_at = _dt(days)
    # e2's bay (4d) becomes ready_to_merge: its job's panels land in that bay >1d ago, no body attached.
    if e2 is not None:
        job_e2 = db.execute(select(ProductionJob)
                            .where(ProductionJob.chassis_record_id == e2.id)).scalars().first()
        ev_e2 = db.execute(select(ChassisLifecycleEvent).where(
            ChassisLifecycleEvent.chassis_record_id == e2.id,
            ChassisLifecycleEvent.event_type == "assembly_assigned")).scalars().first()
        if job_e2 is not None and ev_e2 is not None and ev_e2.assembly_bay_id is not None:
            db.add(ProductionJobBayEvent(production_job_id=job_e2.id, bay_id=ev_e2.assembly_bay_id,
                                         event_type="panels_arrived_in_bay", created_at=_dt(2)))

    # Stage G (_vin(600)) post_attached: age body_attached to 6d → bay_post_attached_stale (RED, >5d).
    # (At the seed's default 3d it sits exactly on the band edge — >3 is false — so it wouldn't light.)
    g1 = db.execute(select(ChassisRecord).where(ChassisRecord.vin == _vin(600))).scalars().first()
    if g1 is not None:
        ev = db.execute(select(ChassisLifecycleEvent).where(
            ChassisLifecycleEvent.chassis_record_id == g1.id,
            ChassisLifecycleEvent.event_type == "body_attached")).scalars().first()
        if ev is not None:
            ev.event_date = _dt(6).date()
            ev.created_at = _dt(6)

    # G2 (_vin(800)) awaiting_qa: move the QA handoff to 4d ago → awaiting_qa_stale (>3d, amber).
    g2 = db.execute(select(ChassisRecord).where(ChassisRecord.vin == _vin(800))).scalars().first()
    if g2 is not None:
        ev = db.execute(select(ChassisLifecycleEvent).where(
            ChassisLifecycleEvent.chassis_record_id == g2.id,
            ChassisLifecycleEvent.event_type == "moved_to_awaiting_qa")).scalars().first()
        if ev is not None:
            ev.event_date = _dt(4).date()
            ev.created_at = _dt(4)

    # ── 3. Stage I — deliberate flag records (invariant-safe: each chassis linked to a job) ──
    def _cust():
        return next(ci).id

    def mk(quote, jobnum, jobstatus, calcstatus, *, make="Isuzu", model="FVR 900", vin=None,
           customer="Stage-I Demo Co", chstatus="expected", created_days=3, eta_days=None,
           ack_days=None, card_status=None, card_vin=None, sent_days=None,
           sales_signed_days=None):
        calc = CalculationRecord(quote_number=quote, customer_id=_cust(), branch_id=bid, status=calcstatus,
                                 created_at=_dt(20), approved_at=_dt(15),
                                 dimensions_json='{"body_type": "5.4m Chiller Body", "requires_chassis": true}',
                                 result_json='{"selling_zar": 285000.0, "cost_zar": 205000.0}')
        db.add(calc); db.flush()
        ch = None
        if chstatus is not None:
            ch = ChassisRecord(make=make, model=model, vin=vin, status=chstatus, source="manual",
                               created_via="pre_job_card", created_source_ref="demo v4.36b §3.7",
                               customer_name=customer, body_gap_mm=120, created_by="demo-seed",
                               created_at=_dt(created_days))
            db.add(ch); db.flush()
        eta = _dt(eta_days) if eta_days is not None else None
        ack = _dt(ack_days) if ack_days is not None else None
        job = ProductionJob(calculation_record_id=calc.id, branch_id=bid, job_number=jobnum,
                            job_number_source="quote_derived", source="quote", status=jobstatus,
                            accepted_at=_dt(15), chassis_record_id=(ch.id if ch else None),
                            chassis_eta=eta, planning_acknowledged_at=ack)
        db.add(job); db.flush()
        if card_status is not None:
            card = PrejobCard(calculation_id=calc.id, template_id=tpl.id, body_description="5.4m Chiller Body",
                              chassis_make_model=make, vin_number=card_vin,
                              sections=[{"name": "GRP", "items": [{"text": "x"}]}], status=card_status,
                              sent_for_check_at=(_dt(sent_days) if sent_days is not None else None),
                              sales_rep_signoff_at=(_dt(sales_signed_days) if sales_signed_days is not None else None))
            db.add(card); db.flush()
        cur["stage_i"] += 1
        return ch, job

    # I1 chassis_no_vin (RED) — expected chassis, VIN NULL, confirmed (card attests make, no VIN — §3.9 path)
    mk("D4101/06/2026", "41010", "pre_job_confirmed", "pre_job_confirmed",
       make="Isuzu FVR 900", vin=None, chstatus="expected", created_days=3,
       card_status="pre_job_confirmed", card_vin=None)
    # I2 chassis_no_make_model (AMBER) — expected stub, make NULL, VIN present
    mk("D4102/06/2026", "41020", "pre_job_confirmed", "pre_job_confirmed",
       make=None, model=None, vin=_vin(910), chstatus="expected", created_days=3,
       card_status="pre_job_confirmed", card_vin=_vin(910))
    # I3 chassis_vin_format_legacy (AMBER) — non-conforming VIN on a booked-in chassis
    mk("D4103/06/2026", "41030", "planning", "planning",
       make="Hino 500", vin=_LEGACY_VIN, chstatus="in_workshop", created_days=5,
       eta_days=-7, ack_days=3)
    # I4 chassis_no_customer (RED) — VIN + make present, customer BLANK, linked to a job
    mk("D4104/06/2026", "41040", "planning", "planning",
       make="FAW 28.380", vin=_vin(940), customer=None, chstatus="in_workshop", created_days=4,
       eta_days=-7, ack_days=3)
    # I5 job_eta_overdue (RED) ×2 — planning job, ETA in the past, chassis NOT received
    for k in range(2):
        mk(f"D410{5+k}/06/2026", f"4105{k}", "planning", "planning",
           make="Scania P320", vin=_vin(950 + k), chstatus="expected", created_days=2,
           eta_days=3 + k)                                            # chassis_eta 3-4d in the PAST
    # I6 job_eta_missing (AMBER) — planning, no ETA, acknowledged >1d ago, not received
    mk("D4107/06/2026", "41070", "planning", "planning",
       make="Hino 300", vin=_vin(960), chstatus="received", created_days=2,
       eta_days=None, ack_days=3)
    # I7 aged sent_for_check card → prejob_sent_stale + signoff_pending_long + signoff_role_pending_5days
    mk("D4108/06/2026", "41080", "pre_job_sent", "pre_job_sent",
       make="Isuzu NPR", vin=None, chstatus=None,                     # no chassis — pre-job stage, no Inv3 concern
       card_status="sent_for_check", card_vin=None, sent_days=8)      # sent 8d ago, no sign-offs → 3 flags

    return cur


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--commit", action="store_true",
                    help="actually commit. Without it, DRY-RUNs (wipe+reseed+curate then ROLLBACK).")
    args = ap.parse_args()

    from scripts._environment_guard import confirm_if_shared_db
    confirm_if_shared_db("seed_v4_36b_demo_reset",
                         destroys="WIPE all workflow data and RESEED the v4.36a canonical lifecycle, then "
                                  "CURATE it for the v4.36b demo (back-fill customers, age bays, +Stage-I "
                                  "deliberate flag records). Master data preserved.")

    db = SessionLocal()
    try:
        before = _counts(db, list(_MASTER_PROBE) + ["icb_mes.production_jobs", "icb_costings.calculations",
                                                    "icb_mes.chassis_records"])
        print("[v4.36b] BEFORE:", {k.split('.')[-1]: v for k, v in before.items()})

        _wipe(db)
        master_after = _counts(db, list(_MASTER_PROBE))
        for t in _MASTER_PROBE:
            assert master_after[t] == before[t], f"MASTER DATA CHANGED on {t}"
        base = _reseed(db)
        cur = _curate(db)
        print("[v4.36b] reseed:", base, "| curate:", cur)

        # INVARIANT GATE — on the uncommitted session; commit only if clean.
        health = integrity.run_health_checks(db)
        print("[v4.36b] health:", {"inv1": health["invariant_1_confirmed_cards_without_job"],
                                    "inv2": len(health["invariant_2_calc_status_strays"]),
                                    "inv3": len(health["invariant_3_anchorless_chassis"]),
                                    "clean": health["clean"]})
        if not health["clean"]:
            db.rollback()
            raise SystemExit(f"[v4.36b] ABORTED — invariant violation; ROLLED BACK (icb untouched). {health}")

        # VIN conformance: every VIN strict EXCEPT the one deliberate legacy VIN (the flag's whole point).
        from app.services import chassis_integrity as cint
        vins = db.execute(select(ChassisRecord.vin).where(ChassisRecord.vin.isnot(None))).scalars().all()
        bad = [v for v in vins if v != _LEGACY_VIN and not cint.VIN_RE.match(v)]
        assert not bad, f"unexpected non-conformant VIN(s): {bad}"

        # Flag distribution (verify-cycle-close evidence, on the uncommitted session).
        summary = vi.compute_planning_board_flags(db, role="admin")
        print("[v4.36b] FLAG DISTRIBUTION (admin):", summary["total"], "items |", summary["by_flag"])
        print("[v4.36b] by_group:", summary["by_group"])

        if args.commit:
            db.commit()
            print("[v4.36b] COMMITTED — icb now holds the v4.36b curated demo dataset.")
        else:
            db.rollback()
            print("[v4.36b] DRY-RUN — rolled back. Re-run with --commit to apply.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
