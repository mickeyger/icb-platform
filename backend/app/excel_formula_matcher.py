"""
app/excel_formula_matcher.py

Join scan results from app.excel_formula_scanner to existing DB rows:

  • Resolve each external reference (FORMULAS 2018 sheet + cell) to a row in
    skin_formulas / taping_blocks / mounting_cleats / floor_plates via the
    SHEET_MAP cell-lookup tables (mirrors tools/import_formula_links.py).
  • Resolve each Excel sheet name to a TrailerType, with a few aliases.
  • For each scan row, look up the matching BOM row by material name.
  • Return per-row proposal dicts that say what's currently linked and what
    the suggested link would be.

Read-only — no DB writes happen here. The admin UI will display proposals;
writing is handled separately (existing tools/import_formula_links.py).
"""
from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.orm import Session


# ── Cell-to-option lookup tables ───────────────────────────────────────────
# These mirror tools/import_formula_links.py. Keep the two in sync.
#
# Cell positions reflect the FORMULAS 2018.xls layout in the "Latest price
# list" folder (verified 2026-05-09). If a future revision adds rows to
# any of these sheets, run tools/dump_formulas_layout.py to refresh.

_SKIN_TOTALS: dict[str, str] = {
    "D13": "450CSM-450",
    "D25": "600CSM-450",
    "D37": "900CSM-450-0",
    "D49": "INTERNAL LAMINATION",
    "D59": "FINAL COAT",
}
_TAPING_TOTALS: dict[str, str] = {
    "F11": "TAPING BLOCK 200MM",
    "F24": "TAPING BLOCK 250MM",
    "F37": "CHEAP TAPPING BLOCK 200MM",
    "F47": "CHEAP TAPPING BLOCK 250MM",
    "F61": "TIMBER ONLY TAPING BLOCK 200MM",
    "F74": "TIMBER ONLY TAPING BLOCK 250MM",
}
_CLEAT_TOTALS: dict[str, str] = {
    "F10": "TOP MOUNTING CLEAT",
    "F22": "BOTTOM MOUNTING CLEAT",
    "F39": "SPRING MOUNTING CLEAT",
}
_FLOOR_TOTALS: dict[str, str] = {
    "F13": "2MM 3CR12",
    "F24": "3MM ALU BUFFER PLATE",
    "F35": "D-RUBBER",
    "F43": "CORNER GUSSETS",
}

# FORMULAS 2018 sheet name (UPPER) -> (db_table, fk_col_on_bom, totals_map, extras)
SHEET_MAP: dict[str, tuple[str, str, dict[str, str], dict]] = {
    "FORMULA SKINS":   ("skin_formulas",   "skin_formula_id",   _SKIN_TOTALS,
                        {"is_formula_skin": 1, "skin_formula_region": "standard"}),
    "TAPING BLOCKS":   ("taping_blocks",   "taping_block_id",   _TAPING_TOTALS, {}),
    "MOUNTING CLEATS": ("mounting_cleats", "mounting_cleat_id", _CLEAT_TOTALS,  {}),
    "SRD FLOOR PLATE": ("floor_plates",    "floor_plate_id",    _FLOOR_TOTALS,  {}),
}

# Excel sheet name (post-strip) -> trailer_type name (when they don't match).
SHEET_ALIASES: dict[str, str] = {
    "4.9 & UP FREEZER BODY 3": "4.9 & UP FREEZER BODY 2",
}

_FK_COLS = ("skin_formula_id", "taping_block_id", "mounting_cleat_id", "floor_plate_id")


# ── Normalisation ──────────────────────────────────────────────────────────

def _normalize(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).upper()


# ── DB lookups ─────────────────────────────────────────────────────────────

def load_lookup_tables(db: Session) -> dict[str, dict[str, int]]:
    """Return {table: {NAME_UPPER: id}} for the four formula-linked tables."""
    out: dict[str, dict[str, int]] = {}
    for table in ("skin_formulas", "taping_blocks", "mounting_cleats", "floor_plates"):
        rows = db.execute(text(f"SELECT id, name FROM {table}")).fetchall()
        out[table] = {(r[1] or "").strip().upper(): r[0] for r in rows}
    return out


