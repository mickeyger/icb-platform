"""WO v4.36a §3.7 — orphan-chassis cleanup (Tier-2).

Find LIVE FK-anchorless chassis (no production_job AND no prejob_card — the §3.6 'wide' orphan set) and,
with --commit, SOFT-DELETE the junk ones through the SAME chassis.soft_delete_chassis chokepoint the admin
UI uses (so script and UI stay consistent: identical refuse-guards, deleted_at, audit). An orphan that
still carries lifecycle history is NOT junk — it is REPORTED for manual Merge, never auto-deleted.

Dry-run by DEFAULT (report only). A --commit run is Tier-2 (confirm_if_shared_db →
ICB_ALLOW_SHARED_DB_WRITE=1 + scripts_audit.log); snapshot the DB (pg_dump) FIRST per standing discipline.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal                                 # noqa: E402
from app.services import chassis as chassis_svc                       # noqa: E402
from app.services import chassis_integrity as ci                      # noqa: E402
from app.services import integrity                                    # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--commit", action="store_true",
                    help="soft-delete junk orphans; without it, report only (dry-run).")
    args = ap.parse_args()

    if args.commit:
        from scripts._environment_guard import confirm_if_shared_db
        confirm_if_shared_db("v4_36a_orphan_chassis_cleanup",
                             destroys="SOFT-DELETE junk orphan chassis (no job / card / lifecycle history). "
                                      "Orphans WITH history are reported for manual Merge, never deleted.")

    db = SessionLocal()
    try:
        orphans = integrity.find_anchorless_chassis(db, statuses=None)    # the wide, FK-anchorless set
        print(f"[orphan-cleanup] {len(orphans)} live FK-anchorless orphan(s) found.")
        deleted, kept = [], []
        for o in orphans:
            print(f"  - chassis {o['id']} vin={o.get('vin')!r} status={o['status']} "
                  f"make={o.get('make')!r} via={o.get('created_via')!r}")
            if not args.commit:
                continue
            try:
                chassis_svc.soft_delete_chassis(db, o["id"], who="v4.36a-orphan-cleanup",
                                                reason="v4.36a §3.7 orphan cleanup")
                deleted.append(o["id"])
            except ci.ChassisIntegrityError as exc:
                kept.append((o["id"], str(exc)))                          # has history → manual Merge

        if args.commit:
            print(f"[orphan-cleanup] COMMITTED — soft-deleted {len(deleted)} junk orphan(s): {deleted}")
            if kept:
                print(f"[orphan-cleanup] {len(kept)} NOT deleted (carry history → resolve via admin Merge): {kept}")
        else:
            print("[orphan-cleanup] DRY-RUN — report only. Re-run with --commit to soft-delete junk orphans.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
