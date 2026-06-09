import asyncio
import json
import logging
import platform
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from ..database import (
    get_db,
    TrailerType, BillOfMaterial, BOMSection,
    CalculationRecord, Customer, Formula, GlobalVariable,
)
from ..deps import get_current_user, user_can
from ..services import (
    _bom_load_options,
    _compute_skin_formula_cost, _compute_taping_block_cost, _compute_floor_plate_cost,
    _compute_mounting_cleat_cost,
    compute_chassis_cost, resolve_report_template, strip_excluded_items,
    get_section_snapshot, get_formula_lib, get_global_vars,
)
from ..templates_config import templates
from ..quote_numbering import assign_quote_number
from app.formula_engine import calculate_bom, evaluate_formula

router = APIRouter()

_approve_lock = asyncio.Lock()


def _attach_formula_debug(result: dict, body_vars: dict, formula_lib: dict,
                          global_vars: dict | None = None) -> None:
    """Attach body_variables, resolved formula-library values, and global variables
    to the result dict so the client tooltip can show substituted expressions."""
    geo = result.get("geometry", {})
    result["body_variables"] = {k: round(float(v), 6) for k, v in body_vars.items()}
    result["global_variables"] = {k: round(float(v), 6) for k, v in (global_vars or {}).items()}
    resolved = {}
    for name, expr in formula_lib.items():
        try:
            resolved[name] = round(evaluate_formula(expr, geo, body_vars, formula_lib), 6)
        except Exception:
            resolved[name] = 0.0
    result["formula_library_resolved"] = resolved


# ─── Calculator page ──────────────────────────────────────────────────────────

@router.get("/calculator", response_class=HTMLResponse)
async def calculator_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login")
    trailers = db.query(TrailerType).filter_by(is_active=True).order_by(TrailerType.name).all()
    return templates.TemplateResponse("calculator.html", {
        "request": request, "user": user, "trailers": trailers,
    })


@router.get("/calculator2", response_class=HTMLResponse)
async def calculator2_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login")
    trailers = db.query(TrailerType).filter_by(is_active=True).order_by(TrailerType.name).all()
    return templates.TemplateResponse("calculator2.html", {
        "request": request, "user": user, "trailers": trailers,
    })


# ─── Core calculation helper ──────────────────────────────────────────────────

def _build_body_variables(bom_rows) -> dict:
    """Map of {material_name -> variable_value} for is_body_option rows.

    Used by the formula engine to resolve {NAME} tokens in BOM formulas.
    Independent of which variant the user has selected — every named variable
    always resolves to its template-defined value.
    """
    out: dict[str, float] = {}
    for row in bom_rows:
        if row.is_body_option and row.variable_value is not None and row.material:
            out[row.material.name] = float(row.variable_value)
    return out


def _apply_body_variable_overrides(body_vars: dict, overrides) -> None:
    """Overlay caller-supplied body-variable values (keyed by material name) onto
    the template-derived map. Used when editing a saved costing so the recompute
    reproduces the quote's insulation thicknesses (EPS/PU) even if the global
    EPS/PU copy-on-switch has since rewritten the BOM's variable_value on disk.
    No-op when overrides is falsy, so normal calculations are unaffected."""
    if not overrides:
        return
    for name, val in overrides.items():
        try:
            body_vars[str(name)] = float(val)
        except (TypeError, ValueError):
            continue


def _eval_bom_conditions(raw_json: str | None, selected_opt_names: set[str]) -> bool:
    """Evaluate a row's per-item bom_conditions against the current selections.

    Returns True if the row should be included, False if it should be excluded.
    NULL/empty conditions = always include.

    Supported JSON shapes (matches the configurator's PATCH endpoint):
      - Legacy list:           [{"option": str, "equals": "Y"|"N"}, ...]   → include_when
      - {"mode":"exclude", "all":[...]}                                    → exclude_when
      - {"mode":"always_exclude"}                                          → never
    """
    if not raw_json:
        return True
    try:
        parsed = json.loads(raw_json)
    except (ValueError, TypeError):
        return True  # malformed → fail-safe to include
    mode = "include"
    items: list = []
    if isinstance(parsed, list):
        items = parsed
    elif isinstance(parsed, dict):
        raw_mode = (parsed.get("mode") or "include").lower()
        if raw_mode == "always_exclude":
            return False
        if raw_mode == "exclude":
            mode = "exclude"
        items = parsed.get("all") or []
    if not items:
        return True  # no conditions = always include
    all_met = True
    for c in items:
        if not isinstance(c, dict):
            continue
        opt = c.get("option") or ""
        eq = (c.get("equals") or "Y").upper()
        is_on = opt in selected_opt_names
        if eq == "Y" and not is_on:
            all_met = False
            break
        if eq == "N" and is_on:
            all_met = False
            break
    return (not all_met) if mode == "exclude" else all_met


