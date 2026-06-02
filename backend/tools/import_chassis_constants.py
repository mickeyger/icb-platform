"""Import quantity + unit price for chassis constants (steel + running gear)
from the CHASSIS COSTINGS sheet of GRP Costings 2018.xlsx into costing.db.

Matches by normalized name. Updates unit_price always.
For quantity: only overwrites qty_constant when the row is NOT length-scaled
(qty_per_metre == 0) — preserves the existing per-metre formulas.
"""
import os, re, sys, sqlite3, openpyxl

XLSX = r"C:\Users\micge\Documents\Burt Costing Model\GRP Costings 2018.xlsx"
DB   = os.path.join(os.path.dirname(__file__), "..", "costing.db")

def norm(s):
    s = str(s or "").lower()
    # spelling/abbreviation aliases between sheet and DB
    s = s.replace("rolles", "rolled")
    s = s.replace("sq tube", "square tube").replace("sqtube", "squaretube")
    return re.sub(r"[^a-z0-9]", "", s)

def main():
    wb = openpyxl.load_workbook(XLSX, data_only=True)
    ws = wb["CHASSIS COSTINGS"]

    # Pull (name, qty, unit_price) triples from the steel + running-gear blocks.
    # Steel:  rows 49..60, name=A, qty=C, price=D
    # Running gear: rows 68..75, name=A, qty=C, price=D
    def grab(rng, cat):
        out = []
        for r in rng:
            name = ws.cell(r, 1).value
            qty   = ws.cell(r, 3).value
            price = ws.cell(r, 4).value
            if not name:
                continue
            try:    qty   = float(qty)   if qty   not in (None, "") else None
            except: qty   = None
            try:    price = float(price) if price not in (None, "") else None
            except: price = None
            out.append((cat, str(name).strip(), qty, price))
        return out

    rows = grab(range(49, 61), "steel") + grab(range(68, 76), "running_gear")
    print(f"Parsed {len(rows)} rows from sheet")

    con = sqlite3.connect(os.path.abspath(DB))
    cur = con.cursor()
    cur.execute("SELECT id, category, name, qty_per_metre, qty_constant FROM chassis_constants")
    db_rows = cur.fetchall()

    by_norm = {}
    for rid, cat, name, qpm, qc in db_rows:
        by_norm.setdefault((cat, norm(name)), (rid, qpm or 0.0, qc or 0.0))

    updated, missed = 0, []
    for cat, name, qty, price in rows:
        key = (cat, norm(name))
        match = by_norm.get(key)
        if match is None:
            missed.append((cat, name))
            continue
        rid, qpm, qc = match

        sets, vals = [], []
        if price is not None:
            sets.append("unit_price = ?"); vals.append(price)
        # Only overwrite qty_constant when row isn't length-scaled (preserve formulas)
        if qty is not None and qpm == 0:
            sets.append("qty_constant = ?"); vals.append(qty)
        if not sets:
            continue
        vals.append(rid)
        cur.execute(f"UPDATE chassis_constants SET {', '.join(sets)} WHERE id=?", vals)
        qty_disp   = f"{qty:.2f}" if qty is not None else "—"
        price_disp = f"R {price:>10,.2f}" if price is not None else "—"
        scaled     = " (length-scaled, qty kept)" if qpm != 0 else ""
        print(f"  OK{cat:13s} {name:40s} qty={qty_disp:>7s}  {price_disp}{scaled}")
        updated += 1
    con.commit()
    con.close()

    print(f"\nUpdated {updated} rows.")
    if missed:
        print("Unmatched sheet rows:")
        for cat, name in missed:
            print(f"  XX{cat:13s} {name}")

if __name__ == "__main__":
    main()