def load_trailer_types(db: Session) -> dict[str, int]:
    """Return {normalized_name: id} for active trailer types."""
    rows = db.execute(text(
        "SELECT id, name FROM trailer_types WHERE name NOT LIKE '%[deleted-%'"
    )).fetchall()
    return {_normalize(name): tid for tid, name in rows}


def load_bom_rows(db: Session, type_id: int) -> list[dict]:
    """BOM rows for a trailer type with FK link state and material name."""
    rows = db.execute(text("""
        SELECT b.id,
               b.skin_formula_id, b.taping_block_id,
               b.mounting_cleat_id, b.floor_plate_id,
               m.name AS material_name,
               b.bom_section
        FROM bill_of_materials b
        LEFT JOIN materials m ON m.id = b.material_id
        WHERE b.trailer_type_id = :tid
    """), {"tid": type_id}).fetchall()
    return [
        {
            "id": r[0],
            "skin_formula_id":   r[1],
            "taping_block_id":   r[2],
            "mounting_cleat_id": r[3],
            "floor_plate_id":    r[4],
            "material_name":     r[5] or "",
            "bom_section":       r[6] or "",
        }
        for r in rows
    ]


def best_bom_match(item_name: str, bom_rows: list[dict]) -> dict | None:
    """Match an Excel item description to a single BOM row.

    Kept for back-compat with anything that wants a single match. Returns
    the first exact match, then a unique containment match. Most callers
    should use all_bom_matches instead so duplicated rows in different
    sections (e.g. DRD vs SRD DOOR FITTINGS) all get linked.
    """
    matches = all_bom_matches(item_name, bom_rows)
    return matches[0] if matches else None


def all_bom_matches(item_name: str, bom_rows: list[dict]) -> list[dict]:
    """Match an Excel item description to all corresponding BOM rows.

    A trailer can carry the same material in multiple BOM sections — for
    example DRD DOOR FITTINGS and SRD DOOR FITTINGS both list 'D-RUBBER'.
    The Excel costing usually shows it once, so the scan needs to fan out
    to every BOM row sharing the name when applying the formula link.

    Strategy:
      1. all exact normalised matches
      2. fall back to a single unambiguous 'contains' match (>=6 chars)
    Returns [] when nothing matches.
    """
    target = _normalize(item_name)
    if not target:
        return []
    exact = [r for r in bom_rows if _normalize(r["material_name"]) == target]
    if exact:
        return exact
    if len(target) >= 6:
        candidates = [
            r for r in bom_rows
            if r["material_name"] and (
                target in _normalize(r["material_name"])
                or _normalize(r["material_name"]) in target
            )
        ]
        if len(candidates) == 1:
            return candidates
    return []


# ── Proposal builder ───────────────────────────────────────────────────────