def _build_bom_items(bom_rows, dims, overrides, body_opt_sel, db, excluded_categories=None, trailer=None, flag_overrides=None, include_all_items=False, user_excluded_bom_ids=None, optional_sections_enabled=None, formula_overrides=None):
    """Resolve BOM rows into the bom_items list consumed by calculate_bom().

    When `trailer.configurator_v2` is True, additional gating runs on top of the
    legacy DRD/SRD logic:
      - sections with archived_at set are skipped (Unassigned tray)
      - sections owned by a master (body_option_master_id) only render when that
        master is currently selected (top-level FLOOR TYPE-style gates)
      - per-item bom_conditions JSON is evaluated against the active selections

    flag_overrides (optional): dict[str, bool] sent by the calculator's settings-draft
      panel. Keys are flag aliases (label, flagBindingName, master material name); a True
      value means the flag is ON. These names are merged into selected_opt_names so that
      unbound flags (those without a body-option master row) can still gate bom_conditions.
      For bound flags this is redundant (body_opt_sel already covers them) but harmless.
    """
    selected_opt_names: set[str] = set()
    selected_opt_groups: set[str] = set()
    selected_opt_material_ids: set[int] = set()
    selected_master_row_ids: set[int] = set()

    if body_opt_sel:
        for row in bom_rows:
            if row.is_body_option and body_opt_sel.get(str(row.id), False):
                selected_opt_names.add(row.material.name)
                selected_opt_material_ids.add(row.material_id)
                selected_master_row_ids.add(row.id)
                if row.body_option_group:
                    selected_opt_groups.add(row.body_option_group)

    # Merge flag_overrides aliases: the calculator's settings-draft panel sends each
    # flag's label, flagBindingName, and bound-master material name as aliases.  When a
    # flag is ON, all its aliases land in selected_opt_names so that bom_conditions
    # referencing any of those strings resolves correctly.  This is the server-side
    # counterpart to the client-side flagOverridesPayload built in calculator.js.
    if flag_overrides:
        for name, is_on in flag_overrides.items():
            if is_on and name:
                selected_opt_names.add(str(name))

    _snap = get_section_snapshot()
    section_mults_by_id      = _snap.mults_by_id
    section_mults_by_name    = _snap.mults_by_name
    section_optional_by_id   = _snap.optional_by_id
    section_optional_by_name = _snap.optional_by_name
    sections_by_id           = _snap.by_id  # values are SectionRow namedtuples
    use_v2 = bool(trailer and getattr(trailer, "configurator_v2", False))

    # Cross-trailer drift resolver: BOMSection rows are global, but
    # bom_sections.body_option_master_id can end up pointing at a master on
    # a *different* trailer (the row gets set during another trailer's
    # configurator save). For v2 gating to behave consistently per-trailer,
    # we resolve the owning master by NAME within the current trailer when
    # the FK points off-trailer. Build the lookup once.
    local_master_by_name: dict[str, int] = {}
    if use_v2:
        for r in bom_rows:
            if r.is_body_option and r.material and r.material.name:
                local_master_by_name.setdefault(r.material.name, r.id)
    # Cache "trailer 51's local master id for the master whose id is X" — X may
    # be off-trailer; the value is the same-named master id on this trailer
    # (or None if no equivalent exists, which means "don't gate by this FK").
    _resolved_owner_cache: dict[int, int | None] = {}
    def _resolve_owning_master_id(fk_id: int) -> int | None:
        if fk_id in _resolved_owner_cache:
            return _resolved_owner_cache[fk_id]
        m = db.query(BillOfMaterial).filter_by(id=fk_id).first()
        if not m:
            _resolved_owner_cache[fk_id] = None
            return None
        if m.trailer_type_id == (trailer.id if trailer else None):
            _resolved_owner_cache[fk_id] = fk_id
            return fk_id
        # Off-trailer master: look up an equivalently-named master on this trailer.
        name = m.material.name if m.material else None
        resolved = local_master_by_name.get(name) if name else None
        _resolved_owner_cache[fk_id] = resolved
        return resolved

    # Groups that use a master ON/OFF toggle — mirrors _DRDSR_TOGGLE_GROUPS in JS.
    _DRDSR_GROUPS = ('DRD', 'SRD')

    user_excluded_set = {int(x) for x in (user_excluded_bom_ids or []) if str(x).strip().lstrip('-').isdigit()}
    # Per-row formula overrides — used by edit-replay so a saved costing reproduces
    # exactly even when the BOM's formula_expression has since changed (e.g. the
    # EPS/PU insulation copy-on-switch rewrites the inactive side's formula).
    formula_overrides = {str(k): v for k, v in (formula_overrides or {}).items()}
    # Optional sections (is_optional=1, e.g. OPTIONAL EXTRAS) default to OFF. The
    # frontend sends the set of section_ids the user has explicitly opted in;
    # any optional row whose section is not in that set is treated as user-
    # excluded so its line_cost is zeroed and it renders struck-through.
    optional_sections_enabled_set = {
        int(x) for x in (optional_sections_enabled or [])
        if str(x).strip().lstrip('-').isdigit()
    }

    bom_items = []
    for row in bom_rows:
        mat = row.material
        # Calculator 2 mode: bypass all body-option gating. Body-option master rows
        # are toggles, not real costed items, so drop them entirely. Items the user
        # ticked off in the UI ride through as soft-excluded (line_cost = 0).
        if include_all_items:
            if row.is_body_option:
                continue
            _excluded_reason = "Excluded by user" if row.id in user_excluded_set else None
            cat = row.bom_section or (mat.category.name if mat.category else "Uncategorised")
            if excluded_categories and cat in excluded_categories:
                continue
            if row.skin_formula_id and row.skin_formula:
                region = row.skin_formula_region or "standard"
                base_price = _compute_skin_formula_cost(row.skin_formula, region)
            elif row.taping_block_id and row.taping_block:
                base_price = _compute_taping_block_cost(row.taping_block)
            elif row.floor_plate_id and row.floor_plate:
                base_price = _compute_floor_plate_cost(row.floor_plate)
            elif row.mounting_cleat_id and row.mounting_cleat:
                base_price = _compute_mounting_cleat_cost(row.mounting_cleat)
            elif row.unit_price_override is not None:
                base_price = row.unit_price_override
            else:
                base_price = mat.price_per_unit
            price = overrides.get(str(row.id), base_price)
            mult = section_mults_by_id.get(row.bom_section_id) if row.bom_section_id else None
            if mult is None:
                mult = section_mults_by_name.get(cat, 1.0)
            is_opt = section_optional_by_id.get(row.bom_section_id) if row.bom_section_id else None
            if is_opt is None:
                is_opt = section_optional_by_name.get(cat, False)
            if is_opt and _excluded_reason is None:
                sid = row.bom_section_id
                if sid is None or int(sid) not in optional_sections_enabled_set:
                    _excluded_reason = "Optional section not enabled"
            bom_items.append({
                "bom_id":             row.id,
                "material_name":      mat.name,
                "category_name":      cat,
                "bom_section_id":     row.bom_section_id,
                "section_is_optional": bool(is_opt),
                "formula_expression": formula_overrides.get(str(row.id), row.formula_expression),
                "waste_percentage":   row.waste_percentage,
                "price_per_unit":     price,
                "unit_of_measure":    mat.unit_of_measure,
                "material_code":      mat.sap_code or mat.material_code or "",
                "section_multiplier": mult,
                "skin_formula_id":     row.skin_formula_id,
                "skin_formula_name":   row.skin_formula.name if row.skin_formula else None,
                "skin_formula_region": row.skin_formula_region,
                "taping_block_id":     row.taping_block_id,
                "taping_block_name":   row.taping_block.name if row.taping_block else None,
                "floor_plate_id":      row.floor_plate_id,
                "floor_plate_name":    row.floor_plate.name if row.floor_plate else None,
                "mounting_cleat_id":   row.mounting_cleat_id,
                "mounting_cleat_name": row.mounting_cleat.name if row.mounting_cleat else None,
                "excluded":            _excluded_reason is not None,
                "excluded_reason":     _excluded_reason,
            })
            continue

        if row.is_body_option and body_opt_sel:
            if not body_opt_sel.get(str(row.id), False):
                continue
        # v2: body-option masters are pure toggles, never cost-carrying line items.
        # The sections they own are what contributes cost. Drop the master rows
        # from the BOM items list so legacy "BODY OPTIONS" / DRD / SRD masters
        # don't appear in the BOM table or in the cost summary.
        if use_v2 and row.is_body_option:
            continue

        # ── Phase 3: configurator-v2 gating ─────────────────────────────────
        # Only runs for trailers explicitly opted in via the per-trailer flag.
        # Legacy trailers fall through to the DRD/SRD pre-filter below unchanged.
        if use_v2 and not row.is_body_option:
            sec = sections_by_id.get(row.bom_section_id) if row.bom_section_id else None
            if sec is not None:
                # 1) Unassigned tray — section is parked, exclude its items.
                if sec.archived_at is not None:
                    continue
                # 2) Top-level gate ownership — section's master must be selected.
                #    Resolve the stored FK to a local trailer master by name —
                #    sections are global and the FK can point off-trailer.
                if sec.body_option_master_id:
                    owner_id = _resolve_owning_master_id(sec.body_option_master_id)
                    # owner_id == None means the owning master has no local
                    # equivalent on this trailer → no gate to enforce, include.
                    if owner_id is not None and owner_id not in selected_master_row_ids:
                        continue
            # 3) Per-item bom_conditions JSON (include/exclude/always_exclude).
            #    When a condition fails, the item is "excluded" — we still pass
            #    it to the BOM as a struck-through line so the user can see
            #    what *would* render if they toggled the relevant flag.
            _excluded_reason = None
            if not _eval_bom_conditions(row.bom_conditions, selected_opt_names):
                _excluded_reason = _describe_failed_condition(row.bom_conditions, selected_opt_names)
        else:
            _excluded_reason = None

        # Section-level DRD/SRD pre-filter (runs BEFORE per-line gates) —
        # mirrors the same fix in calculator.js getBomWithSelectedOptions.
        # When a row lives in a "DRD …" or "SRD …" section, the section's
        # master toggle must be ON regardless of any per-line
        # body_option_linked. Workbook semantics require BOTH section
        # master AND per-line gates to be true; without this pre-filter,
        # an SRD-section line gated by a shared option (e.g. BAKERY BODY)
        # leaks into the BOM when DRD is selected.
        #
        # When configurator_v2 is on, this pre-filter is SKIPPED because the
        # new model's body_option_master_id gating is authoritative — running
        # both would double-filter and require the user to select two distinct
        # masters (legacy DRD + configurator-created DRD) for the same content.
        if not use_v2 and body_opt_sel and not row.is_body_option:
            sec_upper = (row.bom_section or "").upper()
            blocked_by_section = any(
                sec_upper.startswith(grp) and grp not in selected_opt_groups
                for grp in _DRDSR_GROUPS
            )
            if blocked_by_section:
                continue

        # Legacy per-item body_option_linked gate.
        # When configurator_v2 is on, the configurator's bom_conditions JSON is
        # the authoritative per-item rule and this legacy check would double-filter
        # (the legacy gate isn't visible in the configurator UI, so an item the
        # user marked as "always include" would still be hidden by a stale linked
        # value). Skip it for v2 trailers.
        if not use_v2 and (row.body_option_linked_id is not None or row.body_option_linked) and body_opt_sel:
            matched = False
            if row.body_option_linked_id is not None:
                matched = row.body_option_linked_id in selected_opt_material_ids
            if not matched and row.body_option_linked:
                matched = (row.body_option_linked in selected_opt_names
                           or row.body_option_linked in selected_opt_groups)
            if not matched:
                continue
        elif not use_v2 and body_opt_sel and not row.is_body_option:
            # Implicit section gate (kept for clarity — the pre-filter
            # above already handles this for rows without per-line link).
            # Skipped for v2 trailers — the new master-ownership check above
            # is authoritative.
            sec_upper = (row.bom_section or "").upper()
            _skip = False
            for grp in _DRDSR_GROUPS:
                if sec_upper.startswith(grp):
                    _skip = grp not in selected_opt_groups
                    break
            if _skip:
                continue
        cat = row.bom_section or (mat.category.name if mat.category else "Uncategorised")
        if excluded_categories and cat in excluded_categories:
            continue
        if row.skin_formula_id and row.skin_formula:
            region = row.skin_formula_region or "standard"
            base_price = _compute_skin_formula_cost(row.skin_formula, region)
        elif row.taping_block_id and row.taping_block:
            base_price = _compute_taping_block_cost(row.taping_block)
        elif row.floor_plate_id and row.floor_plate:
            base_price = _compute_floor_plate_cost(row.floor_plate)
        elif row.mounting_cleat_id and row.mounting_cleat:
            base_price = _compute_mounting_cleat_cost(row.mounting_cleat)
        elif row.unit_price_override is not None:
            base_price = row.unit_price_override
        else:
            base_price = mat.price_per_unit
        price = overrides.get(str(row.id), base_price)
        mult = section_mults_by_id.get(row.bom_section_id) if row.bom_section_id else None
        if mult is None:
            mult = section_mults_by_name.get(cat, 1.0)
        is_opt = section_optional_by_id.get(row.bom_section_id) if row.bom_section_id else None
        if is_opt is None:
            is_opt = section_optional_by_name.get(cat, False)
        # Honour the optional-section / per-row excludes coming from the
        # client (Costings 1 sends them for items in EXTRAS / OPTIONAL EXTRAS).
        # If a condition already excluded the row, keep that reason; otherwise
        # mark it as user-excluded so the row renders struck-through and the
        # cost engine zeroes its line_cost.
        if row.id in user_excluded_set and _excluded_reason is None:
            _excluded_reason = "Excluded by user"
        if is_opt and _excluded_reason is None:
            sid = row.bom_section_id
            if sid is None or int(sid) not in optional_sections_enabled_set:
                _excluded_reason = "Optional section not enabled"
        bom_items.append({
            "bom_id":             row.id,
            "material_name":      mat.name,
            "category_name":      cat,
            "bom_section_id":     row.bom_section_id,
            "section_is_optional": bool(is_opt),
            "formula_expression": row.formula_expression,
            "waste_percentage":   row.waste_percentage,
            "price_per_unit":     price,
            "unit_of_measure":    mat.unit_of_measure,
            "material_code":      mat.sap_code or mat.material_code or "",
            "section_multiplier": mult,
            "skin_formula_id":     row.skin_formula_id,
            "skin_formula_name":   row.skin_formula.name if row.skin_formula else None,
            "skin_formula_region": row.skin_formula_region,
            "taping_block_id":     row.taping_block_id,
            "taping_block_name":   row.taping_block.name if row.taping_block else None,
            "floor_plate_id":      row.floor_plate_id,
            "floor_plate_name":    row.floor_plate.name if row.floor_plate else None,
            "mounting_cleat_id":   row.mounting_cleat_id,
            "mounting_cleat_name": row.mounting_cleat.name if row.mounting_cleat else None,
            # Soft-excluded items (v2 only): condition rule failed. The line
            # ships in the response so the UI can render it struck-through;
            # calculate_bom skips its cost math (qty / line_cost forced to 0).
            "excluded":            _excluded_reason is not None,
            "excluded_reason":     _excluded_reason,
        })
    return bom_items


