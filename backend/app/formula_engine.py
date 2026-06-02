"""
Safe formula evaluation engine.
Formulas can reference: length, width, height, floor_thickness, panel_thickness,
insulation_thickness, num_doors, num_axles, wall_area, roof_area, floor_area,
surface_area, and any material quantity already computed.
"""
import math
import re

ALLOWED_NAMES = {
    "abs": abs, "round": round, "min": min, "max": max,
    "sqrt": math.sqrt, "pi": math.pi, "ceil": math.ceil, "floor": math.floor,
}

# Matches {VAR NAME} tokens in formulas. Names match Body Variable
# material names (case-insensitive), e.g. {FRONT EPS}, {ROOF PU}.
_VAR_TOKEN_RE = re.compile(r"\{([^{}]+)\}")


def _substitute_variables(
    expr: str,
    variables: dict | None,
    context: dict | None = None,
    formula_library: dict | None = None,
    _seen: frozenset = frozenset(),
    _unknown: list | None = None,
) -> str:
    """Replace {NAME} tokens with numeric values from body variables or formula library.

    Resolution order:
      1. Body variable (e.g. {FRONT EPS}) — case-insensitive lookup in `variables`
      2. Formula library reference (e.g. {front_panel_and_SRD_width}) — evaluated
         recursively against the current geometry `context`
      3. Unknown token → 0  (appended to `_unknown` if provided)
    """
    if "{" not in expr:
        return expr
    norm = {k.strip().upper(): v for k, v in (variables or {}).items()}
    flib = {k.strip().lower(): v for k, v in (formula_library or {}).items()}

    def repl(m):
        key = m.group(1).strip()
        # 1. Body variable
        if key.upper() in norm:
            val = norm[key.upper()]
            try:
                return f"({float(val)})"
            except (TypeError, ValueError):
                return "(0)"
        # 2. Formula library reference — evaluate recursively, guarding cycles
        if key.lower() in flib and key.lower() not in _seen:
            ref_expr = flib[key.lower()]
            val = evaluate_formula(
                ref_expr, context or {}, variables,
                formula_library=formula_library,
                _seen=_seen | {key.lower()},
            )
            return f"({val})"
        # 3. Unknown token — flag and substitute zero
        if _unknown is not None:
            _unknown.append(key)
        return "(0)"

    return _VAR_TOKEN_RE.sub(repl, expr)


def evaluate_formula(
    expression: str,
    context: dict,
    variables: dict | None = None,
    formula_library: dict | None = None,
    _seen: frozenset = frozenset(),
    _err: list | None = None,
    _unknown: list | None = None,
) -> float:
    """Evaluate a formula string with the given variable context.

    `variables` resolves body variable tokens like `{FRONT EPS}`.
    `formula_library` resolves named formula references like `{front_panel_and_SRD_width}`.
    `_err`: optional list; True is appended when eval() raises.
    `_unknown`: optional list; unresolved {VAR} token names are appended.
    """
    if not expression or str(expression).strip() == "":
        return 1.0
    expr = _substitute_variables(str(expression).strip(), variables, context, formula_library, _seen, _unknown)
    # Pure number
    try:
        return float(expr)
    except ValueError:
        pass

    # Build safe evaluation namespace
    safe_vars = {**ALLOWED_NAMES, **context}
    try:
        result = eval(expr, {"__builtins__": {}}, safe_vars)  # noqa: S307
        return max(0.0, float(result))
    except Exception:
        if _err is not None:
            _err.append(True)
        return 0.0


