"""
tools/dry_run_import.py

Run the v2 parser (app/excel_importer.py) against the configured test
sheets and print a human-readable summary + write a JSON file per sheet.

Usage
-----
    python tools/dry_run_import.py                    # all test sheets
    python tools/dry_run_import.py "SHEET NAME"       # single sheet
"""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

# Force UTF-8 on Windows consoles so box-drawing chars render.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Make `app` importable whether run from repo root or from tools/
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.excel_importer import parse_sheet, parsed_to_dict  # noqa: E402


TEST_SHEETS = [
    "EXPLOSIVE 2.7 TO 4.8",
    "EXPLOSIVE 4.9 AND UP",
    "EXPLOSIVE UP TO 2.7",
    "UP TO 2.3 CHILLER BODY",
]


def format_money(v):
    if v is None:
        return "   —   "
    return f"R{v:,.2f}"


def print_sheet(ps):
    print()
    print("═" * 90)
    print(f"Sheet: {ps.sheet_name}")
    print("═" * 90)
    print(f"  Trailer type hint (E1): {ps.trailer_type_hint}")
    print(f"  Dimensions: L={ps.length}  W={ps.width}  H={ps.height}")
    print(f"  Markup (G5): {ps.markup}")
    print(f"  Constants captured: {len(ps.constants)}")
    if ps.grand_total_cell:
        print(f"  Grand total cell: {ps.grand_total_cell}  "
              f"→ Excel={format_money(ps.grand_total_excel)}  "
              f"Computed={format_money(ps.computed_total)}")
        if ps.grand_total_excel is not None:
            diff = ps.computed_total - ps.grand_total_excel
            pct = (abs(diff) / ps.grand_total_excel * 100) if ps.grand_total_excel else 0
            flag = "✓" if abs(diff) < 0.01 else (f"Δ={format_money(diff)} ({pct:.2f}%)")
            print(f"  Reconciliation: {flag}")
    if ps.skipped_sections:
        print(f"  Skipped sections (zero total): {', '.join(ps.skipped_sections)}")
    if ps.warnings:
        print(f"  Warnings:")
        for w in ps.warnings:
            print(f"    ! {w}")

    print()
    print(f"  {'Section':<30} {'×':>3} {'Excel Total':>14} {'# Items':>8} {'# Skins':>8}")
    print(f"  {'-'*30} {'-'*3} {'-'*14} {'-'*8} {'-'*8}")
    for s in ps.sections:
        skin_count = sum(1 for i in s.items if i.is_formula_skin)
        print(f"  {s.name:<30} {s.multiplier:>3} "
              f"{format_money(s.excel_total):>14} "
              f"{len(s.items):>8} {skin_count:>8}")

    # Show a sample of items with their formulas
    print()
    print("  Sample items (first 2 per section):")
    for s in ps.sections:
        print(f"  ── {s.name} ──")
        for i, item in enumerate(s.items[:2]):
            tag = ""
            if item.is_formula_skin:
                tag = f" [SKIN child of '{item.skin_parent}']"
            print(f"    • {item.name}{tag}")
            print(f"        cell={item.source_cell}  price={item.unit_price}  "
                  f"excel_total={item.excel_total}")
            if item.excel_formula:
                print(f"        excel_formula: {item.excel_formula}")
            print(f"        symbolic:      {item.symbolic_formula}")


def main():
    sheets = sys.argv[1:] if len(sys.argv) > 1 else TEST_SHEETS
    out_dir = REPO_ROOT / "tools" / "dry_run_output"
    out_dir.mkdir(exist_ok=True)

    for sheet in sheets:
        try:
            ps = parse_sheet(sheet)
        except Exception as e:
            print(f"\n!!! Failed to parse {sheet!r}: {e}")
            continue
        print_sheet(ps)
        safe_name = sheet.replace("/", "_").replace(" ", "_").strip("_")
        out_path = out_dir / f"{safe_name}.json"
        out_path.write_text(
            json.dumps(parsed_to_dict(ps), indent=2, default=str),
            encoding="utf-8",
        )
        print(f"\n  → JSON written: {out_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
