"""Wipe demo / transactional workflow data from the icb database while PRESERVING all
structural / reference / master / auth data - so an operator can hand a fresh, blank-slate
app to a new user (onboarding) and let them create the first real costing / chassis / job.

Built for Michael's Simeon onboarding (Phase 1 go-live): Simeon needs no demo costings,
no demo chassis, no demo job numbers. Safely re-runnable (a "second reset" after the intro).

Run from the repo root:

    python -m backend.scripts.wipe_demo_data            # DRY-RUN (default, safe - no changes)
    python -m backend.scripts.wipe_demo_data --apply    # actually DELETE the WIPE rows

DRY-RUN prints a per-table classification report (SCHEMA / TABLE / COUNT / ACTION / NOTE) and
touches nothing. ``--apply`` re-uses the same Tier-2 guard as the demo-reset scripts
(``confirm_if_shared_db``): against a non-``*_test`` DB it demands an explicit confirmation -
an interactive 'y' or ``ICB_ALLOW_SHARED_DB_WRITE=1`` - so it can never fire by accident.

SCOPE (verified against the live schema + FK graph at HEAD, migration 0029):

  WIPE - demo / transactional workflow data:
    icb_mes  chassis (records/audit/photos/lifecycle_events), production_jobs (+audit/bay_events),
             prejob_cards, planning (slots/acks), work_orders/tasks/sign_offs/photos/rework_tickets,
             qc_inspections/qc_signoffs, generated_boms/bom_lines, demand_lines,
             stores demo (stock_counts/discrepancies/po_suggestions/stock_positions/mes_materials/
             suppliers), feedback_submissions (v4.38)
    icb_costings  calculations (the costings / quotes)

  PRESERVE - structural / reference / master / auth (everything else):
    branches, users + roles/permissions/sessions, customers + customer_contacts (real partners),
    chassis_models, defect_categories, prejob_templates, assembly_bays, parking_bays, fridge_units,
    bom_rules/lookups/spec_options, the whole costing-engine reference set in icb_costings
    (materials, formulas, body_option_*, trailer_*, floor_plates, sap_item_codes, ...), every
    alembic_version, and icb_sap.* (READ-ONLY per ADR 0013 - never touched).

DESIGN / SAFETY:
  * DELETE in FK-safe child->parent order, NOT ``TRUNCATE ... CASCADE``. DELETE only ever touches
    the tables we name; ``TRUNCATE CASCADE`` would silently truncate any table that FKs into one
    of ours - including PRESERVE tables. Every ON DELETE CASCADE from a WIPE table points only at
    another WIPE table (verified against the live FK graph), so the cascade stays inside the set.
  * One transaction: delete -> re-count on the uncommitted session -> assert every WIPE table is 0
    AND every PRESERVE table's count is unchanged -> commit. Any failure rolls back; DB untouched.
  * Tolerant: a table absent on an older alembic state is skipped, not an error (e.g.
    chassis_records_audit arrived in 0029 / v4.36.5; an 0028 / v1.39 DB simply won't have it).
  * Re-runnable: DELETE is idempotent - a second run deletes 0 rows.

NB: this is a wipe-only tool; it does NOT re-seed. To repopulate demo data for testing, run the
existing seed flow (``python -m backend.scripts.seed_from_mockup``) afterwards.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Print UTF-8 regardless of the Windows console code page, so neither this report nor the
# env-guard's "WARN" banner crashes on a legacy cp1252 console (no PYTHONUTF8=1 needed).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 - best-effort; older/edge streams lack reconfigure
        pass

from sqlalchemy import text                                            # noqa: E402

from app.database import SessionLocal                                  # noqa: E402

_SCHEMAS = ("icb_mes", "icb_costings", "icb_sap")

# Children -> parents, FK-safe (DELETE order). Each ON DELETE CASCADE from a table here points only
# at another table here, so the cascade never reaches a PRESERVE table. production_jobs ->
# chassis_records is RESTRICT, so production_jobs (and its children) must be deleted first.
_WIPE_ORDER = [
    # -- chassis_records children (qc_*/audit/photos/lifecycle CASCADE on chassis_records) --
    "icb_mes.qc_signoffs",
    "icb_mes.qc_inspections",
    "icb_mes.chassis_records_audit",
    "icb_mes.chassis_photos",
    "icb_mes.chassis_lifecycle_events",
    # -- work_order / sign-off subtree (photos/rework -> sign_offs -> work_orders) --
    "icb_mes.photos",
    "icb_mes.rework_tickets",
    "icb_mes.sign_offs",
    "icb_mes.tasks",
    "icb_mes.work_orders",
    # -- production_jobs children --
    "icb_mes.production_job_bay_events",
    "icb_mes.production_jobs_audit",
    "icb_mes.planning_acks",
    "icb_mes.planning_slots",
    "icb_mes.bom_lines",
    "icb_mes.generated_boms",
    "icb_mes.demand_lines",
    "icb_mes.prejob_cards",
    # -- parents (after their children) --
    "icb_mes.production_jobs",
    "icb_mes.chassis_records",
    # -- stores / materials demo --
    "icb_mes.discrepancies",
    "icb_mes.stock_counts",
    "icb_mes.po_suggestions",
    "icb_mes.stock_positions",
    "icb_mes.mes_materials",
    "icb_mes.suppliers",
    # -- feedback portal (v4.38) --
    "icb_mes.feedback_submissions",
    # -- costings / quotes - AFTER icb_mes.production_jobs (which references it) --
    "icb_costings.calculations",
]
_WIPE_SET = set(_WIPE_ORDER)

# Annotations for the dry-run report. WIPE rows flagged here are demo MASTER worth a second look;
# PRESERVE rows flagged here are kept deliberately and worth a BA glance before any deeper reset.
_NOTES = {
    # WIPE - demo master / verify
    "icb_mes.mes_materials": "demo MES catalogue (re-seedable)",
    "icb_mes.suppliers": "demo supplier master (re-seedable)",
    "icb_mes.feedback_submissions": "v4.38 portal submissions",
    "icb_costings.calculations": "the costings / quotes",
    # PRESERVE - kept on purpose; flag for BA
    "icb_costings.customers": "REAL partner master - preserved",
    "icb_costings.customer_contacts": "REAL partner contacts - preserved",
    "icb_mes.chassis_models": "DDM lookup (ADR 0019) - preserved",
    "icb_mes.defect_categories": "QC lookup (migration-seeded) - preserved",
    "icb_mes.chassis_register": "imported Truck Register reference - preserved (flag for deeper reset)",
    "icb_mes.live_daily_count": "imported stock-count snapshot - preserved (flag for deeper reset)",
    "icb_costings.bom_snapshots": "legacy configurator working data - preserved (not MES-surfaced)",
    "icb_costings.bom_snapshot_items": "legacy configurator working data - preserved (not MES-surfaced)",
    "icb_costings.configurator_drafts": "legacy configurator working data - preserved (not MES-surfaced)",
    "icb_costings.configurator_draft_snapshots": "legacy configurator working data - preserved",
    "icb_costings.commodity_quotes": "legacy costing-engine data - preserved",
}


def _existing_tables(db) -> set:
    rows = db.execute(text(
        "SELECT table_schema, table_name FROM information_schema.tables "
        "WHERE table_schema = ANY(:schemas) AND table_type = 'BASE TABLE'"
    ), {"schemas": list(_SCHEMAS)}).all()
    return {f"{s}.{t}" for s, t in rows}


def _count(db, table: str) -> int:
    schema, name = table.split(".", 1)
    return db.execute(text(f'SELECT count(*) FROM "{schema}"."{name}"')).scalar()


def _print_report(before: dict, existing: set, wipe_present: list, missing: list) -> None:
    print("\n  SCHEMA        TABLE                              COUNT  ACTION    NOTE")
    print("  " + "-" * 96)

    def row(t: str, action: str) -> None:
        schema, name = t.split(".", 1)
        print(f"  {schema:<12}  {name:<32} {before.get(t, 0):>7}  {action:<8}  {_NOTES.get(t, '')}")

    print("  == WIPE (demo / transactional) ==")
    for t in _WIPE_ORDER:
        if t in wipe_present:
            row(t, "WIPE")
    for t in missing:
        schema, name = t.split(".", 1)
        print(f"  {schema:<12}  {name:<32} {'-':>7}  WIPE      (absent on this alembic state - skipped)")

    print("  == PRESERVE (structural / reference / master / auth) ==")
    for t in sorted(existing - _WIPE_SET):
        action = "PRESERVE*" if t.startswith("icb_sap.") else "PRESERVE"
        row(t, action)
    print("  " + "-" * 96)
    print("  * icb_sap.* is READ-ONLY per ADR 0013 - never touched.")

    wipe_rows = sum(before[t] for t in wipe_present)
    preserve_tables = existing - _WIPE_SET
    preserve_rows = sum(before[t] for t in preserve_tables)
    print(f"\n  WIPE     : {len(wipe_present):>3} tables, {wipe_rows:>7} rows"
          f"   ({len(missing)} listed table(s) absent on this DB, skipped)")
    print(f"  PRESERVE : {len(preserve_tables):>3} tables, {preserve_rows:>7} rows")


def wipe(apply: bool) -> None:
    db = SessionLocal()
    try:
        existing = _existing_tables(db)
        wipe_present = [t for t in _WIPE_ORDER if t in existing]
        missing = [t for t in _WIPE_ORDER if t not in existing]
        before = {t: _count(db, t) for t in existing}

        print(f"[wipe] target: {_target()}  |  mode: {'APPLY' if apply else 'DRY-RUN'}")
        _print_report(before, existing, wipe_present, missing)

        if not apply:
            print("\n[wipe] DRY-RUN - no changes made. Re-run with --apply to delete the WIPE rows.")
            return

        # Tier-2 gate: a non-*_test DB (Michael's local 'icb', Marnus's prod) requires explicit
        # confirmation. Only reached on --apply, so the dry-run report needs no confirmation.
        from scripts._environment_guard import confirm_if_shared_db
        confirm_if_shared_db(
            "wipe_demo_data --apply",
            destroys=(f"DELETE every row from {len(wipe_present)} demo/transactional tables "
                      "(costings, chassis, jobs, QC, planning, work-orders, stores, feedback). "
                      "Structural / reference / master / auth data and icb_sap.* are PRESERVED."))

        deleted = {}
        for t in wipe_present:
            schema, name = t.split(".", 1)
            deleted[t] = db.execute(text(f'DELETE FROM "{schema}"."{name}"')).rowcount

        # Verify on the UNCOMMITTED session - commit only if every invariant holds.
        after = {t: _count(db, t) for t in existing}
        wipe_not_zero = {t: after[t] for t in wipe_present if after[t] != 0}
        preserve_tables = existing - _WIPE_SET
        preserve_changed = {t: (before[t], after[t]) for t in preserve_tables if after[t] != before[t]}
        if wipe_not_zero or preserve_changed:
            db.rollback()
            raise SystemExit(
                "[wipe] ABORTED - rolled back; DB untouched. "
                f"wipe-not-zero={wipe_not_zero}  preserve-changed={preserve_changed}")

        db.commit()
        rows = sum(deleted.values())
        print(f"\n[wipe] COMMITTED. Wiped {len(wipe_present)} tables, {rows} rows. "
              f"Preserved {len(preserve_tables)} tables, {sum(after[t] for t in preserve_tables)} rows.")
        print("[wipe] per-table deleted:", {t.split('.')[-1]: n for t, n in deleted.items() if n})
    except SystemExit:
        raise
    except Exception:
        db.rollback()  # any unexpected error mid-delete -> nothing committed; DB untouched
        raise
    finally:
        db.close()


def _target() -> str:
    from app.config import settings
    from app.db_guard import resolve_db_name, resolve_host
    url = settings.DATABASE_URL
    return f"host={resolve_host(url)} db={resolve_db_name(url)}"


def main():
    ap = argparse.ArgumentParser(description="Wipe demo/transactional data; preserve structural data.")
    ap.add_argument("--apply", action="store_true",
                    help="Actually DELETE the WIPE rows. Without it, DRY-RUNs (report only, no changes).")
    args = ap.parse_args()
    wipe(apply=args.apply)


if __name__ == "__main__":
    main()