def build_geometry(dims: dict) -> dict:
    """Derive standard geometry values from user-supplied dimensions."""
    L = float(dims.get("length", 0) or 0)
    W = float(dims.get("width", 0) or 0)
    H = float(dims.get("height", 0) or 0)
    FT = float(dims.get("floor_thickness", 0) or 0)
    PT = float(dims.get("panel_thickness", 0) or 0)
    IT = float(dims.get("insulation_thickness", 0) or 0)
    ND = float(dims.get("num_doors", 1) or 1)
    NA = float(dims.get("num_axles", 2) or 2)

    wall_area = L * H * 2
    roof_area = L * W
    floor_area = L * W
    front_rear_area = W * H * 2
    surface_area = wall_area + roof_area + floor_area + front_rear_area
    total_panel_area = wall_area + roof_area + front_rear_area
    volume = L * W * H

    return {
        "length": L,
        "width": W,
        "height": H,
        "floor_thickness": FT,
        "panel_thickness": PT,
        "insulation_thickness": IT,
        "num_doors": ND,
        "num_axles": NA,
        "wall_area": wall_area,
        "roof_area": roof_area,
        "floor_area": floor_area,
        "front_rear_area": front_rear_area,
        "surface_area": surface_area,
        "total_panel_area": total_panel_area,
        "volume": volume,
    }


def calculate_bom(bom_items: list, dims: dict, body_variables: dict | None = None, formula_library: dict | None = None, global_variables: dict | None = None) -> dict:
    """
    Calculate costs for a list of BOM items.

    bom_items: list of dicts with keys:
        material_name, category_name, formula_expression, waste_percentage,
        price_per_unit, unit_of_measure, material_code

    dims: dict of user-input dimensions

    Returns a dict:
        items: list of line items
        category_totals: dict category_name -> total
        grand_total: float
        cost_per_sqm: float
    """
    ctx = build_geometry(dims)
    # Global variables are a fallback layer; body-specific variables take precedence.
    merged_vars = {**(global_variables or {}), **(body_variables or {})}
    items = []
    category_totals = {}

    for bom in bom_items:
        expr = bom.get("formula_expression") or "1"
        waste_pct = float(bom.get("waste_percentage") or 0)
        price = float(bom.get("price_per_unit") or 0)
        cat = bom.get("category_name", "Uncategorised")
        # "Soft excluded" rows ride along in the response so the costings page
        # can render them struck-through under their section, but they do NOT
        # contribute to qty / line_cost / category totals.
        excluded = bool(bom.get("excluded"))
        excluded_reason = bom.get("excluded_reason")

        _err: list = []
        _unknown: list = []
        qty_raw = evaluate_formula(expr, ctx, merged_vars, formula_library, _err=_err, _unknown=_unknown)
        formula_error = bool(_err) or bool(_unknown)
        section_mult = float(bom.get("section_multiplier") or 1.0)
        qty = qty_raw * section_mult * (1 + waste_pct / 100)
        line_cost = qty * price

        items.append({
            "category": cat,
            "bom_id": bom.get("bom_id"),
            "bom_section_id": bom.get("bom_section_id"),
            "section_is_optional": bool(bom.get("section_is_optional")),
            "material": bom.get("material_name", ""),
            "material_code": bom.get("material_code", ""),
            "unit": bom.get("unit_of_measure", "each"),
            "formula": expr,
            "quantity": round(qty, 4),
            "unit_price": price,
            "waste_pct": waste_pct,
            "line_cost": 0.0 if excluded else round(line_cost, 2),
            "section_multiplier": section_mult,
            "formula_error": formula_error,
            "formula_unknown_vars": _unknown if _unknown else [],
            "excluded": excluded,
            "excluded_reason": excluded_reason,
        })

        if not excluded:
            category_totals[cat] = category_totals.get(cat, 0) + line_cost

    grand_total = sum(category_totals.values())
    floor_area = ctx.get("floor_area", 1) or 1
    cost_per_sqm = grand_total / floor_area if floor_area else 0

    # Build per-category multiplier map (first item in each category wins)
    category_multipliers = {}
    for it in items:
        cat = it["category"]
        if cat not in category_multipliers and it["section_multiplier"] != 1.0:
            category_multipliers[cat] = it["section_multiplier"]

    return {
        "items": items,
        "category_totals": {k: round(v, 2) for k, v in category_totals.items()},
        "category_multipliers": category_multipliers,
        "grand_total": round(grand_total, 2),
        "cost_per_sqm": round(cost_per_sqm, 2),
        "geometry": {k: round(v, 4) for k, v in ctx.items()},
    }