def _describe_failed_condition(raw_json, selected_opt_names: set[str]) -> str | None:
    """Produce a short human-readable reason a bom_conditions check returned
    False, for the "show hidden lines" tooltip on the costings page.

    Examples:
      "FRONT PU = Y"   (include rule, FRONT PU not selected)
      "[exclude] BAKERY = Y"
      "always excluded"
    """
    import json as _json
    if not raw_json:
        return None
    try:
        parsed = _json.loads(raw_json)
    except (ValueError, TypeError):
        return None
    mode = "include"
    items = []
    if isinstance(parsed, list):
        items = parsed
    elif isinstance(parsed, dict):
        m = (parsed.get("mode") or "include").lower()
        if m == "always_exclude":
            return "always excluded"
        if m == "exclude":
            mode = "exclude"
        items = parsed.get("all") or []
    if not items:
        return None
    for c in items:
        if not isinstance(c, dict):
            continue
        opt = c.get("option") or ""
        eq = (c.get("equals") or "Y").upper()
        is_on = opt in selected_opt_names
        # For include rules: fail when an opt expected Y is off, or expected N is on.
        # For exclude rules: fail when the matched conjunction is true (item excluded).
        if mode == "include":
            if (eq == "Y" and not is_on) or (eq == "N" and is_on):
                return f"{opt} = {eq}"
        else:  # exclude
            if (eq == "Y" and is_on) or (eq == "N" and not is_on):
                return f"[exclude] {opt} = {eq}"
    return None


