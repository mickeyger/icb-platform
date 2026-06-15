"""WO v4.34.4 §3.3 — READ-ONLY integrity health-check for the Pre-Job → Job → Chassis pipeline.

Runs the three state-machine invariants (app/services/integrity.run_health_checks) as a report and
prints any violations. SELECT-only — safe to run against the shared dev DB (it never writes), which is
exactly its purpose: spot orphaned confirmed cards, calc.status strays, or anchorless 'expected'
chassis BEFORE they surprise anyone. Reconciliation stays manual / BA-gated / snapshot-reversible.

    python -m scripts.health_check          # exit 0 = clean, 1 = violations found
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings                              # noqa: E402
from app.database import SessionLocal                        # noqa: E402
from app.db_guard import resolve_db_name, resolve_host       # noqa: E402
from app.services.integrity import run_health_checks         # noqa: E402


def main() -> int:
    url = settings.DATABASE_URL
    print(f"[health-check] READ-ONLY — target host={resolve_host(url)} db={resolve_db_name(url)}")
    db = SessionLocal()
    try:
        report = run_health_checks(db)
    finally:
        db.close()

    inv1 = report["invariant_1_confirmed_cards_without_job"]
    inv2 = report["invariant_2_calc_status_strays"]
    inv3 = report["invariant_3_anchorless_chassis"]
    print(f"  Invariant 1 — confirmed Pre-Job Cards with NO production job : {len(inv1)}")
    for cid in inv1:
        print(f"      calc {cid}")
    print(f"  Invariant 2 — calc.status strays (ahead of what's backed)    : {len(inv2)}")
    for row in inv2:
        print(f"      {row['detail']}")
    print(f"  Invariant 3 — anchorless 'expected' chassis                  : {len(inv3)}")
    for row in inv3:
        print(f"      chassis {row['id']} ({row['make']}) status={row['status']} via={row['created_via']}")

    if report["clean"]:
        print("[health-check] CLEAN — all three invariants hold.")
        return 0
    print("[health-check] VIOLATIONS FOUND — review above (recovery is manual / BA-gated).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
