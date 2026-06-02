"""
tools/reset_costing_data.py

Wipe all costing / BOM / quote / formula / material data from costing.db.

KEEPS:
    users, customers, themes, admin_settings, alembic_version
WIPES:
    bill_of_materials, trailer_ratios, price_history, calculations,
    pdf_templates, formulas, materials, material_categories,
    bom_sections, trailer_types

Tables are emptied in FK-dependency order.  SQLite auto-increment counters
are also reset so fresh imports start from id=1.

Usage
-----
    python tools/reset_costing_data.py            # interactive confirm
    python tools/reset_costing_data.py --yes      # skip confirmation
"""

from __future__ import annotations
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "costing.db"

# Order matters: children first, parents last.
WIPE_ORDER = [
    "bill_of_materials",
    "trailer_ratios",
    "price_history",
    "calculations",
    "pdf_templates",
    "formulas",
    "materials",
    "material_categories",
    "bom_sections",
    "trailer_types",
]

KEEP = {"users", "customers", "themes", "admin_settings", "alembic_version",
        "sqlite_sequence"}


def main() -> int:
    skip_confirm = "--yes" in sys.argv or "-y" in sys.argv
    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} not found")
        return 1

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    print(f"DB: {DB_PATH}")
    print()
    print("Pre-wipe row counts:")
    for t in WIPE_ORDER:
        try:
            n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t:25s} {n}")
        except sqlite3.OperationalError as e:
            print(f"  {t:25s} (skip: {e})")

    if not skip_confirm:
        ans = input("\nType DELETE to wipe these tables: ").strip()
        if ans != "DELETE":
            print("Aborted.")
            return 2

    cur.execute("PRAGMA foreign_keys = OFF")
    for t in WIPE_ORDER:
        try:
            cur.execute(f"DELETE FROM {t}")
            cur.execute(f"DELETE FROM sqlite_sequence WHERE name = ?", (t,))
        except sqlite3.OperationalError as e:
            print(f"  ! {t}: {e}")
    con.commit()
    cur.execute("PRAGMA foreign_keys = ON")

    print()
    print("Post-wipe row counts:")
    for t in WIPE_ORDER:
        try:
            n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t:25s} {n}")
        except sqlite3.OperationalError:
            pass

    print()
    print("Kept (unchanged):")
    for t in sorted(KEEP - {"sqlite_sequence"}):
        try:
            n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t:25s} {n}")
        except sqlite3.OperationalError:
            pass

    cur.execute("VACUUM")
    con.close()
    print("\nDone. VACUUM complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