def _apply_chassis_and_margin(result, body, db):
    chassis_sel = body.get("chassis") or {}
    if chassis_sel.get("enabled"):
        chassis = compute_chassis_cost(db, chassis_sel)
        result["chassis"] = chassis
        result["materials_total"] = result["grand_total"]
        result["grand_total"] = round(result["grand_total"] + chassis["subtotal"], 2)

    grand_total = float(result.get("grand_total", 0) or 0)

    profit_margin = float(body.get("profit_margin", 0) or 0)
    profit_amount = 0.0
    if profit_margin > 0:
        profit_amount = round(grand_total * profit_margin / 100, 2)
        result["profit_amount"] = profit_amount
        result["profit_margin"] = profit_margin

    with_margin = grand_total + profit_amount

    # Ratio is a divisor in (0, 1] (e.g. 0.95 = 95%). Selling price = with_margin / ratio.
    try:
        ratio_value = float(body.get("ratio_value")) if body.get("ratio_value") is not None else None
    except (TypeError, ValueError):
        ratio_value = None
    ratio_label = body.get("ratio_label") or None

    selling_price = with_margin
    ratio_amount = 0.0
    if ratio_value and 0 < ratio_value <= 1:
        selling_price = round(with_margin / ratio_value, 2)
        ratio_amount = round(selling_price - with_margin, 2)
        result["ratio_value"] = ratio_value
        result["ratio_label"] = ratio_label or f"{round(ratio_value * 100, 1)}%"
        result["ratio_amount"] = ratio_amount

    if profit_margin > 0 or ratio_amount > 0:
        result["selling_price"] = round(selling_price, 2)

    return result


def _apply_discount(result, body):
    """Apply an optional discount to the Total Cost (selling price). Sets
    discount_kind / discount_input / discount_amount and net_total on the result.
    A percent discount is clamped to 0–100; a flat amount is clamped to the total.
    net_total is ALWAYS set (= the final headline figure) so callers can read one
    field. No discount → kind/input NULL, discount_amount 0, net_total == total."""
    base = float(result.get("selling_price") or result.get("grand_total") or 0)
    kind = (body.get("discount_kind") or "").strip().lower()
    try:
        raw = float(body.get("discount_input") or 0)
    except (TypeError, ValueError):
        raw = 0.0
    discount_amount = 0.0
    if kind == "percent" and raw > 0:
        discount_amount = round(base * min(max(raw, 0.0), 100.0) / 100.0, 2)
    elif kind == "amount" and raw > 0:
        discount_amount = round(min(raw, base), 2)
    else:
        kind, raw = None, 0.0
    result["discount_kind"]   = kind
    result["discount_input"]  = raw if kind else None
    result["discount_amount"] = discount_amount
    result["net_total"]       = round(base - discount_amount, 2)
    return result


# ─── Calculate ───────────────────────────────────────────────────────────────

@router.post("/api/calculate")
async def api_calculate(request: Request, db: Session = Depends(get_db)):
    import time as _time
    _stages: dict[str, float] = {}
    def _mark(stage: str, started: float) -> float:
        now = _time.monotonic()
        _stages[stage] = round((now - started) * 1000.0, 1)
        return now

    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401)
    body = await request.json()
    trailer_id = body.get("trailer_type_id")

    _t = _time.monotonic()
    tt = db.query(TrailerType).filter_by(id=trailer_id).first()
    if not tt:
        raise HTTPException(status_code=404, detail="Trailer type not found")
    _t_tt = _time.monotonic()
    _stages["tt_query_ms"] = round((_t_tt - _t) * 1000.0, 1)

    bom_rows = (db.query(BillOfMaterial)
                .filter_by(trailer_type_id=trailer_id)
                .options(*_bom_load_options()).all())
    _t_q = _time.monotonic()
    _stages["bom_query_ms"]  = round((_t_q  - _t_tt) * 1000.0, 1)
    _stages["bom_row_count"] = len(bom_rows)

    section_order = get_section_snapshot().order
    def _sec_key(r):
        name = r.bom_section or (r.material.category.name if r.material and r.material.category else "")
        return (section_order.get(name, 99998), name.lower(), r.material.name.lower() if r.material else "")
    bom_rows.sort(key=_sec_key)
    _t = _mark("bom_load_ms", _t)

    overrides    = {str(k): float(v) for k, v in body.get("overrides", {}).items()}
    body_opt_sel = {str(k): bool(v) for k, v in body.get("body_option_selections", {}).items()}
    excluded_cats = body.get("excluded_categories") or []
    flag_overrides = {str(k): bool(v) for k, v in (body.get("flag_overrides") or {}).items()}
    include_all_items = bool(body.get("include_all_items"))
    user_excluded_bom_ids = body.get("user_excluded_bom_ids") or []
    optional_sections_enabled = body.get("optional_sections_enabled") or []

    bom_items = _build_bom_items(bom_rows, body.get("dimensions", {}), overrides, body_opt_sel, db, excluded_cats, trailer=tt, flag_overrides=flag_overrides, include_all_items=include_all_items, user_excluded_bom_ids=user_excluded_bom_ids, optional_sections_enabled=optional_sections_enabled, formula_overrides=body.get("formula_overrides"))
    body_vars = _build_body_variables(bom_rows)
    _apply_body_variable_overrides(body_vars, body.get("body_variable_overrides"))
    _t = _mark("build_items_ms", _t)

    formula_lib = get_formula_lib()
    global_vars = get_global_vars()
    result = calculate_bom(bom_items, body.get("dimensions", {}), body_vars, formula_lib, global_vars)
    _t = _mark("formula_eval_ms", _t)

    result = _apply_chassis_and_margin(result, body, db)
    result = _apply_discount(result, body)
    result["trailer_name"] = tt.name
    _attach_formula_debug(result, body_vars, formula_lib, global_vars)
    _t = _mark("chassis_margin_ms", _t)

    # Serialize as a separate phase so we can tell whether a spike sits in
    # the handler logic or in JSON-dumping the result. Pre-encoding here also
    # lets GZipMiddleware compress a known-size bytes payload (slightly faster
    # than chunked-from-dict). Big freezer trailers can produce ~200 KB JSON.
    import json as _json
    _payload = _json.dumps(result, default=str).encode("utf-8")
    _mark("serialize_ms", _t)
    _stages["resp_bytes"] = len(_payload)

    # Surface the stage breakdown to the perf middleware so /admin/performance
    # can pinpoint where any future spike came from.
    try:
        request.state.perf_extra = _stages
    except Exception:
        pass
    return Response(content=_payload, media_type="application/json")


