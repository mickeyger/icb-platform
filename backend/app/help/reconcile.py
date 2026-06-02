"""Reconcile an attached Excel workbook against a live in-app costing.

Used by the AI Help assistant. Reuses the importer's `parse_sheet` for the
Excel side (so the workbook layout assumptions stay in one place) and the
calculator's already-computed result dict (matching `calculate_bom`'s output)
for the live side.

The output is a structured JSON-serialisable report that the assistant
narrates verbatim — it is told never to invent numbers and to cite the deltas
from this report.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from difflib import SequenceMatcher
from typing import Any, Iterable

from ..excel_importer import parse_sheet, ParsedSheet, ParsedItem

logger = logging.getLogger("burtcost.help.reconcile")

# Rounding threshold below which a delta is treated as "0" (matches the
# convention in bom_snapshots.py).
EPSILON = 0.01

# A section / line item is considered "inactive" on the Excel side when its
# column-J total is at or below this threshold. Picks up SRD/DRD sections when
# the user hasn't selected those body options, and individual door-variant
# lines where the user picked DRD EPS but not DRD PU (or vice versa — the
# unselected variant's column J cell sits at 0).
INACTIVE_TOTAL_THRESHOLD = 0.01

# Hard caps on report size — keeps token cost predictable.
MAX_LINES_PER_SECTION = 40
MAX_ONLY_PER_SIDE = 25

# Body-name → sheet-name fuzzy match threshold (0..1). Below this, we don't
# auto-pick; the UI shows the dropdown instead.
SHEET_AUTO_PICK_THRESHOLD = 0.55


# ── Public API ────────────────────────────────────────────────────────────────


def list_sheets(workbook_path: str) -> list[str]:
    """Return the sheet names in the workbook. Used by the attachment endpoint
    to populate the chip's dropdown. Thin wrapper around openpyxl so callers
    don't have to import it directly."""
    import openpyxl
    wb = openpyxl.load_workbook(workbook_path, data_only=True, read_only=True)
    try:
        return list(wb.sheetnames)
    finally:
        wb.close()


def pick_sheet_for_body(sheets: list[str], body_name: str | None) -> str | None:
    """Return the best-matching sheet name for the given body, or None if
    nothing is close enough. The UI falls back to a dropdown when this returns
    None."""
    if not sheets:
        return None
    if not body_name:
        return sheets[0]
    norm = _normalise(body_name)
    best, best_score = None, 0.0
    for s in sheets:
        score = SequenceMatcher(None, _normalise(s), norm).ratio()
        # Also reward containment in either direction
        if _normalise(s) in norm or norm in _normalise(s):
            score = max(score, 0.85)
        if score > best_score:
            best, best_score = s, score
    if best_score >= SHEET_AUTO_PICK_THRESHOLD:
        return best
    return sheets[0]  # fall back to first sheet; UI exposes the dropdown


