"""WO v4.34.2 — ensure every Pre-Job Card anchors a production_job.

A Pre-Job Card that is sent_for_check / pre_job_confirmed but whose calculation has NO production_job
is INVISIBLE to Planning (the ack-candidate pool needs status='Pre-Job Confirmed' AND
production_job_id != null). The normal UI flow can't create such a card (it gates card creation on a
job), but a re-seed truncates icb_mes.production_jobs WITHOUT truncating prejob_cards — orphaning the
user's cards from their jobs. This reconciler re-creates the missing job in the status that matches
the card, so confirmed cards pulse as "Awaiting Ack" again.

Forward-only + idempotent: only creates a job where none exists; never downgrades an existing job.
Used two ways: (1) one-off `python -m scripts.backfill_prejob_job_anchor`; (2) called at the END of
seed_from_mockup so a fresh seed never leaves carded costings jobless.
"""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select                                # noqa: E402

from app.database import Branch, CalculationRecord, SessionLocal  # noqa: E402
from app.config import settings                              # noqa: E402
from app.models.mes import PrejobCard, ProductionJob         # noqa: E402
from app.services.production_jobs import _job_number_from_quote  # noqa: E402

# A card's lifecycle status → the job status it should anchor.
_CARD_TO_JOB = {"sent_for_check": "pre_job_sent", "pre_job_confirmed": "pre_job_confirmed"}


def _default_branch_id(db) -> "int | None":
    row = db.execute(select(Branch).where(Branch.code == settings.DEFAULT_BRANCH_CODE)).scalar_one_or_none()
    return row.id if row else None


def ensure_jobs_for_carded_calcs(db, *, commit: bool = True) -> dict:
    """Create a production_job (in the card-matching status) for any sent_for_check/confirmed card
    whose calculation lacks one. Returns counts. Runs inside the caller's txn when commit=False."""
    now = datetime.now(timezone.utc)
    default_branch = _default_branch_id(db)
    stats = {"checked": 0, "created": 0, "skipped_have_job": 0}
    cards = db.execute(
        select(PrejobCard).where(PrejobCard.status.in_(list(_CARD_TO_JOB)))
    ).scalars().all()
    for card in cards:
        stats["checked"] += 1
        existing = db.execute(select(ProductionJob.id).where(
            ProductionJob.calculation_record_id == card.calculation_id)).first()
        if existing:
            stats["skipped_have_job"] += 1
            continue
        calc = db.get(CalculationRecord, card.calculation_id)
        if calc is None:
            continue
        target = _CARD_TO_JOB[card.status]
        branch_id = getattr(calc, "branch_id", None) or default_branch
        if branch_id is None:
            continue                                          # no branch resolvable — skip (shouldn't happen)
        db.add(ProductionJob(
            calculation_record_id=calc.id,
            branch_id=branch_id,
            job_number=_job_number_from_quote(calc.quote_number),
            job_number_source="quote_derived",
            source="quote",
            status=target,
            accepted_at=now,
            pre_job_sent_at=now,
            pre_job_confirmed_at=(now if target == "pre_job_confirmed" else None),
        ))
        stats["created"] += 1
    if commit:
        db.commit()
    else:
        db.flush()
    return stats


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        s = ensure_jobs_for_carded_calcs(db, commit=not args.dry_run)
        if args.dry_run:
            db.rollback()
    finally:
        db.close()
    print(f"[job-anchor] {'DRY-RUN — ' if args.dry_run else ''}cards checked={s['checked']}  "
          f"jobs created={s['created']}  already had a job={s['skipped_have_job']}")


if __name__ == "__main__":
    main()