# ─── Check duplicate ──────────────────────────────────────────────────────────

def _same_quote_type_filter(is_repair_flag: bool):
    """Filter clause selecting calculations of the same quote type — Repair vs
    normal — so the two keep independent revision sequences. Legacy rows with a
    NULL is_repair are treated as normal."""
    if is_repair_flag:
        return CalculationRecord.is_repair == True   # noqa: E712
    return (CalculationRecord.is_repair == False) | (CalculationRecord.is_repair.is_(None))  # noqa: E712


@router.get("/api/check-duplicate")
async def check_duplicate(customer_id: int, trailer_type_id: int,
                          request: Request, db: Session = Depends(get_db),
                          is_repair: bool = False):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401)
    existing = (db.query(CalculationRecord)
                .filter(CalculationRecord.customer_id     == customer_id,
                        CalculationRecord.trailer_type_id == trailer_type_id,
                        _same_quote_type_filter(is_repair))
                .order_by(CalculationRecord.created_at.desc()).all())
    if not existing:
        return JSONResponse({"has_duplicate": False, "count": 0, "next_version": 2})
    max_version  = 1
    records_info = []
    for rec in existing:
        try:
            v = int(json.loads(rec.result_json).get("version", 1))
        except Exception:
            v = 1
        max_version = max(max_version, v)
        records_info.append({
            "id": rec.id, "version": v,
            "trailer": rec.trailer_type.name if rec.trailer_type else "—",
            "saved_at": rec.created_at.strftime("%Y-%m-%d %H:%M") if rec.created_at else "—",
            "quote_number": rec.quote_number,
        })
    # Pick a parent quote number to reuse: highest version that actually has one,
    # falling back to most-recent (records are already ordered created_at desc).
    parent_quote_number = None
    for r in sorted(records_info, key=lambda x: (-x["version"], 0)):
        if r.get("quote_number"):
            parent_quote_number = r["quote_number"]
            break
    return JSONResponse({
        "has_duplicate": True, "count": len(existing),
        "max_version": max_version, "next_version": max_version + 1,
        "records": records_info,
        "parent_quote_number": parent_quote_number,
    })


# ─── Approve / save ───────────────────────────────────────────────────────────

