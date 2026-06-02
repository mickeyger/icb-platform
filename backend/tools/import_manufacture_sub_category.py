"""Populate materials.manufacture_sub_category by scanning the formulas in
GRP Costings 2018.xlsx for cross-workbook references to PRICE 2017 MARCH.xlsx.

For each row in every sheet, we read the material name from column A and scan
all other cells in the row for a formula like:

    ='[PRICE 2017 MARCH.xlsx]PLYWOODS + TIMBER'!$C$6/2.98
    =[PRICE 2017 MARCH.xlsx]'PLYWOODS + TIMBER'!$C$6
    =[2]'PLYWOODS + TIMBER'!$C$6      <-- after openpyxl rewrites the link

The sheet name is extracted and matched against materials.name (normalized
case/whitespace/punctuation insensitive). The new field is updated.

Conflicts (same material referenced from different sheets) keep the first hit
and log the rest. Materials with no formula link stay NULL.
"""
import os, re, sqlite3
import openpyxl

XLSX = r"C:\Users\micge\Documents\Burt Costing Model\Latest price list\GRP Costings 2018.xlsx"
DB   = os.path.join(os.path.dirname(__file__), "..", "costing.db")

# Match either form openpyxl produces:
#   '[PRICE 2017 MARCH.xlsx]SHEETNAME'!  or  [PRICE 2017 MARCH.xlsx]'SHEETNAME'!
# Also tolerate the indexed form '[N]SHEETNAME'! that openpyxl rewrites links into,
# but we only care about the named form here (otherwise we don't know the workbook).
RE_DIRECT  = re.compile(r"\[PRICE 2017 MARCH\.xlsx\]'?([^'\]!]+?)'?!", re.IGNORECASE)

def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())

def extract_sheet(formula):
    if not formula or not isinstance(formula, str):
        return None
    m = RE_DIRECT.search(formula)
    return m.group(1).strip() if m else None

def main():
    wb = openpyxl.load_workbook(XLSX, data_only=False)  # need formulas

    # name_norm -> sheet_name
    matches = {}     # first hit wins
    conflicts = {}   # name_norm -> set of (sheet, source_tab, row)
    rows_scanned = 0
    formula_hits = 0

    # External link table — openpyxl may rewrite cross-workbook formulas as
    # '[N]SHEET'!$C$6 where N indexes wb._external_links. We resolve N → file
    # so we still match references that look indexed.
    from urllib.parse import unquote
    ext_files = []
    for el in getattr(wb, "_external_links", []) or []:
        try:
            ext_files.append(unquote(el.file_link.Target))
        except Exception:
            ext_files.append("")
    re_indexed = re.compile(r"\[(\d+)\]'?([^'\]!]+?)'?!")

    def extract_any(formula):
        sheet = extract_sheet(formula)
        if sheet:
            return sheet
        if not formula or not isinstance(formula, str):
            return None
        m = re_indexed.search(formula)
        if not m:
            return None
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(ext_files) and "PRICE 2017 MARCH" in ext_files[idx].upper():
            return m.group(2).strip()
        return None

    for ws in wb.worksheets:
        for row in ws.iter_rows():
            if not row:
                continue
            name_cell = row[0].value
            if not name_cell or not isinstance(name_cell, str):
                continue
            name = name_cell.strip()
            if not name:
                continue
            rows_scanned += 1
            sheet_name = None
            for c in row[1:]:
                v = c.value
                if isinstance(v, str) and v.startswith("="):
                    sheet_name = extract_any(v)
                    if sheet_name:
                        break
            if not sheet_name:
                continue
            formula_hits += 1
            key = norm(name)
            if key not in matches:
                matches[key] = sheet_name
            elif matches[key] != sheet_name:
                conflicts.setdefault(key, []).append(
                    (sheet_name, ws.title, row[0].row)
                )

    print(f"Scanned {rows_scanned} named rows, {formula_hits} with PRICE-file links")
    print(f"Distinct material names matched: {len(matches)}")

    # Apply to DB
    con = sqlite3.connect(os.path.abspath(DB))
    cur = con.cursor()
    cur.execute("SELECT id, name FROM materials")
    db_rows = cur.fetchall()

    updated = 0
    unmatched = []
    for mid, mname in db_rows:
        sheet = matches.get(norm(mname))
        if not sheet:
            unmatched.append(mname)
            continue
        cur.execute(
            "UPDATE materials SET manufacture_sub_category = ? WHERE id = ?",
            (sheet, mid),
        )
        updated += 1
    con.commit()
    con.close()

    print(f"\nUpdated {updated} materials with manufacture_sub_category")
    print(f"Unmatched DB materials: {len(unmatched)}")

    if conflicts:
        print(f"\n{len(conflicts)} conflicting materials (kept first hit):")
        for key, hits in list(conflicts.items())[:20]:
            print(f"  - {key!r}: kept '{matches[key]}', also seen {hits[:3]}")
        if len(conflicts) > 20:
            print(f"  ... ({len(conflicts) - 20} more)")

if __name__ == "__main__":
    main()
