"""
tools/scan_formula_references.py

CLI wrapper over app.excel_formula_scanner.

Scans GRP Costings 2018.xlsx and writes a CSV listing every BOM row whose
PRICE column ultimately resolves (directly OR through a chain of intra-sheet
cell references) to a cell in FORMULAS 2018.xls.

Usage:
    python tools/scan_formula_references.py
    python tools/scan_formula_references.py --xlsx "C:/path/to/GRP Costings 2018.xlsx"
    python tools/scan_formula_references.py --sheet "UP TO 2.3 CHILLER BODY"
    python tools/scan_formula_references.py --out report.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

# Make `app` importable when running the script directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.excel_formula_scanner import DEFAULT_GRP_PATH, scan_workbook


_FIELDS = [
    "body_type", "section", "item", "row", "price_col",
    "ref_sheet", "ref_cell", "had_aggregate", "raw_formula", "chain",
]


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDS)
        writer.writeheader()
        for r in rows:
            row = {k: r.get(k, "") for k in _FIELDS}
            row["had_aggregate"] = "yes" if row["had_aggregate"] else ""
            writer.writerow(row)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Scan GRP Costings for FORMULAS 2018.xls references."
    )
    ap.add_argument("--xlsx", default=DEFAULT_GRP_PATH,
                    help=f"path to GRP Costings xlsx (default: {DEFAULT_GRP_PATH})")
    ap.add_argument("--out", default="scan_formula_references.csv",
                    help="output CSV path (default: %(default)s)")
    ap.add_argument("--sheet", help="restrict to a single sheet name")
    args = ap.parse_args()

    xlsx_path = Path(args.xlsx)
    if not xlsx_path.exists():
        sys.exit(f"Workbook not found: {xlsx_path}")

    print(f"Source: {xlsx_path}")
    try:
        result = scan_workbook(xlsx_path, only_sheet=args.sheet)
    except ValueError as e:
        sys.exit(str(e))

    print(f"FORMULAS 2018 external link IDs: {result['formulas_link_ids']}")
    for s in result["sheets"]:
        print(f"  {s['name']:<48s} {s['linked_count']:>4} ref(s)")
    if result["skipped_sheets"]:
        print(f"\nSkipped sheets: {', '.join(result['skipped_sheets'])}")

    out_path = Path(args.out).resolve()
    _write_csv(out_path, result["linked"])
    print(f"\nWrote {len(result['linked'])} rows to {out_path}")

    if result["linked"]:
        by_ref_sheet: dict[str, int] = {}
        for r in result["linked"]:
            by_ref_sheet[r["ref_sheet"]] = by_ref_sheet.get(r["ref_sheet"], 0) + 1
        print("\nReferences by FORMULAS 2018 sheet:")
        for sheet, n in sorted(by_ref_sheet.items(), key=lambda x: -x[1]):
            print(f"  {sheet:<35s} {n:>4}")


if __name__ == "__main__":
    main()