@router.post("/api/approve")
async def api_approve(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401)
    body = await request.json()

    trailer_id     = body.get("trailer_type_id")
    dims           = body.get("dimensions", {})
    profit_margin  = float(body.get("profit_margin", 0))
    customer_id    = body.get("customer_id") or None
    overrides      = {str(k): float(v) for k, v in body.get("overrides", {}).items()}
    override_reasons = {str(k): str(v).strip() for k, v in (body.get("override_reasons") or {}).items() if str(v).strip()}
    version_action = body.get("version_action")
    next_version   = int(body.get("next_version") or 2)
    is_repair      = bool(body.get("is_repair"))
    reuse_quote_number = bool(body.get("reuse_quote_number"))
    # When set, this save is an EDIT of an existing PENDING costing rather than a
    # brand-new one. version_action == "overwrite" updates that record in place;
    # "new_version" saves a fresh revision (optionally reusing its quote number).
    edit_record_id = body.get("edit_record_id")

    tt = db.query(TrailerType).filter_by(id=trailer_id).first()
    if not tt:
        raise HTTPException(status_code=404, detail="Trailer type not found")

    bom_rows = (db.query(BillOfMaterial)
                .filter_by(trailer_type_id=trailer_id)
                .options(*_bom_load_options())
                .order_by(BillOfMaterial.sort_order).all())
    section_order = {s.name: s.sort_order for s in db.query(BOMSection).all()}
    def _sec_key(r):
        name = r.bom_section or (r.material.category.name if r.material and r.material.category else "")
        return (section_order.get(name, 99998), name.lower(), r.material.name.lower() if r.material else "")
    bom_rows.sort(key=_sec_key)

    body_opt_sel  = {str(k): bool(v) for k, v in body.get("body_option_selections", {}).items()}
    excluded_cats = body.get("excluded_categories") or []
    flag_overrides = {str(k): bool(v) for k, v in (body.get("flag_overrides") or {}).items()}
    include_all_items = bool(body.get("include_all_items"))
    user_excluded_bom_ids = body.get("user_excluded_bom_ids") or []
    optional_sections_enabled = body.get("optional_sections_enabled") or []
    bom_items = _build_bom_items(bom_rows, dims, overrides, body_opt_sel, db, excluded_cats, trailer=tt, flag_overrides=flag_overrides, include_all_items=include_all_items, user_excluded_bom_ids=user_excluded_bom_ids, optional_sections_enabled=optional_sections_enabled, formula_overrides=body.get("formula_overrides"))
    body_vars = _build_body_variables(bom_rows)
    _apply_body_variable_overrides(body_vars, body.get("body_variable_overrides"))
    formula_lib = {f.name.lower(): f.expression
                   for f in db.query(Formula).filter_by(is_active=True).all()}
    global_vars = {gv.name: gv.value for gv in db.query(GlobalVariable).all()}
    result = calculate_bom(bom_items, dims, body_vars, formula_lib, global_vars)
    _attach_formula_debug(result, body_vars, formula_lib, global_vars)
    result = _apply_chassis_and_margin(result, body, db)
    result = _apply_discount(result, body)

    mat_updated = {row.material.name: (row.material.last_updated.isoformat()
                   if row.material.last_updated else None) for row in bom_rows}
    for item in result["items"]:
        item["last_updated"] = mat_updated.get(item["material"])

    bom_id_to_name = {str(row.id): row.material.name for row in bom_rows}
    result["overrides_by_bom"]  = {k: v for k, v in overrides.items() if k in bom_id_to_name}
    result["overrides_by_name"] = {bom_id_to_name[k]: v for k, v in overrides.items() if k in bom_id_to_name}
    result["override_reasons_by_bom"]  = {k: r for k, r in override_reasons.items() if k in bom_id_to_name}
    result["override_reasons_by_name"] = {bom_id_to_name[k]: r for k, r in override_reasons.items() if k in bom_id_to_name}

    # Snapshot the raw input selections so a later EDIT can faithfully re-hydrate
    # the calculator (body options, optional sections, exclusions, overrides).
    # Stored inside result_json — additive and backward compatible (old records
    # simply lack the key and fall back to recomputed defaults on edit).
    result["input_state"] = {
        "overrides":                 overrides,
        "override_reasons":          override_reasons,
        "body_option_selections":    body_opt_sel,
        "excluded_categories":       excluded_cats,
        "flag_overrides":            flag_overrides,
        "user_excluded_bom_ids":     user_excluded_bom_ids,
        "optional_sections_enabled": optional_sections_enabled,
        "profit_margin":             profit_margin,
        "is_repair":                 is_repair,
        "ratio_value":               body.get("ratio_value"),
        "ratio_label":               body.get("ratio_label"),
        "chassis":                   body.get("chassis"),
        # Complete client-side UI snapshot (body options, DRD/SRD, configurator
        # draft states, optional sections, full price overrides, chassis, body
        # variable values). Lets an edit re-hydrate the calculator exactly so the
        # recomputed total balances with the saved quote. Opaque to the backend.
        "ui_snapshot":               body.get("ui_snapshot"),
    }

    async with _approve_lock:
        # ── EDIT: overwrite an existing PENDING costing in place ──────────────
        # Keeps the record's id, quote number, revision and creation time; only
        # the recomputed result + dimensions are replaced. Guarded so a stale
        # page cannot overwrite a quote that has since been accepted/declined.
        if version_action == "overwrite" and edit_record_id:
            rec = db.query(CalculationRecord).filter_by(id=int(edit_record_id)).first()
            if not rec:
                raise HTTPException(status_code=404, detail="Costing to edit was not found")
            rec_status = rec.status or ("accepted" if rec.approved_at else "pending")
            if rec_status != "pending":
                raise HTTPException(
                    status_code=409,
                    detail=f"Only pending costings can be edited — this one is '{rec_status}'.",
                )
            try:
                _prev = json.loads(rec.result_json) if rec.result_json else {}
            except Exception:
                _prev = {}
            result["version"]   = int(_prev.get("version", 1) or 1)
            result["is_repair"] = is_repair
            rec.dimensions_json = json.dumps(dims)
            rec.result_json     = json.dumps(result)
            rec.is_repair       = is_repair
            rec.customer_id     = customer_id
            rec.discount_kind   = result.get("discount_kind")
            rec.discount_input  = result.get("discount_input")
            rec.discount_amount = result.get("discount_amount")
            rec.net_total       = result.get("net_total")
            db.commit()
            db.refresh(rec)
            result["record_id"]     = rec.id
            result["quote_number"]  = rec.quote_number
            result["trailer_name"]  = tt.name
            _cust = db.query(Customer).filter_by(id=customer_id).first() if customer_id else None
            result["customer_name"] = _cust.name if _cust else None
            return JSONResponse(result)

        if customer_id and version_action is None:
            fresh_count = db.query(CalculationRecord).filter(
                CalculationRecord.customer_id     == customer_id,
                CalculationRecord.trailer_type_id == trailer_id,
                _same_quote_type_filter(is_repair),
            ).count()
            if fresh_count > 0:
                raise HTTPException(
                    status_code=409,
                    detail="A costing for this customer and trailer was saved just before yours. "
                           "Please go back and choose 'Save as new version' or 'Replace'."
                )

        if customer_id and version_action == "replace":
            db.query(CalculationRecord).filter(
                CalculationRecord.customer_id     == customer_id,
                CalculationRecord.trailer_type_id == trailer_id,
                _same_quote_type_filter(is_repair),
            ).delete(synchronize_session=False)
            db.commit()
            result["version"] = 1
        elif version_action == "new_version":
            result["version"] = next_version
        else:
            result["version"] = 1

        result["is_repair"] = is_repair
        rec = CalculationRecord(
            trailer_type_id=trailer_id,
            user_id=user.id,
            customer_id=customer_id,
            dimensions_json=json.dumps(dims),
            result_json=json.dumps(result),
            is_repair=is_repair,
            discount_kind=result.get("discount_kind"),
            discount_input=result.get("discount_input"),
            discount_amount=result.get("discount_amount"),
            net_total=result.get("net_total"),
        )
        db.add(rec)
        db.flush()
        if reuse_quote_number and version_action == "new_version" and (customer_id or edit_record_id):
            # Copy the parent quote's number onto this revision so the whole
            # revision family shares one identifier. assign_quote_number below
            # is idempotent — it returns early when rec.quote_number is set,
            # so the global counter doesn't advance.
            parent = None
            # An edit knows its exact parent record — use it directly so reuse
            # works even for quotes saved without a customer.
            if edit_record_id:
                parent = db.query(CalculationRecord).filter_by(id=int(edit_record_id)).first()
            if (parent is None or not parent.quote_number) and customer_id:
                parent = (db.query(CalculationRecord)
                            .filter(CalculationRecord.customer_id     == customer_id,
                                    CalculationRecord.trailer_type_id == trailer_id,
                                    CalculationRecord.id              != rec.id,
                                    CalculationRecord.quote_number.isnot(None),
                                    _same_quote_type_filter(is_repair))
                            .order_by(CalculationRecord.created_at.desc())
                            .first())
            if parent and parent.quote_number:
                rec.quote_number = parent.quote_number
                db.flush()
        try:
            assign_quote_number(rec, db=db, user=user, trailer=tt)
        except Exception:
            logging.exception("assign_quote_number failed for record %s", rec.id)
        db.commit()
        db.refresh(rec)

    result["record_id"]    = rec.id
    result["quote_number"] = rec.quote_number
    result["trailer_name"] = tt.name
    customer = db.query(Customer).filter_by(id=customer_id).first() if customer_id else None
    result["customer_name"] = customer.name if customer else None
    return JSONResponse(result)


