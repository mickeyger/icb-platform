"""Backfill: reconcile calculations.status (+ production_jobs.status) with the Pre-Job Card lifecycle.

Companion to fix/prejob-card-status-sync. The v4.33 card flow drove production_jobs.status but left
calculations.status at 'accepted', so both-signed-off cards showed 'Accepted' on the Costings
dashboard and never surfaced as Pre-Job Confirmed / flowed to Planning. The seed also creates
confirmed cards on top of 'accepted' calcs/jobs. This walks every Pre-Job Card and advances its
linked calculation (and job) FORWARD to match the card — never downgrading a costing that has moved
further on (e.g. a job already 'planning'), and never touching a 'declined' costing.

Idempotent + forward-only (rank-guarded). Safe to re-run. Usage:
    python -m scripts.backfill_prejob_calc_status [--dry-run]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select                                    # noqa: E402

from app.database import CalculationRecord, SessionLocal         # noqa: E402
from app.models.mes import PrejobCard, ProductionJob            # noqa: E402

# Pre-Job lifecycle ordering — advance forward only.
_RANK = {"pending": -1, "accepted": 0, "pre_job_sent": 1, "pre_job_confirmed": 2,
         "planning": 3, "in_production": 4, "completed": 5, "dispatched": 6}

# A card's status → the lifecycle status its costing/job should be AT LEAST.
_CARD_TO_STATUS = {"sent_for_check": "pre_job_sent", "pre_job_confirmed": "pre_job_confirmed"}


def _rank(s):
    return _RANK.get(s, -2)


def backfill(dry_run: bool = False) -> dict:
    db = SessionLocal()
    stats = {"cards": 0, "calc_advanced": 0, "job_advanced": 0}
    try:
        cards = db.execute(select(PrejobCard)).scalars().all()
        for card in cards:
            target = _CARD_TO_STATUS.get(card.status)            # draft (incl. rejected) → skip; ambiguous
            if target is None:
                continue
            stats["cards"] += 1
            calc = db.get(CalculationRecord, card.calculation_id)
            if calc is not None and calc.status != "declined" and _rank(calc.status) < _rank(target):
                print(f"  calc {calc.id} ({calc.quote_number}): {calc.status} -> {target}")
                calc.status = target
                stats["calc_advanced"] += 1
            job = db.execute(
                select(ProductionJob).where(ProductionJob.calculation_record_id == card.calculation_id)
            ).scalars().first()
            if job is not None and _rank(job.status) < _rank(target):
                print(f"  job  {job.id} ({job.job_number}): {job.status} -> {target}")
                job.status = target
                if target == "pre_job_confirmed" and job.pre_job_confirmed_at is None:
                    from datetime import datetime, timezone
                    job.pre_job_confirmed_at = datetime.now(timezone.utc)
                stats["job_advanced"] += 1
        if dry_run:
            db.rollback()
            print("[dry-run] rolled back — no changes written")
        else:
            db.commit()
        return stats
    finally:
        db.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="report only; write nothing")
    args = ap.parse_args()
    # WO v4.34.4 §3.2 — a reconcile script: HARD-refuse unless DATABASE_URL is a *_test DB.
    # ("No reconcile scripts running ever again on the shared dev DB.") Applies even to --dry-run.
    from scripts._environment_guard import require_test_db
    require_test_db("backfill_prejob_calc_status (reconcile calc/job status)")
    s = backfill(dry_run=args.dry_run)
    print(f"\n[backfill] cards considered={s['cards']}  calcs advanced={s['calc_advanced']}  "
          f"jobs advanced={s['job_advanced']}")