def build_proposals(scan_result: dict, db: Session) -> dict:
    """Combine a scan result with DB state to produce proposals.

    Each proposal dict:
        body_type, section, item, row, price_col,
        ref_sheet, ref_cell, raw_formula, chain, had_aggregate,
        trailer_type_id, trailer_type_name,
        target_table, target_fk, target_option_id, target_option_name,
        bom_id, bom_material_name, bom_section,
        current_link_id, status, status_reason

    status is one of:
        'set'         — BOM row currently has no link, would set it
        'overwrite'   — link exists but points elsewhere
        'ok'          — link already correct
        'no_trailer'  — Excel sheet has no matching trailer_type
        'unknown_ref' — external ref isn't in SHEET_MAP / DB lookup
        'no_bom_row'  — couldn't match Excel item to a BOM row
    """
    lookup_tables = load_lookup_tables(db)
    trailer_types = load_trailer_types(db)
    bom_cache: dict[int, list[dict]] = {}

    proposals: list[dict] = []

    counts = {
        "set": 0, "overwrite": 0, "ok": 0,
        "no_trailer": 0, "unknown_ref": 0, "no_bom_row": 0,
    }

    for r in scan_result.get("linked", []):
        body_type = r["body_type"]
        ref_sheet = r["ref_sheet"]
        ref_cell  = r["ref_cell"]

        # 1) Resolve external ref to DB row id via SHEET_MAP
        sheet_key = ref_sheet.strip().upper()
        target_table = target_fk = target_option_name = None
        target_option_id = None
        extras: dict = {}
        sm = SHEET_MAP.get(sheet_key)
        if sm:
            target_table, target_fk, totals_map, extras = sm
            target_option_name = totals_map.get(ref_cell)
            if target_option_name:
                target_option_id = lookup_tables.get(target_table, {}).get(
                    target_option_name.upper()
                )

        # 2) Resolve Excel sheet to trailer_type
        alias = SHEET_ALIASES.get(body_type.strip())
        norm = _normalize(alias or body_type)
        type_id = trailer_types.get(norm)
        type_name_for_match = alias or body_type.strip()

        # 3) Match item name to BOM row(s). A material name may appear in
        #    multiple sections of the same trailer (e.g. DRD + SRD DOOR
        #    FITTINGS) — fan out to every row so all of them get linked.
        bom_matches: list[dict] = []
        if type_id is not None:
            if type_id not in bom_cache:
                bom_cache[type_id] = load_bom_rows(db, type_id)
            bom_matches = all_bom_matches(r["item"], bom_cache[type_id])

        # 4) Build one proposal per BOM row (or one no-match proposal when
        #    nothing matched / no trailer / unknown ref).
        if not bom_matches:
            bom_iter: list[dict | None] = [None]
        else:
            bom_iter = list(bom_matches)

        for bom_row in bom_iter:
            status: str
            status_reason = ""
            current_link_id = None
            if type_id is None:
                status = "no_trailer"
                status_reason = f"No trailer_type for sheet '{body_type}'"
                counts["no_trailer"] += 1
            elif not target_option_id or not target_table or not target_fk:
                status = "unknown_ref"
                status_reason = (
                    f"External ref {ref_sheet}!{ref_cell} not in SHEET_MAP"
                    if not sm else
                    f"Cell {ref_cell} on '{ref_sheet}' not in lookup table"
                    if not target_option_name else
                    f"Lookup '{target_option_name}' not present in DB ({target_table})"
                )
                counts["unknown_ref"] += 1
            elif bom_row is None:
                status = "no_bom_row"
                status_reason = f"No BOM row matched item '{r['item']}'"
                counts["no_bom_row"] += 1
            else:
                current_link_id = bom_row.get(target_fk)
                if current_link_id is None:
                    status = "set"
                    counts["set"] += 1
                elif current_link_id == target_option_id:
                    status = "ok"
                    counts["ok"] += 1
                else:
                    status = "overwrite"
                    counts["overwrite"] += 1

            proposals.append({
                "body_type":        body_type,
                "section":          r.get("section", ""),
                "item":             r["item"],
                "row":              r["row"],
                "price_col":        r["price_col"],
                "ref_sheet":        ref_sheet,
                "ref_cell":         ref_cell,
                "raw_formula":      r.get("raw_formula", ""),
                "chain":            r.get("chain", ""),
                "had_aggregate":    bool(r.get("had_aggregate")),
                "trailer_type_id":  type_id,
                "trailer_type_name": type_name_for_match if type_id else None,
                "target_table":     target_table,
                "target_fk":        target_fk,
                "target_option_id": target_option_id,
                "target_option_name": target_option_name,
                "bom_id":           bom_row["id"] if bom_row else None,
                "bom_material_name": bom_row["material_name"] if bom_row else None,
                "bom_section":      bom_row["bom_section"] if bom_row else None,
                "current_link_id":  current_link_id,
                "status":           status,
                "status_reason":    status_reason,
                "extras":           extras,
            })

    return {
        "proposals": proposals,
        "counts":    counts,
        "scan":      {
            "source":            scan_result.get("source"),
            "formulas_link_ids": scan_result.get("formulas_link_ids", []),
            "sheets":            scan_result.get("sheets", []),
            "skipped_sheets":    scan_result.get("skipped_sheets", []),
            "linked_count":      len(scan_result.get("linked", [])),
        },
    }