# ─── Results page ─────────────────────────────────────────────────────────────

@router.get("/results/{record_id}", response_class=HTMLResponse)
async def results_page(record_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login")
    rec = db.query(CalculationRecord).filter_by(id=record_id).first()
    if not rec:
        raise HTTPException(status_code=404)
    dims   = json.loads(rec.dimensions_json)
    result = json.loads(rec.result_json)
    result = strip_excluded_items(result)  # report shows only selected items
    tt     = db.query(TrailerType).filter_by(id=rec.trailer_type_id).first()

    overrides_by_name        = result.get("overrides_by_name", {})
    override_reasons_by_name = result.get("override_reasons_by_name", {}) or {}
    result_version           = result.get("version", 1)
    now_utc = datetime.now(timezone.utc)
    cutoff  = now_utc - timedelta(days=7)
    outdated_cutoff = now_utc - timedelta(days=90)

    recently_updated: dict = {}
    outdated_prices:  dict = {}
    for item in result.get("items", []):
        lu = item.get("last_updated")
        if lu and item["material"] not in overrides_by_name:
            try:
                lu_dt = datetime.fromisoformat(lu)
                if lu_dt.tzinfo is None:
                    lu_dt = lu_dt.replace(tzinfo=timezone.utc)
                dfmt = "%#d %b %Y" if platform.system() == "Windows" else "%-d %b %Y"
                if lu_dt >= cutoff:
                    recently_updated[item["material"]] = "Price updated " + lu_dt.strftime(dfmt)
                elif lu_dt < outdated_cutoff:
                    outdated_prices[item["material"]] = "Outdated price from " + lu_dt.strftime(dfmt)
            except Exception:
                pass

    report_template = resolve_report_template(tt)
    return templates.TemplateResponse("results.html", {
        "request": request, "user": user,
        "record": rec, "dims": dims, "result": result,
        "result_items": result.get("items", []),
        "trailer": tt,
        "overrides_by_name":        overrides_by_name,
        "override_reasons_by_name": override_reasons_by_name,
        "recently_updated":  recently_updated,
        "outdated_prices":   outdated_prices,
        "result_version":    result_version,
        "report_template":   report_template,
    })


# ─── Calculations list ────────────────────────────────────────────────────────

@router.get("/api/calculations")
async def api_list_calculations(
    request: Request, db: Session = Depends(get_db),
    filter: str = "all", limit: int = 20
):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401)
    q = db.query(CalculationRecord)
    now_utc = datetime.now(timezone.utc)
    if filter == "week":
        q = q.filter(CalculationRecord.created_at >= now_utc - timedelta(days=7))
    elif filter == "month":
        q = q.filter(CalculationRecord.created_at >= now_utc - timedelta(days=30))
    elif filter == "approved":
        q = q.filter(CalculationRecord.approved_at.isnot(None))
    elif filter == "pending":
        q = q.filter((CalculationRecord.status == "pending") | (CalculationRecord.status.is_(None)))
    elif filter == "accepted":
        q = q.filter(CalculationRecord.status == "accepted")
    elif filter == "declined":
        q = q.filter(CalculationRecord.status == "declined")
    elif filter == "repair":
        q = q.filter(_same_quote_type_filter(True))
    records = q.order_by(CalculationRecord.created_at.desc()).limit(limit).all()
    full_access = user_can(user, "bom.view_full_cost", db)
    result = []
    for r in records:
        rd = {}
        if r.result_json:
            try: rd = json.loads(r.result_json)
            except Exception: pass
        # Headline total = net (after discount). Prefer the column, then result_json,
        # then fall back to the pre-discount selling price / grand total for legacy rows.
        _net = r.net_total if getattr(r, "net_total", None) is not None else rd.get("net_total")
        grand_total = float(_net if _net is not None else (rd.get("selling_price") or rd.get("grand_total") or 0))
        raw_status = (getattr(r, "status", None) or ("accepted" if r.approved_at else "pending"))
        # MES status mapping (Addendum v1.2.1): translate the internal lower-case
        # status to the labels the MES React mockup uses on its Costings Dashboard.
        # A Repair quote reads as "Repair" once it has been accepted; until then it
        # follows the normal status flow with an additional Repair badge in the UI.
        if bool(getattr(r, "is_repair", False)) and raw_status in ("accepted", "pre_job_sent", "pre_job_confirmed", "planning"):
            mes_status = "Repair"
        else:
            mes_status = {
                "pending":           "Pending",
                "accepted":          "Accepted",
                "pre_job_sent":      "Pre-Job Sent",
                "pre_job_confirmed": "Pre-Job Confirmed",
                "planning":          "Planning",
                "declined":          "Rejected",
            }.get(raw_status, raw_status.title())
        result.append({
            "id": r.id,
            "quote_number": r.quote_number or None,
            "trailer":  r.trailer_type.name if r.trailer_type else "—",
            "customer": r.customer.name if r.customer else "—",
            "user":     r.user.username if r.user else "—",
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "—",
            "grand_total": grand_total if full_access else None,   # net of discount (headline)
            "gross_total":     float(rd.get("selling_price") or rd.get("grand_total") or 0) if full_access else None,
            "discount_amount": (float(r.discount_amount) if getattr(r, "discount_amount", None) is not None
                                else (float(rd["discount_amount"]) if rd.get("discount_amount") is not None else 0)) if full_access else None,
            "discount_kind":   r.discount_kind if getattr(r, "discount_kind", None) is not None else rd.get("discount_kind"),
            "version":    int(rd.get("version", 1)),
            "approved":   bool(r.approved_at),
            "approved_at": r.approved_at.strftime("%Y-%m-%d %H:%M") if r.approved_at else None,
            "approver":   r.approver.username if getattr(r, "approver", None) else None,
            "status":     raw_status,
            "mes_status": mes_status,
            "decline_reason": getattr(r, "decline_reason", None),
            "is_repair":  bool(getattr(r, "is_repair", False)),
            "pre_job_sent_at":      r.pre_job_sent_at.strftime("%Y-%m-%d %H:%M") if getattr(r, "pre_job_sent_at", None) else None,
            "pre_job_confirmed_at": r.pre_job_confirmed_at.strftime("%Y-%m-%d %H:%M") if getattr(r, "pre_job_confirmed_at", None) else None,
            "job_number_assigned":  getattr(r, "job_number_assigned", None),
            "repair_phases":        json.loads(r.repair_phases_json) if getattr(r, "repair_phases_json", None) else None,
            # Work Order v4 — sign-off + planning ack fields (attestation text excluded to keep list payload lean).
            "pre_job_signoff_sales_at":      r.pre_job_signoff_sales_at.strftime("%Y-%m-%d %H:%M") if getattr(r, "pre_job_signoff_sales_at", None) else None,
            "pre_job_signoff_sales_by":      getattr(r, "pre_job_signoff_sales_by", None),
            "pre_job_signoff_production_at": r.pre_job_signoff_production_at.strftime("%Y-%m-%d %H:%M") if getattr(r, "pre_job_signoff_production_at", None) else None,
            "pre_job_signoff_production_by": getattr(r, "pre_job_signoff_production_by", None),
            "planning_acknowledged_at":      r.planning_acknowledged_at.strftime("%Y-%m-%d %H:%M") if getattr(r, "planning_acknowledged_at", None) else None,
            "planning_acknowledged_by":      getattr(r, "planning_acknowledged_by", None),
            # Work Order v4.2 — chassis ETA capture fields.
            "chassis_eta":                   r.chassis_eta.strftime("%Y-%m-%d") if getattr(r, "chassis_eta", None) else None,
            "chassis_eta_captured_at":       r.chassis_eta_captured_at.strftime("%Y-%m-%d %H:%M") if getattr(r, "chassis_eta_captured_at", None) else None,
            "chassis_eta_captured_by":       getattr(r, "chassis_eta_captured_by", None),
            "chassis_data":                  json.loads(r.chassis_data_json) if getattr(r, "chassis_data_json", None) else None,
            "chassis_received_at":           r.chassis_received_at.strftime("%Y-%m-%d") if getattr(r, "chassis_received_at", None) else None,
            "chassis_received_by":           getattr(r, "chassis_received_by", None),
        })
    return result


