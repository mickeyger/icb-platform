"""
Import customers from Customers.xlsx into the current customers table.
- Dedupe on bp_code (case-insensitive). Existing rows are updated, new rows inserted.
- Names prefixed "(Inactive) " -> is_active=False and prefix stripped from name.
- Usage: py -3 tools/import_customers.py [--path PATH] [--dry-run]
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import openpyxl
from app.database import SessionLocal, Customer

INACTIVE_RE = re.compile(r"^\s*\(inactive\)\s*", re.IGNORECASE)


def _norm(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def parse_row(row):
    _num, bp_code, bp_name, _bal, email, tel, *_ = row
    bp_code = _norm(bp_code)
    bp_name = _norm(bp_name)
    if not bp_code or not bp_name:
        return None
    is_active = True
    m = INACTIVE_RE.match(bp_name)
    if m:
        is_active = False
        bp_name = bp_name[m.end():].strip()
    return {
        "bp_code": bp_code,
        "name": bp_name,
        "email": _norm(email),
        "telephone": _norm(tel),
        "is_active": is_active,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default=r"C:\Users\micge\Documents\Burt Costing Model\Customers.xlsx")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    wb = openpyxl.load_workbook(args.path, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    print(f"Header: {header}")
    parsed = [p for p in (parse_row(r) for r in rows[1:]) if p]
    print(f"Parsed {len(parsed)} rows from Excel")

    # Collapse duplicates in the file itself (keep first)
    seen = {}
    for p in parsed:
        key = p["bp_code"].upper()
        if key not in seen:
            seen[key] = p
    print(f"Unique bp_code in file: {len(seen)} (dropped {len(parsed) - len(seen)} dupes)")

    db = SessionLocal()
    try:
        existing = {(c.bp_code or "").upper(): c for c in db.query(Customer).all()}
        inserted = updated = unchanged = 0
        for key, p in seen.items():
            c = existing.get(key)
            if c is None:
                c = Customer(**p)
                db.add(c)
                inserted += 1
            else:
                changed = False
                for field, val in p.items():
                    if getattr(c, field) != val:
                        setattr(c, field, val)
                        changed = True
                if changed:
                    updated += 1
                else:
                    unchanged += 1

        print(f"Inserted: {inserted}  Updated: {updated}  Unchanged: {unchanged}")
        if args.dry_run:
            db.rollback()
            print("Dry run — no changes committed.")
        else:
            db.commit()
            print("Committed.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
