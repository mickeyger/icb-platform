"""
tools/preview_grp_import.py

Phase B preview script. Runs the new app.excel_grp_importer.discover()
against a chosen sheet of the GRP Costings workbook and prints the
resulting WritePlan — every body option, every section, every BOM line,
and every warning — without writing anything to the DB.

Usage:
    python tools/preview_grp_import.py
    python tools/preview_grp_import.py --sheet "RIGID DRY FREIGHT"
    python tools/preview_grp_import.py --sheet "..." --csv lines.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

# Make `app` importable from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.excel_grp_importer import discover, WritePlan, BomLine

DEFAULT_XLSX = (
    r"C:\Users\micge\Documents\Burt Costing Model"
    r"\Latest price list\GRP Costings 2018.xlsx"
)
DEFAULT_SHEET = "RIGID DRY FREIGHT"


def _bold(s):  return f"\033[1m{s}\033[0m"
def _green(s): return f"\033[92m{s}\033[0m"
def _red(s):   return f"\033[91m{s}\033[0m"
def _amber(s): return f"\033[93m{s}\033[0m"
def _dim(s):   return f"\033[90m{s}\033[0m"
def _cyan(s):  return f"\033[96m{s}\033[0m"


def _kind_color(k: str) -> str:
    return {
        "literal":                _green,
        "external_formulas_2018": _cyan,
        "external_other":         _amber,
        "aggregate":              _amber,
        "if_condition":           _cyan,
        "expression":             _amber,
        "empty":                  _dim,
        "unresolved":             _red,
    }.get(k, lambda x: x)(k)


def render(plan: WritePlan) -> None:
    print(_bold(f"\n=== Plan for sheet {plan.sheet_name!r} (trailer: {plan.trailer_name!r}) ==="))
    print(f"Source: {plan.source_path}")
    if plan.dimensions:
        dims = ", ".join(f"{k}={v}" for k, v in plan.dimensions.items())
        print(f"Dimensions:    {dims}")
    if plan.default_margin is not None:
        print(f"Margin (G4):   {plan.default_margin}")
    if plan.default_ratio is not None:
        print(f"Ratio  (G8):   {plan.default_ratio}")
    if plan.grand_total_excel is not None:
        print(f"Grand total (Excel cached): R {plan.grand_total_excel:,.2f}")
    print()

    # ── Body options ──
    print(_bold(f"BODY OPTIONS ({len(plan.body_options)})"))
    for opt in plan.body_options:
        default = _green("Y") if opt.default_yn else _dim("N")
        qty = f"  qty={opt.quantity}" if opt.quantity is not None else ""
        print(f"  {opt.source_addr:<5} {default}  {opt.name}{qty}")
    print()

    # ── Sections ──
    print(_bold(f"SECTIONS ({len(plan.sections)})"))
    for sec in plan.sections:
        master = (f"  master: {_cyan(sec.master_option)}" if sec.master_option else "")
        mult   = (f"  ×{sec.j_multiplier}" if sec.j_multiplier else "")
        total  = (f"  TOTAL row R{sec.total_row}" if sec.total_row else _dim("  (no TOTAL row)"))
        n_lines = sum(1 for l in plan.bom_lines if l.section == sec.name)
        print(f"  R{sec.header_row:>4} {sec.name:<30}  {n_lines} item(s){master}{mult}{total}")
    print()

    # ── BOM lines (grouped by section) ──
    print(_bold(f"BOM LINES ({len(plan.bom_lines)})"))
    by_section: dict[str, list[BomLine]] = {}
    for line in plan.bom_lines:
        by_section.setdefault(line.section, []).append(line)
    for sec_name, lines in by_section.items():
        print(_dim(f"  ── {sec_name} ──"))
        for ln in lines:
            kind = _kind_color(ln.price_kind)
            ref = ""
            if ln.price_ref_cell:
                ref = f"  ref={ln.price_ref_sheet}!{ln.price_ref_cell}"
            elif ln.price_value is not None:
                ref = f"  value={ln.price_value}"
            elif ln.price_fallback is not None:
                ref = f"  fallback={ln.price_fallback}"
            gate = ""
            if ln.gate_option_name:
                tag = "[inh]" if ln.inherited_from_section else "[row]"
                gate = f"  gate={ln.gate_option_name} {_dim(tag)}"
            print(f"    {ln.source_addr:<5} {ln.item_name[:34]:<34}  qty={ln.qty_formula[:36]:<36}  {kind:<22}{ref}{gate}")
    print()

    # ── Warnings ──
    if plan.warnings:
        print(_amber(_bold(f"WARNINGS ({len(plan.warnings)})")))
        for w in plan.warnings:
            cell = f" [{w.cell}]" if w.cell else ""
            print(f"  ⚠ {w.code}{cell}: {w.message}")
        print()
    if plan.errors:
        print(_red(_bold(f"ERRORS ({len(plan.errors)})")))
        for e in plan.errors:
            cell = f" [{e.cell}]" if e.cell else ""
            print(f"  ✕ {e.code}{cell}: {e.message}")
        print()

    # ── Summary ──
    n_set = sum(1 for o in plan.body_options if o.default_yn)
    by_kind: dict[str, int] = {}
    for ln in plan.bom_lines:
        by_kind[ln.price_kind] = by_kind.get(ln.price_kind, 0) + 1
    print(_bold("Summary"))
    print(f"  Body options:        {len(plan.body_options)} ({n_set} default-Y)")
    print(f"  Sections:            {len(plan.sections)} ({sum(1 for s in plan.sections if s.master_option)} gated)")
    print(f"  BOM lines:           {len(plan.bom_lines)}")
    for k, n in sorted(by_kind.items(), key=lambda x: -x[1]):
        print(f"    · {_kind_color(k):<22}  {n}")
    print(f"  Warnings: {len(plan.warnings)}   Errors: {len(plan.errors)}")


def write_csv(plan: WritePlan, path: Path) -> None:
    fields = [
        "section", "source_addr", "item_name", "qty_formula", "qty_source_cell",
        "price_kind", "price_value", "price_fallback",
        "price_ref_sheet", "price_ref_cell", "price_raw_formula",
        "gate_option_name", "inherited_from_section",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for ln in plan.bom_lines:
            w.writerow({k: getattr(ln, k) for k in fields})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--xlsx",  default=DEFAULT_XLSX)
    ap.add_argument("--sheet", default=DEFAULT_SHEET)
    ap.add_argument("--trailer-name", default=None,
                    help="override the trailer-template name (default: sheet name)")
    ap.add_argument("--csv", default=None,
                    help="also write the BOM lines to this CSV path")
    args = ap.parse_args()

    if not Path(args.xlsx).exists():
        print(_red(f"Workbook not found: {args.xlsx}"))
        return 2
    plan = discover(args.xlsx, args.sheet, trailer_name_override=args.trailer_name)
    render(plan)
    if args.csv:
        write_csv(plan, Path(args.csv))
        print(f"\nWrote {len(plan.bom_lines)} lines to {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