@router.post("/api/calculations/{record_id}/accept")
@router.post("/api/calculations/{record_id}/approve")  # legacy alias
async def api_mark_calculation_accepted(record_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401)
    rec = db.query(CalculationRecord).filter_by(id=record_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Calculation not found")
    if rec.approved_at:
        return {
            "ok": True, "already_decided": True, "status": "accepted",
            "approved_at": rec.approved_at.strftime("%Y-%m-%d %H:%M"),
            "approver": rec.approver.username if rec.approver else (user.username if rec.approved_by_user_id == user.id else None),
        }
    rec.approved_at = datetime.now(timezone.utc)
    rec.approved_by_user_id = user.id
    rec.status = "accepted"
    rec.decline_reason = None
    db.commit()
    db.refresh(rec)
    return {
        "ok": True, "already_decided": False, "status": "accepted",
        "approved_at": rec.approved_at.strftime("%Y-%m-%d %H:%M"),
        "approver": user.username,
    }


@router.post("/api/calculations/{record_id}/decline")
async def api_mark_calculation_declined(record_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401)
    rec = db.query(CalculationRecord).filter_by(id=record_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Calculation not found")
    body = await request.json()
    reason = (body.get("reason") or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="A decline reason is required")
    rec.approved_at         = datetime.now(timezone.utc)
    rec.approved_by_user_id = user.id
    rec.status              = "declined"
    rec.decline_reason      = reason
    db.commit()
    db.refresh(rec)
    return {
        "ok": True, "already_decided": False, "status": "declined",
        "decline_reason": reason,
        "approved_at": rec.approved_at.strftime("%Y-%m-%d %H:%M"),
        "approver": user.username,
    }


@router.delete("/api/calculations/{record_id}")
async def api_delete_calculation(record_id: int, request: Request, db: Session = Depends(get_db)):
    from ..deps import require_admin
    require_admin(request, db)
    rec = db.query(CalculationRecord).filter_by(id=record_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Calculation not found")
    db.delete(rec)
    db.commit()
    return {"ok": True}


@router.get("/api/calculations/{record_id}")
async def api_get_calculation(record_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401)
    rec = db.query(CalculationRecord).filter_by(id=record_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Calculation not found")
    try:
        dims = json.loads(rec.dimensions_json) if rec.dimensions_json else {}
    except Exception:
        dims = {}
    try:
        result_data = json.loads(rec.result_json) if rec.result_json else {}
    except Exception:
        result_data = {}
    input_state = result_data.get("input_state") or {}
    status = rec.status or ("accepted" if rec.approved_at else "pending")
    return {
        "id": rec.id,
        "trailer_type_id": rec.trailer_type_id,
        "customer_id":     rec.customer_id,
        "dimensions":      dims,
        "profit_margin":   float(result_data.get("profit_margin")
                                 or input_state.get("profit_margin") or 0),
        # ── Edit-mode fields (used by /calculator?edit=) ──────────────────────
        "status":        status,
        "version":       int(result_data.get("version", 1) or 1),
        "quote_number":  rec.quote_number,
        "is_repair":     bool(getattr(rec, "is_repair", False)),
        # Price overrides survive on every record (overrides_by_bom); option
        # toggles only on records saved with the input_state snapshot.
        "overrides":               result_data.get("overrides_by_bom")
                                   or input_state.get("overrides") or {},
        "override_reasons":        result_data.get("override_reasons_by_bom")
                                   or input_state.get("override_reasons") or {},
        "body_option_selections":    input_state.get("body_option_selections") or {},
        "excluded_categories":       input_state.get("excluded_categories") or [],
        "flag_overrides":            input_state.get("flag_overrides") or {},
        "user_excluded_bom_ids":     input_state.get("user_excluded_bom_ids") or [],
        "optional_sections_enabled": input_state.get("optional_sections_enabled") or [],
        # Profit ratio lives at the top level of result_json on every record that
        # used one (set by _apply_chassis_and_margin) — read it there first so the
        # calculator restores the selling-price ratio on edit and the total doesn't
        # jump. input_state is only the fallback for the (redundant) newer copy.
        "ratio_value":               result_data.get("ratio_value")
                                     if result_data.get("ratio_value") is not None
                                     else input_state.get("ratio_value"),
        "ratio_label":               result_data.get("ratio_label")
                                     or input_state.get("ratio_label"),
        # Full UI snapshot + chassis for faithful re-hydration on edit.
        "ui_snapshot":   input_state.get("ui_snapshot") or {},
        "chassis":       input_state.get("chassis") or result_data.get("chassis"),
        # Discount (prefer the dedicated columns; fall back to result_json).
        "discount_kind":   rec.discount_kind   if rec.discount_kind   is not None else result_data.get("discount_kind"),
        "discount_input":  rec.discount_input  if rec.discount_input  is not None else result_data.get("discount_input"),
        "discount_amount": rec.discount_amount if rec.discount_amount is not None else result_data.get("discount_amount"),
        "net_total":       rec.net_total       if rec.net_total       is not None else result_data.get("net_total"),
        # The saved result itself (sans the bulky input_state echo) so the editor
        # can display the original figures and run a balance check against them.
        "saved_result":  {k: v for k, v in result_data.items() if k != "input_state"},
    }
