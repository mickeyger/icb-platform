"""WO v4.28 — synthetic chassis_records + lifecycle events for CI / fresh dev DBs.

Real chassis data comes from ``translate_chassis_register`` (the Truck Register workbook, ~250
records). CI's mock-seeded DB has no workbook, so the chassis list + the Playwright journey would
have nothing to render. This seeds a small, deterministic set covering every shape the UI must
handle: a closed single cycle (dispatched), an open cycle (in_workshop), a two-cycle history
(re-book-in), and a bare record with no events yet (received).

Idempotent: clears only ``source='mock'`` rows, so it never touches register-translated or
manually-created records. Wired into ``seed_from_mockup`` behind a table-exists guard.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.database import SessionLocal  # noqa: E402
from app.models.mes import ChassisLifecycleEvent, ChassisRecord  # noqa: E402

# (cycle, event_type, event_date, legacy_reference)
_CHASSIS = [
    dict(vin="MOCKVIN0000000001", make="MERCEDES-BENZ", model="ATEGO 1318",
         customer_name="Demo Foods CC", contact_person="A. Buyer", telephone="011 555 0001",
         description="Insulated body — demo", status="dispatched",
         events=[(1, "VCL", date(2026, 1, 12), "VCL-1001"),
                 (1, "DCL", date(2026, 2, 3), "DCL-1001")]),
    dict(vin="MOCKVIN0000000002", make="HINO", model="500 1627",
         customer_name="Cold Chain Ltd", contact_person="B. Planner", telephone="021 555 0002",
         description="Freezer body — demo", status="in_workshop",
         events=[(1, "VCL", date(2026, 3, 5), "VCL-1002")]),
    dict(vin="MOCKVIN0000000003", make="ISUZU", model="FTR 850",
         customer_name="Demo Foods CC", contact_person="A. Buyer", telephone="011 555 0001",
         description="Repeat customer — two cycles", status="dispatched",
         events=[(1, "VCL", date(2025, 11, 1), "VCL-0901"),
                 (1, "DCL", date(2025, 11, 20), "DCL-0901"),
                 (2, "VCL", date(2026, 4, 2), "VCL-1103"),
                 (2, "DCL", date(2026, 4, 18), "DCL-1103")]),
    dict(vin="MOCKVIN0000000004", make="FAW", model="28.280",
         customer_name="Frozen Logistics", contact_person="C. Stores", telephone="031 555 0004",
         description="Just booked — no events", status="received", events=[]),
]


def seed_chassis_mock(db, *, who: str = "seed_v4.28_mock") -> dict:
    """Replace the mock chassis set. Returns counts. Caller commits."""
    db.query(ChassisRecord).filter_by(source="mock").delete()
    db.flush()
    n_rec = n_ev = 0
    for c in _CHASSIS:
        rec = ChassisRecord(
            vin=c["vin"], make=c["make"], model=c["model"],
            customer_name=c["customer_name"], contact_person=c["contact_person"],
            telephone=c["telephone"], description=c["description"],
            status=c["status"], source="mock", created_by=who, updated_by=who,
        )
        db.add(rec)
        db.flush()  # assign rec.id for the event FK
        n_rec += 1
        for (cycle, ev_type, ev_date, ref) in c["events"]:
            db.add(ChassisLifecycleEvent(
                chassis_record_id=rec.id, cycle_number=cycle, event_type=ev_type,
                event_date=ev_date, legacy_reference=ref, created_by=who,
            ))
            n_ev += 1
    db.flush()
    return {"chassis_records": n_rec, "lifecycle_events": n_ev}


def main() -> None:
    db = SessionLocal()
    try:
        counts = seed_chassis_mock(db)
        db.commit()
        print(f"[seed_v4_28_chassis_mock] {counts}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
