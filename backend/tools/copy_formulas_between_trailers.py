"""
tools/copy_formulas_between_trailers.py

Copy BillOfMaterial.formula_expression from a SOURCE trailer template to a
TARGET trailer template, matching rows by (material_name, bom_section).

Built to fix templates that came in with bad formulas from a wonky Excel
import. The default source/target is the user's reported case:
    target: 'RIGID DRY FREIGHT'
    source: '4.9 & UP CHILLER AND 2.5 WIDE'

Default is a dry run — pass --apply to actually write.

Usage:
    python tools/copy_formulas_between_trailers.py
    python tools/copy_formulas_between_trailers.py --apply
    python tools/copy_formulas_between_trailers.py --target "FOO" --source "BAR"
    DATABASE_URL=mysql+pymysql://... python tools/copy_formulas_between_trailers.py --apply
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy import create_engine, text

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass


DEFAULT_TARGET = "RIGID DRY FREIGHT"
DEFAULT_SOURCE = "4.9 & UP CHILLER AND 2.5 WIDE"


def _normalize(s: str | None) -> str:
    return " ".join((s or "").strip().split()).upper()


def _load_bom(engine, trailer_name: str) -> tuple[int, list[dict]]:
    """Return (trailer_type_id, [bom rows]). Rows have id, material_name,
    bom_section, formula_expression."""
    with engine.connect() as c:
        tt = c.execute(text(
            "SELECT id FROM trailer_types WHERE name = :n"
        ), {"n": trailer_name}).fetchone()
        if not tt:
            sys.exit(f"Trailer type not found: {trailer_name!r}")
        tid = tt[0]
        rows = c.execute(text("""
            SELECT b.id, m.name AS material_name,
                   COALESCE(b.bom_section, '') AS bom_section,
                   COALESCE(b.formula_expression, '') AS formula_expression
            FROM bill_of_materials b
            JOIN materials m ON m.id = b.material_id
            WHERE b.trailer_type_id = :tid
            ORDER BY b.bom_section, b.sort_order, b.id
        """), {"tid": tid}).fetchall()
    return tid, [
        {
            "id":                 r[0],
            "material_name":      r[1],
            "bom_section":        r[2],
            "formula_expression": r[3],
        }
        for r in rows
    ]


def _index_by_key(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """Map (NORM_section, NORM_material_name) -> list of rows."""
    out: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        key = (_normalize(r["bom_section"]), _normalize(r["material_name"]))
        out[key].append(r)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", default=DEFAULT_TARGET,
                    help=f"target trailer name (default: {DEFAULT_TARGET!r})")
    ap.add_argument("--source", default=DEFAULT_SOURCE,
                    help=f"source trailer name (default: {DEFAULT_SOURCE!r})")
    ap.add_argument("--db-url", default=None,
                    help="SQLAlchemy URL (default: $DATABASE_URL or sqlite:///costing.db)")
    ap.add_argument("--apply", action="store_true",
                    help="write changes (default: dry run)")
    ap.add_argument("--also-empty", action="store_true",
                    help="also overwrite when target's current formula is empty (default: yes)")
    ap.add_argument("--no-overwrite-equal", action="store_true",
                    help="skip rows where target already matches source (default: yes, skipped)")
    args = ap.parse_args()

    db_url = args.db_url or os.environ.get("DATABASE_URL") or "sqlite:///costing.db"
    print(f"DB:     {db_url}")
    print(f"Source: {args.source!r}")
    print(f"Target: {args.target!r}")
    print(f"Mode:   {'APPLY (writing)' if args.apply else 'DRY RUN'}")
    print()

    engine = create_engine(db_url)

    src_id, src_rows = _load_bom(engine, args.source)
    tgt_id, tgt_rows = _load_bom(engine, args.target)
    print(f"Source has {len(src_rows)} BOM rows (tt_id={src_id})")
    print(f"Target has {len(tgt_rows)} BOM rows (tt_id={tgt_id})")
    print()

    src_index = _index_by_key(src_rows)
    tgt_index = _index_by_key(tgt_rows)

    updates: list[dict] = []   # rows that will change
    same: list[dict] = []      # already matching, skip
    unmatched: list[dict] = [] # no source row by (section, name)
    ambiguous: list[dict] = [] # multi-match where target+source counts differ

    seen_target_ids: set[int] = set()

    for key, tgt_group in tgt_index.items():
        candidates = src_index.get(key, [])
        if not candidates:
            for r in tgt_group:
                unmatched.append(r)
                seen_target_ids.add(r["id"])
            continue

        if len(candidates) == 1 and len(tgt_group) == 1:
            # Plain 1-to-1
            r = tgt_group[0]
            seen_target_ids.add(r["id"])
            new_formula = candidates[0]["formula_expression"] or ""
            old_formula = r["formula_expression"] or ""
            if new_formula == old_formula:
                same.append(r)
            else:
                updates.append({
                    "id":       r["id"], "section": r["bom_section"],
                    "material": r["material_name"], "old": old_formula,
                    "new":      new_formula,
                })
            continue

        # Multi-match: pair target & source by position within the (section,
        # name) group. Both lists are already ordered by sort_order, so the
        # Nth GLUE LINE in target SIDES maps to the Nth GLUE LINE in source
        # SIDES (matches how lamination layers are structured).
        pair_count = min(len(tgt_group), len(candidates))
        for i in range(pair_count):
            r = tgt_group[i]
            src = candidates[i]
            seen_target_ids.add(r["id"])
            new_formula = src["formula_expression"] or ""
            old_formula = r["formula_expression"] or ""
            if new_formula == old_formula:
                same.append(r)
            else:
                updates.append({
                    "id":       r["id"], "section": r["bom_section"],
                    "material": r["material_name"], "old": old_formula,
                    "new":      new_formula,
                    "ordinal":  f"{i+1}/{len(tgt_group)} (source has {len(candidates)})",
                })
        # Any extras (target group longer than source group, or vice-versa)
        # are reported as ambiguous so the user can fix them by hand.
        if len(tgt_group) > pair_count:
            for r in tgt_group[pair_count:]:
                seen_target_ids.add(r["id"])
                ambiguous.append({
                    "target": r,
                    "reason": f"target has {len(tgt_group)} rows for this key, source has only {len(candidates)} — extra target rows skipped",
                })

    # Report
    print("=" * 100)
    print(f"Updates planned : {len(updates)}")
    print(f"Already matching: {len(same)}")
    print(f"Unmatched       : {len(unmatched)}")
    print(f"Ambiguous (>1)  : {len(ambiguous)}")
    print("=" * 100)

    if updates:
        print("\n--- UPDATES ---")
        for u in updates:
            tag = f" (pair {u['ordinal']})" if u.get("ordinal") else ""
            print(f"  bom_id={u['id']:>5} [{u['section']}] {u['material']}{tag}")
            print(f"        OLD: {u['old']!r}")
            print(f"        NEW: {u['new']!r}")

    if unmatched:
        print(f"\n--- UNMATCHED (no source row for these target keys) [{len(unmatched)}] ---")
        for r in unmatched[:30]:
            print(f"  [{r['bom_section']}] {r['material_name']}  (target bom_id={r['id']}, formula={r['formula_expression']!r})")
        if len(unmatched) > 30:
            print(f"  ... +{len(unmatched) - 30} more")

    if ambiguous:
        print(f"\n--- AMBIGUOUS [{len(ambiguous)}] ---")
        for a in ambiguous:
            r = a["target"]
            reason = a.get("reason") or f"{len(a.get('candidates') or [])} source matches; SKIPPED"
            print(f"  target bom_id={r['id']} [{r['bom_section']}] {r['material_name']} — {reason}")

    if not updates:
        print("\nNothing to write.")
        return

    if not args.apply:
        print("\n(dry run — pass --apply to write)")
        return

    with engine.begin() as c:
        for u in updates:
            c.execute(
                text("UPDATE bill_of_materials SET formula_expression = :f WHERE id = :id"),
                {"f": u["new"], "id": u["id"]},
            )
    print(f"\nWrote {len(updates)} updates.")


if __name__ == "__main__":
    main()
