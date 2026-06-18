"""WO v4.36a §3.7 — demo workflow-data WIPE + RESEED with CONFORMANT VINs (the v4.35 reset, hardened
for the Chassis Integrity sprint).

Identical Tier-2 discipline + atomic safety to seed_v4_35_demo_reset (run AFTER the mandatory pg_dump
snapshot; ICB_ALLOW_SHARED_DB_WRITE=1 + scripts_audit.log; wipe + reseed + in-session run_health_checks
ALL in ONE transaction → rollback if any v4.34.4 invariant fails). Two v4.36a deltas:

  1. CONFORMANT VINs — every seeded VIN is strict ISO-3779 (17 chars, [A-HJ-NPR-Z0-9], no I/O/Q) via
     _vin(); the v4.35 'DEMO…' VINs all contained an 'O' and so were non-conformant. This lets Michael's
     click-around exercise the §3.5b adoption flow (a typed conformant VIN that MATCHES a seeded one).
  2. ~3 UNLINKED production_jobs — the pre_job_sent Stage-A/B jobs carry NO chassis_record_id, so they
     surface in GET /api/production-jobs/unlinked and feed the §3.5b/§3.5c auto-populate (blocked since
     §3.5b because the live demo had every job linked). Their cards carry a chassis_make_model so the
     prefill shows a chassis type, not just the customer.

Master data (customers/contacts/is_dealer, templates, DDMs, users, bays) is preserved untouched.
"""
import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, text                                   # noqa: E402

from app.database import Branch, CalculationRecord, Customer, SessionLocal  # noqa: E402
from app.models.mes import (                                          # noqa: E402
    AssemblyBay, ChassisLifecycleEvent, ChassisRecord, PlanningSlot, PrejobCard,
    PrejobTemplate, ProductionJob,
)
from app.services import integrity                                    # noqa: E402

# Children → parents, RESTRICT-safe (§3.0 DEV-3) — unchanged from v4.35.
_WIPE_ORDER = [
    "icb_mes.production_jobs_audit", "icb_mes.tasks", "icb_mes.photos", "icb_mes.rework_tickets",
    "icb_mes.sign_offs", "icb_mes.work_orders", "icb_mes.planning_acks", "icb_mes.planning_slots",
    "icb_mes.chassis_photos", "icb_mes.chassis_lifecycle_events", "icb_mes.bom_lines",
    "icb_mes.generated_boms", "icb_mes.demand_lines", "icb_mes.prejob_cards",
    "icb_mes.production_jobs", "icb_mes.chassis_records", "icb_costings.calculations",
]
_MASTER_PROBE = {
    "icb_costings.customers": None, "icb_costings.customer_contacts": None,
    "icb_mes.prejob_templates": None, "icb_mes.assembly_bays": None, "icb_costings.users": None,
}

_NOW = datetime.now(timezone.utc)
_TODAY = date.today()


def _vin(seq: int) -> str:
    """A conformant 17-char VIN (ISO-3779: [A-HJ-NPR-Z0-9], no I/O/Q). 'DEMV436A' is a deliberately
    recognisable demo WMI/VDS (8 valid chars, no I/O/Q) + a 9-digit serial = 17."""
    vin = f"DEMV436A{seq:09d}"
    assert len(vin) == 17 and not (set(vin) & set("IOQ")), f"non-conformant demo VIN: {vin}"
    return vin


def _dt(days_ago=0):
    return _NOW - timedelta(days=days_ago)


def _counts(db, tables):
    return {t: db.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in tables}


def _wipe(db):
    for t in _WIPE_ORDER:
        db.execute(text(f"DELETE FROM {t}"))