def build_reconciliation(workbook_path: str,
                         sheet_name: str,
                         live_result: dict | None,
                         live_body_name: str | None = None) -> dict:
    """Compute the reconciliation report. Never raises — returns an `error`
    key on the dict if something fails so the assistant can surface it.

    Args:
        workbook_path: absolute path to the user-uploaded workbook.
        sheet_name: which sheet inside it to compare.
        live_result: the calculator's last-computed result (matches
            `calculate_bom`'s output: items[], category_totals, grand_total,
            geometry, ...). May be None if the user hasn't run a costing yet.
        live_body_name: optional body-template name to include in the report.
    """
    # Tolerant sheet lookup: openpyxl is whitespace/case-sensitive, but the chip
    # in the UI or a stale localStorage value may have drifted from the canonical
    # name in the file. Try an exact match first; if that fails, try a
    # whitespace-collapsed + case-insensitive match against the workbook's real
    # sheet names. Only if NOTHING matches do we surface an error — and we
    # include the actual available sheet names so the assistant can suggest one.
    try:
        available_sheets = list_sheets(workbook_path)
    except Exception as e:  # noqa: BLE001
        logger.exception("list_sheets failed for %s", workbook_path)
        return {"error": "workbook_unreadable",
                "message": f"Couldn't open the attached workbook: {str(e)[:200]}"}

    canonical = sheet_name
    if sheet_name not in available_sheets:
        target = _normalise(sheet_name)
        canonical = next(
            (s for s in available_sheets if _normalise(s) == target),
            None,
        )
        if canonical is None:
            # Last-ditch: fuzzy pick using the same matcher the chip uses.
            fuzzy = pick_sheet_for_body(available_sheets, sheet_name)
            if fuzzy and SequenceMatcher(
                None, _normalise(fuzzy), _normalise(sheet_name)
            ).ratio() >= 0.75:
                canonical = fuzzy
        if canonical is None:
            return {
                "error": "sheet_not_found",
                "sheet": sheet_name,
                "available_sheets": available_sheets,
                "message": (
                    f"The attached workbook has no sheet exactly named "
                    f"'{sheet_name}'. The sheets it does have are: "
                    + ", ".join(f"'{s}'" for s in available_sheets)
                    + ". Ask the user to pick the right one from the chip's "
                    "dropdown above the chat input."
                ),
            }
        logger.info(
            "reconcile: resolved sheet %r to canonical %r", sheet_name, canonical
        )

    try:
        parsed = parse_sheet(canonical, workbook_path)
    except Exception as e:  # noqa: BLE001
        logger.exception("parse_sheet failed for %s", canonical)
        return {"error": "parse_failed",
                "message": f"Couldn't read sheet '{canonical}': {str(e)[:200]}",
                "available_sheets": available_sheets}

    excel_side = _flatten_excel(parsed)
    live_side = _flatten_live(live_result)

    by_section = _diff_sections(excel_side, live_side)

    excel_grand = parsed.grand_total_excel if parsed.grand_total_excel is not None else parsed.computed_total
    live_grand = (live_result or {}).get("grand_total")

    delta = None
    if excel_grand is not None and live_grand is not None:
        delta = round(float(live_grand) - float(excel_grand), 2)

    # Sum the per-section rounding drift so the assistant / panel can say how
    # much of the grand-total gap is pure rounding noise vs a real difference.
    rounding_drift_total = round(
        sum(s.get("rounding_drift") or 0.0 for s in by_section), 2
    )

    warnings = _gather_warnings(parsed, live_result)

    # Match quality: how many of each side's line items found a partner
    matched_count = sum(len(s["matched"]) for s in by_section)
    excel_total_lines = sum(1 for _ in _iter_excel_lines(excel_side))
    live_total_lines = sum(1 for _ in _iter_live_lines(live_side))
    denom = max(excel_total_lines, live_total_lines, 1)
    match_quality = round(matched_count / denom, 2)

    return {
        "sheet_name": parsed.sheet_name,
        "summary": {
            "excel_grand_total": _r(excel_grand),
            "live_grand_total":  _r(live_grand),
            "delta":             delta,
            "delta_pct":         _delta_pct(delta, excel_grand),
            "rounding_drift_total": rounding_drift_total,
            "match_quality":     match_quality,
            "excel_dims": {
                "length": parsed.length,
                "width":  parsed.width,
                "height": parsed.height,
            },
            "live_dims":  ((live_result or {}).get("geometry") or {}),
            "excel_markup": parsed.markup,
            "live_body":    live_body_name,
        },
        "by_section": by_section,
        "warnings":   warnings,
    }


# ── Internals ─────────────────────────────────────────────────────────────────


def _normalise(s: str | None) -> str:
    if not s:
        return ""
    # Collapse whitespace, uppercase, strip non-alnum for fuzzy matching.
    return " ".join(str(s).upper().split())


def _normalise_strict(s: str | None) -> str:
    """Stricter normalisation used as the matching key."""
    n = _normalise(s)
    # Drop common decorative suffixes/prefixes that often differ between
    # Excel and app rows ("(WHITE)" etc.). Keep digits + letters + spaces.
    out = []
    for ch in n:
        if ch.isalnum() or ch == " ":
            out.append(ch)
    return " ".join("".join(out).split())


