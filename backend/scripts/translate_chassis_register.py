"""WO v4.28 §0.3 — one-shot translation of the v4.22 `chassis_register` (workbook import) into the
relational chassis lifecycle model (`chassis_records` + `chassis_lifecycle_events`).

Idempotent: clears `source='register'` records (cascades their events + photos), then reloads.
The `chassis_register` table is NOT modified (kept for rollback). Per the v4.28 pre-flight:
  * null/empty VIN (67) → skip + log (historical workbook artefacts; recoverable from chassis_register).
  * 'CANCELLED'-style VIN (3) → skip + log.
  * short VINs (<14 char) → KEEP + log "verify" (likely partial VINs, not junk).
  * duplicate VIN (1 genuine) → MERGE: append the second row's cycles after the record's existing ones.
Per cycle N: `date_received_N` + `vcl_N` → a VCL (book-in) event; `date_left_N` + `dcl_N` → a DCL
(dispatch) event. `vcl_N`/`dcl_N` are free text → carried as the event's `legacy_reference`.

Run: python -m backend.scripts.translate_chassis_register
"""
import re
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.mes import ChassisLifecycleEvent, ChassisRecord, ChassisRegister  # noqa: E402

_CANCEL_RE = re.compile(r"cancel", re.IGNORECASE)
_SHORT_VIN = 14   # below this, log as "verify" but keep


def _clean(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def translate(db, *, who: str = "translate_v4.28") -> dict:
    # Idempotent: drop register-sourced records (CASCADE removes their events + photos).
    db.query(ChassisRecord).filter_by(source="register").delete()
    db.flush()

    rows = db.execute(select(ChassisRegister).order_by(ChassisRegister.id)).scalars().all()
    report = {"register_rows": len(rows), "chassis_records": 0, "lifecycle_events": 0,
              "skipped_missing_vin": 0, "skipped_cancelled": 0, "short_vin_kept": 0,
              "merged_dup_vin": 0, "rows_with_cycle2": 0}
    by_vin: dict = {}        # vin -> ChassisRecord
    next_cycle: dict = {}    # vin -> next cycle number to assign
    short_samples: list = []

    def add_cycle(rec, cyc, recv, vcl, left, dcl) -> int:
        n = 0
        if recv is not None or vcl:
            db.add(ChassisLifecycleEvent(chassis_record_id=rec.id, cycle_number=cyc, event_type="VCL",
                                         event_date=recv, legacy_reference=(vcl or None)[:128] if vcl else None,
                                         created_by=who))
            n += 1
        if left is not None or dcl:
            db.add(ChassisLifecycleEvent(chassis_record_id=rec.id, cycle_number=cyc, event_type="DCL",
                                         event_date=left, legacy_reference=(dcl or None)[:128] if dcl else None,
                                         created_by=who))
            n += 1
        return n

    for r in rows:
        vin = _clean(r.vehicle_id_no)
        if not vin:
            report["skipped_missing_vin"] += 1
            continue
        if _CANCEL_RE.search(vin):
            report["skipped_cancelled"] += 1
            continue
        if len(vin) < _SHORT_VIN:
            report["short_vin_kept"] += 1
            if len(short_samples) < 10:
                short_samples.append(vin)

        rec = by_vin.get(vin)
        if rec is None:
            rec = ChassisRecord(
                vin=vin[:32], job_number=_clean(r.job_number), customer_name=_clean(r.customer_name),
                contact_person=_clean(r.contact_person), telephone=_clean(r.telephone),
                make=_clean(r.make), model=_clean(r.model), description=_clean(r.description),
                submit_status=_clean(r.submit_status), source="register", source_register_id=r.id,
                status="received", created_by=who, updated_by=who)
            db.add(rec)
            db.flush()
            by_vin[vin] = rec
            next_cycle[vin] = 1
            report["chassis_records"] += 1
        else:
            report["merged_dup_vin"] += 1

        vcl1, dcl1 = _clean(r.vcl_1), _clean(r.dcl_1)
        vcl2, dcl2 = _clean(r.vcl_2), _clean(r.dcl_2)
        c = next_cycle[vin]
        if r.date_received_1 or vcl1 or r.date_left_1 or dcl1:
            report["lifecycle_events"] += add_cycle(rec, c, r.date_received_1, vcl1, r.date_left_1, dcl1)
            c += 1
        if r.date_received_2 or vcl2 or r.date_left_2 or dcl2:
            report["rows_with_cycle2"] += 1
            report["lifecycle_events"] += add_cycle(rec, c, r.date_received_2, vcl2, r.date_left_2, dcl2)
            c += 1
        next_cycle[vin] = c

        # Denormalised status: dispatched if the chassis has left, else still in the workshop.
        last_left = r.date_left_2 or r.date_left_1
        last_dcl = dcl2 or dcl1
        rec.status = "dispatched" if (last_left or last_dcl) else "in_workshop"

    db.flush()
    report["short_vin_samples"] = short_samples
    return report


def main():
    db = SessionLocal()
    try:
        rep = translate(db)
        db.commit()
        print("\n[translate_chassis_register] Complete. Report:")
        for k, v in rep.items():
            print(f"  {k:<22} {v}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