def _reseed(db):
    """Realistic lifecycle mix on preserved master data; conformant VINs; ~3 unlinked jobs. Returns a
    summary dict. Invariant-safe by construction (pre-job cards only for pre-job-stage units; a
    'pre_job_confirmed' card always gets an anchor job (Inv1); calc.status matches the job (Inv2); every
    chassis is linked to a job — no anchorless 'expected' (Inv3))."""
    branch = db.execute(select(Branch).order_by(Branch.id)).scalars().first()
    bid = branch.id
    tpl = db.execute(select(PrejobTemplate).where(PrejobTemplate.is_active.is_(True))
                     .order_by(PrejobTemplate.id)).scalars().first()
    bays = db.execute(select(AssemblyBay).order_by(AssemblyBay.sort_order)).scalars().all()
    custs = db.execute(select(Customer).order_by(Customer.id).limit(14)).scalars().all()
    if not (branch and tpl and len(bays) >= 5 and len(custs) >= 11):
        raise RuntimeError("missing master data (branch/template/5 bays/customers) — aborting reseed")

    n = {"calc": 0, "job": 0, "card": 0, "chassis": 0, "event": 0, "slot": 0, "unlinked_jobs": 0}
    ci = iter(custs)

    def cust():
        return next(ci).id

    def mk_calc(quote, status, body="5.4m Chiller Body"):
        c = CalculationRecord(
            quote_number=quote, customer_id=cust(), branch_id=bid, status=status,
            created_at=_dt(20), approved_at=(_dt(15) if status != "pre_job_sent" else None),
            dimensions_json='{"body_type": "%s", "requires_chassis": true}' % body,
            result_json='{"selling_zar": 285000.0, "cost_zar": 205000.0, "gross_profit_zar": 80000.0}')
        db.add(c); db.flush(); n["calc"] += 1
        return c

    def mk_job(calc, status, jobnum, chassis_id=None, **kw):
        j = ProductionJob(
            calculation_record_id=calc.id, branch_id=bid, job_number=jobnum,
            job_number_source="quote_derived", source="quote", status=status,
            accepted_at=_dt(15), chassis_record_id=chassis_id, **kw)
        db.add(j); db.flush(); n["job"] += 1
        if chassis_id is None and status not in ("completed", "dispatched", "cancelled"):
            n["unlinked_jobs"] += 1
        return j

    def mk_chassis(make, vin, status, created_via="planning_job_create", body_gap=120):
        ch = ChassisRecord(make=make, model="FVR 900", vin=vin, status=status, source="manual",
                           created_via=created_via, created_source_ref="demo v4.36a",
                           body_gap_mm=body_gap, created_by="demo-seed")
        db.add(ch); db.flush(); n["chassis"] += 1
        return ch

    def mk_event(ch, etype, days_ago, bay_id=None):
        e = ChassisLifecycleEvent(
            chassis_record_id=ch.id, cycle_number=1, event_type=etype, assembly_bay_id=bay_id,
            event_date=_dt(days_ago).date(), created_by="demo-seed", created_at=_dt(days_ago))
        db.add(e); db.flush(); n["event"] += 1
        return e

    def mk_card(calc, status, jobnum, vin=None, make=None, **kw):
        card = PrejobCard(
            calculation_id=calc.id, template_id=tpl.id, body_description="5.4m Chiller Body",
            chassis_make_model=make,
            sections=[{"name": "GRP SECTION", "items": [{"text": "Demo body build checklist"}]}],
            vin_number=vin, status=status, created_by_user_id=None, **kw)
        db.add(card); db.flush(); n["card"] += 1
        return card

    # ── Stage A — pre-job pending (sales sign-off awaiting) ×2 — UNLINKED jobs (no chassis yet) ─────
    for i in range(2):
        c = mk_calc(f"D{4001+i}/06/2026", "pre_job_sent")
        mk_job(c, "pre_job_sent", f"4001{i}", pre_job_sent_at=_dt(4))      # chassis_id=None → unlinked
        mk_card(c, "sent_for_check", f"4001{i}", make="Hino 300 614 SWB (EU3)", sent_for_check_at=_dt(4))

    # ── Stage B — pre-job pending (planner sign-off; sales already signed) ×1 — UNLINKED job ────────
    c = mk_calc("D4010/06/2026", "pre_job_sent")
    mk_job(c, "pre_job_sent", "40100", pre_job_sent_at=_dt(3))            # chassis_id=None → unlinked
    mk_card(c, "sent_for_check", "40100", make="Isuzu FVR 900", sent_for_check_at=_dt(3),
            sales_rep_signoff_at=_dt(2), sales_rep_attestation="Commercial spec confirmed.")

    # ── Stage C — confirmed but blocked (chassis expected, no ETA) ×1 ─────────────
    c = mk_calc("D4020/06/2026", "pre_job_confirmed")
    ch = mk_chassis("Isuzu", _vin(200), "expected", created_via="pre_job_card", body_gap=None)
    j = mk_job(c, "pre_job_confirmed", "40200", chassis_id=ch.id, pre_job_sent_at=_dt(6),
               pre_job_confirmed_at=_dt(5))
    mk_card(c, "pre_job_confirmed", "40200", vin=_vin(200), make="Isuzu FVR 900",
            sent_for_check_at=_dt(6), sales_rep_signoff_at=_dt(5), planner_signoff_at=_dt(5),
            sales_rep_attestation="ok", planner_attestation="Feasible.")

    # ── Stage D — scheduled (on a lane), chassis received ×2 ──────────────────────
    for i in range(2):
        c = mk_calc(f"D{4030+i}/06/2026", "planning")
        ch = mk_chassis("Hino", _vin(301 + i), "in_workshop")
        j = mk_job(c, "planning", f"4030{i}", chassis_id=ch.id, planning_acknowledged_at=_dt(3),
                   planned_start_date=_dt(-7))
        mk_event(ch, "VCL", days_ago=8)
        db.add(PlanningSlot(production_job_id=j.id, week=(_TODAY - timedelta(days=_TODAY.weekday())),
                            bay=f"V-{i+1}", lane="vacuum", slot_position=i + 1, status="scheduled"))
        n["slot"] += 1

    # ── Stage E — in assembly, awaiting attachment ×2 (the "Mark body attached" demo targets) ──
    for i, bay in enumerate(bays[1:3]):                                     # AssemblyBay-2, -3
        c = mk_calc(f"D{4040+i}/06/2026", "in_production")
        ch = mk_chassis("Isuzu", _vin(401 + i), "in_assembly")
        mk_job(c, "in_production", f"4040{i}", chassis_id=ch.id)
        mk_event(ch, "VCL", days_ago=10)
        mk_event(ch, "assembly_assigned", days_ago=2, bay_id=bay.id)        # in the bay, no body yet

    # ── Stage F — body attached today ×2 (Bay-4, Bay-5) ──────────────────────────
    for i, bay in enumerate(bays[3:5]):                                     # AssemblyBay-4, -5
        c = mk_calc(f"D{4050+i}/06/2026", "in_production")
        ch = mk_chassis("Hino", _vin(501 + i), "in_assembly")
        mk_job(c, "in_production", f"4050{i}", chassis_id=ch.id)
        mk_event(ch, "VCL", days_ago=12)
        mk_event(ch, "assembly_assigned", days_ago=5, bay_id=bay.id)
        mk_event(ch, "body_attached", days_ago=0, bay_id=bay.id)            # attached TODAY

    # ── Stage G — body attached earlier this week (post-attached / finishing) ×1 ──
    c = mk_calc("D4060/06/2026", "in_production")
    ch = mk_chassis("FAW", _vin(600), "in_assembly")
    mk_job(c, "in_production", "40600", chassis_id=ch.id)
    mk_event(ch, "VCL", days_ago=18)
    mk_event(ch, "assembly_assigned", days_ago=9, bay_id=bays[0].id)        # AssemblyBay-1
    mk_event(ch, "body_attached", days_ago=3)                              # attached 3 days ago

    # ── Stage G2 — moved off the bay to AWAITING QA ×1 (status-promoting; WO v4.36a.1) ──
    # Pre-staged so the Planning Board AWAITING QA zone has visible content on first load. status is
    # 'awaiting_qa' (NOT in_assembly) so it occupies NO bay — current_occupants excludes it.
    c = mk_calc("D4080/06/2026", "in_production")
    ch = mk_chassis("FAW", _vin(800), "awaiting_qa")
    mk_job(c, "in_production", "40800", chassis_id=ch.id)
    mk_event(ch, "VCL", days_ago=20)
    mk_event(ch, "assembly_assigned", days_ago=10, bay_id=bays[0].id)       # was on a bay…
    mk_event(ch, "body_attached", days_ago=2)
    mk_event(ch, "moved_to_awaiting_qa", days_ago=0)                        # …handed to QA today

    # ── Stage H — completed / dispatched ×1 ──────────────────────────────────────
    c = mk_calc("D4070/06/2026", "completed")
    ch = mk_chassis("Isuzu", _vin(700), "dispatched")
    mk_job(c, "completed", "40700", chassis_id=ch.id, completed_at=_dt(1))
    mk_event(ch, "VCL", days_ago=25)
    mk_event(ch, "body_attached", days_ago=8)
    mk_event(ch, "DCL", days_ago=1)

    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--commit", action="store_true",
                    help="actually commit. Without it, the script DRY-RUNs (wipe+reseed then ROLLBACK).")
    args = ap.parse_args()

    from scripts._environment_guard import confirm_if_shared_db
    confirm_if_shared_db("seed_v4_36a_demo_reset",
                         destroys="WIPE all workflow data (jobs/cards/chassis/events/slots/calcs) and "
                                  "RESEED a demo lifecycle with CONFORMANT VINs + ~3 unlinked jobs. "
                                  "Master data (customers/templates/users/bays) preserved.")

    db = SessionLocal()
    try:
        before = _counts(db, list(_MASTER_PROBE) + ["icb_mes.production_jobs", "icb_costings.calculations",
                                                     "icb_mes.chassis_records"])
        print("[reset] BEFORE:", {k.split('.')[-1]: v for k, v in before.items()})

        _wipe(db)
        wiped = _counts(db, ["icb_mes.production_jobs", "icb_mes.prejob_cards", "icb_mes.chassis_records",
                             "icb_costings.calculations"])
        assert all(v == 0 for v in wiped.values()), f"wipe incomplete: {wiped}"
        master_after_wipe = _counts(db, list(_MASTER_PROBE))
        for t in _MASTER_PROBE:
            assert master_after_wipe[t] == before[t], f"MASTER DATA CHANGED on {t}: {before[t]}->{master_after_wipe[t]}"
        print("[reset] wipe OK — workflow=0, master preserved:",
              {k.split('.')[-1]: v for k, v in master_after_wipe.items()})

        summary = _reseed(db)
        print("[reset] reseed built:", summary)

        # INVARIANT GATE — check on the UNCOMMITTED session; only commit if clean.
        health = integrity.run_health_checks(db)
        print("[reset] health (in-session):", {
            "inv1_confirmed_cards_without_job": health["invariant_1_confirmed_cards_without_job"],
            "inv2_calc_status_strays": len(health["invariant_2_calc_status_strays"]),
            "inv3_anchorless_chassis": len(health["invariant_3_anchorless_chassis"]),
            "clean": health["clean"]})
        if not health["clean"]:
            db.rollback()
            raise SystemExit("[reset] ABORTED — reseed violates a v4.34.4 invariant; ROLLED BACK (icb untouched). "
                             f"Details: {health}")

        # Conformant-VIN proof + unlinked-job count, on the uncommitted session.
        from app.services import chassis_integrity as ci
        vins = db.execute(select(ChassisRecord.vin).where(ChassisRecord.vin.isnot(None))).scalars().all()
        bad = [v for v in vins if not ci.VIN_RE.match(v)]
        assert not bad, f"NON-CONFORMANT VIN seeded: {bad}"
        unlinked = db.execute(text(
            "SELECT count(*) FROM icb_mes.production_jobs WHERE chassis_record_id IS NULL "
            "AND status NOT IN ('completed','dispatched','cancelled')")).scalar()
        print(f"[reset] VIN conformance OK ({len(vins)} VINs, all strict); unlinked jobs = {unlinked}; "
              f"sample VINs = {vins[:3]}")

        if args.commit:
            db.commit()
            print("[reset] COMMITTED. icb now holds the v4.36a demo dataset (conformant VINs + unlinked jobs).")
        else:
            db.rollback()
            print("[reset] DRY-RUN — rolled back (no changes). Re-run with --commit to apply.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