def _r(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _delta_pct(delta: float | None, base: Any) -> float | None:
    if delta is None or base in (None, 0):
        return None
    try:
        return round((delta / float(base)) * 100.0, 2)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _flatten_excel(parsed: ParsedSheet) -> dict[str, dict[str, Any]]:
    """Section name -> {items: [...], total: float, multiplier: float}.
    Items are dicts with normalised matching keys.

    Inactive sections (J-total ~= 0) are excluded entirely — they correspond
    to body options the user did not select in this Excel workbook (e.g. SRD,
    DRD sections, or DOOR FITTINGS for the unselected door type). Inside an
    active section, individual line items with a zero/blank Excel total are
    also dropped: in the GRP costing sheet a 0 in column J means that row is
    not contributing (commonly the unselected door-insulation variant — the
    "Y" in column D activates one variant, the others go to 0)."""
    out: dict[str, dict[str, Any]] = {}
    for sec in parsed.sections:
        # Section-level filter
        if sec.excel_total is None or abs(float(sec.excel_total)) <= INACTIVE_TOTAL_THRESHOLD:
            continue
        # Section multiplier (e.g. SIDES: =SUM(Hxx:Hyy)*2 → multiplier=2).
        # Per-item Excel totals come from column H — they are the per-side
        # value BEFORE the ×N multiplier. The live calculator's line_cost is
        # already the total-for-the-trailer (multiplier applied). Apply the
        # multiplier here so per-line comparisons line up like-for-like.
        # Quantity gets the same treatment; unit_price stays per-unit.
        try:
            mult = float(sec.multiplier) if sec.multiplier else 1.0
        except (TypeError, ValueError):
            mult = 1.0
        if mult <= 0:
            mult = 1.0
        rows: list[dict[str, Any]] = []
        for it in sec.items:
            if not it.is_enabled:
                continue
            qty = it.qty
            unit = it.unit_price
            total = it.excel_total
            # Excel sometimes leaves total blank — derive from qty*unit if possible
            if total is None and qty is not None and unit is not None:
                try:
                    total = float(qty) * float(unit)
                except (TypeError, ValueError):
                    total = None
            # Item-level filter: drop zero/blank totals (inactive door variants etc.)
            if total is None or abs(float(total)) <= INACTIVE_TOTAL_THRESHOLD:
                continue
            # Apply section multiplier to totals + qty so per-line numbers
            # match the calculator's per-trailer values.
            if mult != 1.0:
                try:
                    total = float(total) * mult
                    if qty is not None:
                        qty = float(qty) * mult
                except (TypeError, ValueError):
                    pass
            rows.append({
                "name":             it.name,
                "match_key":        _normalise_strict(it.name),
                "qty":              _r(qty),
                "unit_price":       _r(unit),
                "total":            _r(total),
                "excel_formula":    it.excel_formula,
                "symbolic_formula": it.symbolic_formula,
                "source_cell":      it.source_cell,
            })
        # If section had a non-zero total but every row got filtered, still
        # surface the section so the AI can note "we couldn't account for the
        # R X total in section Y". This is rare — usually it means the J total
        # is a literal value rather than a sum of itemised rows.
        out[_normalise(sec.name)] = {
            "display_name": sec.name,
            "items":        rows,
            "total":        _r(sec.excel_total),
            "multiplier":   sec.multiplier,
        }
    return out


def _flatten_live(live_result: dict | None) -> dict[str, dict[str, Any]]:
    """Same shape as _flatten_excel but from the calculator's output.

    Mirrors the Excel-side inactive filter: skip any category whose total is
    zero (the user didn't pick that body option, e.g. SRD/DRD), and skip
    individual line items with zero line_cost (toggled-off optional rows,
    inactive door variants, etc.). Excluded rows are already dropped by the
    calculator engine; this is a belt-and-braces second filter."""
    if not live_result:
        return {}
    by_cat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for it in live_result.get("items", []) or []:
        if it.get("excluded"):
            continue
        line_cost = it.get("line_cost")
        # Item-level filter: drop zero-cost lines so they don't appear as
        # spurious "only_in_live" entries.
        if line_cost is None or abs(float(line_cost)) <= INACTIVE_TOTAL_THRESHOLD:
            continue
        name = it.get("material") or ""
        cat  = it.get("category") or "UNCATEGORISED"
        by_cat[_normalise(cat)].append({
            "name":        name,
            "match_key":   _normalise_strict(name),
            "qty":         _r(it.get("quantity")),
            "unit_price":  _r(it.get("unit_price")),
            "total":       _r(line_cost),
            "app_formula": it.get("formula"),
            "display_cat": cat,
        })
    cat_totals = live_result.get("category_totals") or {}
    out: dict[str, dict[str, Any]] = {}
    for k, rows in by_cat.items():
        display_cat = rows[0]["display_cat"]
        cat_total = cat_totals.get(display_cat)
        # Category-level filter: skip whole categories with zero total (the
        # user did not select this body option). Keep categories whose total
        # is unknown (None) — that just means category_totals wasn't populated
        # but the rows themselves are real.
        if cat_total is not None and abs(float(cat_total)) <= INACTIVE_TOTAL_THRESHOLD:
            continue
        out[k] = {
            "display_name": display_cat,
            "items":        rows,
            "total":        _r(cat_total),
            "multiplier":   1.0,
        }
    return out


def _diff_sections(excel: dict[str, dict[str, Any]],
                   live:  dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-section diffs. Sections appear in the order they're found in the
    Excel sheet, with any live-only sections appended at the end."""
    section_keys: list[str] = list(excel.keys())
    for k in live.keys():
        if k not in excel:
            section_keys.append(k)

    out: list[dict[str, Any]] = []
    for k in section_keys:
        ex_sec   = excel.get(k, {"items": [], "total": None, "display_name": k, "multiplier": 1.0})
        live_sec = live.get(k,  {"items": [], "total": None, "display_name": k, "multiplier": 1.0})

        # FIFO queue match on (match_key)
        live_queue: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in live_sec["items"]:
            live_queue[r["match_key"]].append(r)

        matched: list[dict[str, Any]] = []
        only_in_excel: list[dict[str, Any]] = []
        consumed_live: set[int] = set()

        for ex_row in ex_sec["items"]:
            q = live_queue.get(ex_row["match_key"])
            if q:
                live_row = q.pop(0)
                consumed_live.add(id(live_row))
                pair_delta = _pair_delta(ex_row, live_row)
                cause = _classify_line(ex_row, live_row)
                matched.append({
                    "name":  ex_row["name"],
                    "excel": {"qty": ex_row["qty"], "unit_price": ex_row["unit_price"], "total": ex_row["total"]},
                    "live":  {"qty": live_row["qty"], "unit_price": live_row["unit_price"], "total": live_row["total"]},
                    "delta": pair_delta,
                    "cause": cause,
                    "excel_formula": ex_row.get("excel_formula"),
                    "symbolic_formula": ex_row.get("symbolic_formula"),
                    "app_formula": live_row.get("app_formula"),
                    "source_cell": ex_row.get("source_cell"),
                })
            else:
                only_in_excel.append({
                    "name":  ex_row["name"],
                    "qty":   ex_row["qty"],
                    "unit_price": ex_row["unit_price"],
                    "total": ex_row["total"],
                })

        only_in_live = [
            {"name": r["name"], "qty": r["qty"], "unit_price": r["unit_price"], "total": r["total"]}
            for r in live_sec["items"] if id(r) not in consumed_live
        ]

        # Truncate to caps so the JSON stays small enough for the model.
        truncated_matched = matched[:MAX_LINES_PER_SECTION]
        truncated_excel_only = only_in_excel[:MAX_ONLY_PER_SIDE]
        truncated_live_only  = only_in_live[:MAX_ONLY_PER_SIDE]

        section_delta = None
        if ex_sec["total"] is not None and live_sec["total"] is not None:
            section_delta = round(live_sec["total"] - ex_sec["total"], 2)

        # How much of this section's delta is pure rounding noise (half-up vs
        # banker's) rather than a real cost difference.
        rounding_drift = round(sum(
            m["cause"]["rounding_drift"] or 0.0
            for m in matched
            if m.get("cause", {}).get("cause") == "rounding"
        ), 2)

        out.append({
            "section":          ex_sec["display_name"] or live_sec["display_name"],
            "excel_total":      ex_sec["total"],
            "live_total":       live_sec["total"],
            "delta":            section_delta,
            "rounding_drift":   rounding_drift,
            "excel_multiplier": ex_sec["multiplier"],
            "matched":          truncated_matched,
            "matched_truncated": max(0, len(matched) - len(truncated_matched)),
            "only_in_excel":    truncated_excel_only,
            "only_in_excel_truncated": max(0, len(only_in_excel) - len(truncated_excel_only)),
            "only_in_live":     truncated_live_only,
            "only_in_live_truncated":  max(0, len(only_in_live) - len(truncated_live_only)),
        })
    return out


def _pair_delta(ex: dict, live: dict) -> dict[str, float | None]:
    """Per-line delta in qty / unit_price / total. None means one side is
    missing the value entirely."""
    def diff(a, b):
        if a is None or b is None:
            return None
        d = round(float(b) - float(a), 2)
        return d if abs(d) >= EPSILON else 0.0
    return {
        "qty":        diff(ex.get("qty"),        live.get("qty")),
        "unit_price": diff(ex.get("unit_price"), live.get("unit_price")),
        "total":      diff(ex.get("total"),      live.get("total")),
    }


def _round_half_up(value: float, places: int = 2) -> float:
    """Round with Excel's ROUND() semantics (round-half-AWAY-from-zero), as
    opposed to Python's built-in round() which is banker's rounding
    (round-half-to-even). Used to detect line-total drift that is purely an
    artefact of the two rounding conventions, not a real cost difference."""
    q = Decimal(1).scaleb(-places)  # e.g. Decimal('0.01') for places=2
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))


# Total deltas at or below this (in Rands) with matching qty & unit price are
# treated as rounding noise rather than a real discrepancy. A handful of cents
# is the most a single line can drift from half-up vs half-even rounding.
ROUNDING_DRIFT_CAP = 0.05


def _classify_line(ex: dict, live: dict) -> dict[str, Any]:
    """Explain WHY a matched line's total differs. Returns
    {cause, rounding_drift, note}.

    cause is one of:
      • "match"       — totals agree within EPSILON.
      • "price"       — unit prices differ (the Excel sheet and the app hold
                        different prices for this material).
      • "formula"     — quantities differ (the qty-driving formula diverges).
      • "rounding"    — qty & unit price agree but the total still differs by a
                        few cents: pure half-up vs banker's-rounding drift.
      • "unexplained" — qty & price agree yet the total gap is too large to be
                        rounding. Surfaced so it isn't silently swallowed.

    Operates on the already-rounded report numbers carried on each row; it does
    no I/O and never raises."""
    et, lt = ex.get("total"), live.get("total")
    if et is None or lt is None:
        return {"cause": "unknown", "rounding_drift": None,
                "note": "one side has no line total"}

    total_delta = round(float(lt) - float(et), 2)
    if abs(total_delta) < EPSILON:
        return {"cause": "match", "rounding_drift": 0.0, "note": "totals agree"}

    eu, lu = ex.get("unit_price"), live.get("unit_price")
    eq, lq = ex.get("qty"), live.get("qty")
    price_delta = None if eu is None or lu is None else round(float(lu) - float(eu), 2)
    qty_delta   = None if eq is None or lq is None else round(float(lq) - float(eq), 4)

    if price_delta is not None and abs(price_delta) >= EPSILON:
        return {"cause": "price", "rounding_drift": None,
                "note": f"unit price differs by {price_delta:+.2f}"}

    if qty_delta is not None and abs(qty_delta) >= EPSILON:
        return {"cause": "formula", "rounding_drift": None,
                "note": f"quantity differs by {qty_delta:+g}"}

    # qty & unit price agree but the total still differs. If the gap is within a
    # few cents, prove it's the rounding convention by recomputing qty×price both
    # ways; otherwise flag it as unexplained.
    if eq is not None and (eu is not None or lu is not None) and abs(total_delta) <= ROUNDING_DRIFT_CAP:
        unit = eu if eu is not None else lu
        raw = float(eq) * float(unit)
        half_up = _round_half_up(raw, 2)
        bankers = round(raw, 2)
        return {"cause": "rounding", "rounding_drift": total_delta,
                "note": (f"qty {float(eq):g} × price {float(unit):.2f} = {raw:.4f}; "
                         f"Excel half-up R{half_up:.2f} vs app banker's R{bankers:.2f}")}

    return {"cause": "unexplained", "rounding_drift": None,
            "note": f"total differs by {total_delta:+.2f} with matching qty & price"}


def _gather_warnings(parsed: ParsedSheet, live_result: dict | None) -> list[str]:
    warnings: list[str] = list(parsed.warnings or [])
    if live_result:
        geom = live_result.get("geometry") or {}
        for dim_label, ex_val, live_val in (
            ("length", parsed.length, geom.get("length")),
            ("width",  parsed.width,  geom.get("width")),
            ("height", parsed.height, geom.get("height")),
        ):
            if ex_val is not None and live_val is not None:
                if abs(float(ex_val) - float(live_val)) > 0.01:
                    warnings.append(
                        f"Excel sheet uses {dim_label}={ex_val} but your costing uses "
                        f"{dim_label}={live_val} — totals are not directly comparable."
                    )
        if parsed.markup is not None:
            live_markup = live_result.get("markup_percentage")
            if live_markup is not None and abs(float(parsed.markup) - float(live_markup)) > 0.01:
                warnings.append(
                    f"Excel markup is {parsed.markup}% but your costing uses {live_markup}%."
                )
    if not live_result:
        warnings.append(
            "No live costing on screen yet — run the calculator first, then re-ask."
        )
    return warnings


def _iter_excel_lines(excel: dict) -> Iterable[dict]:
    for sec in excel.values():
        for r in sec["items"]:
            yield r


def _iter_live_lines(live: dict) -> Iterable[dict]:
    for sec in live.values():
        for r in sec["items"]:
            yield r
