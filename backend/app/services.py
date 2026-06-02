"""Cross-router business logic helpers: BOM loading, cost computation, serialization."""

from collections import namedtuple

from sqlalchemy.orm import joinedload, selectinload

from . import cache
from . import database as _db  # WO v4.7.1 — module reference so SessionLocal stays live across switch_db()
from .database import (
    BillOfMaterial, Material, BOMSection, Formula, GlobalVariable,
    SkinFormula, SkinFormulaItem, SkinFormulaIngredient,
    TapingBlock, TapingBlockItem,
    FloorPlate, FloorPlateItem,
    MountingCleat, MountingCleatItem,
    BodyOptionGroup, BodyOptionSubgroup,
)


def SessionLocal():
    """Call-time lookup of the current SessionLocal. switch_db() rebinds
    database.SessionLocal to a new sessionmaker; if we'd imported the binding
    directly it would still point at the stale (pre-swap) engine, which is
    exactly the bug that made OPTIONAL EXTRAS render blue after db_choice=dev
    (the snapshot loaded from tcm_db, not SQLite, so is_optional=0 stuck)."""
    return _db.SessionLocal()


# ── Lookup-table cache (hot path) ─────────────────────────────────────────────
#
# BOMSection / Formula(is_active) / GlobalVariable are read on every
# /api/calculate but written only by admins. We snapshot each into plain
# Python data structures (no ORM objects — those would be detached after
# the loader's session closes) and cache per-worker for a short TTL.
#
# Admin write endpoints call the invalidate_* helpers below so the writing
# worker's next read is fresh; other workers catch up within TTL.

_SECTION_TTL  = 30.0
_FORMULA_TTL  = 30.0
_GVAR_TTL     = 30.0

# Plain-data section row — what _build_bom_items / get_bom actually consume.
SectionRow = namedtuple(
    "SectionRow",
    "id name sort_order multiplier is_optional archived_at body_option_master_id",
)

# Bundle of everything section-related the calc path needs from a single
# load. Keys are pre-computed so the request hot path is dict lookups only.
SectionSnapshot = namedtuple(
    "SectionSnapshot",
    "order mults_by_id mults_by_name optional_by_id optional_by_name by_id",
)


def _load_section_snapshot() -> SectionSnapshot:
    """Single DB hit → pre-built lookup dicts. Runs at most once per TTL per worker."""
    db = SessionLocal()
    try:
        rows = [
            SectionRow(
                id=s.id,
                name=s.name,
                sort_order=s.sort_order,
                multiplier=s.multiplier or 1.0,
                is_optional=bool(s.is_optional),
                archived_at=s.archived_at,
                body_option_master_id=s.body_option_master_id,
            )
            for s in db.query(BOMSection).all()
        ]
    finally:
        db.close()
    return SectionSnapshot(
        order            = {r.name: r.sort_order for r in rows},
        mults_by_id      = {r.id:   r.multiplier for r in rows},
        mults_by_name    = {r.name: r.multiplier for r in rows},
        optional_by_id   = {r.id:   r.is_optional for r in rows},
        optional_by_name = {r.name: r.is_optional for r in rows},
        by_id            = {r.id:   r for r in rows},
    )


def _load_formula_lib() -> dict[str, str]:
    db = SessionLocal()
    try:
        return {f.name.lower(): f.expression
                for f in db.query(Formula).filter_by(is_active=True).all()}
    finally:
        db.close()


def _load_global_vars() -> dict[str, float]:
    db = SessionLocal()
    try:
        return {gv.name: gv.value for gv in db.query(GlobalVariable).all()}
    finally:
        db.close()


def get_section_snapshot() -> SectionSnapshot:
    return cache.get("sections", _load_section_snapshot, ttl=_SECTION_TTL)


def get_formula_lib() -> dict[str, str]:
    return cache.get("formulas", _load_formula_lib, ttl=_FORMULA_TTL)


def get_global_vars() -> dict[str, float]:
    return cache.get("global_vars", _load_global_vars, ttl=_GVAR_TTL)


def invalidate_sections() -> None:
    cache.invalidate("sections")


def invalidate_formulas() -> None:
    cache.invalidate("formulas")


def invalidate_global_vars() -> None:
    cache.invalidate("global_vars")


# Auto-invalidation: hook the ORM mapper events for the three cached tables so
# *any* code path that writes through SQLAlchemy busts the cache. This is
# strictly better than scattering invalidate_*() calls through routers — no
# new write site can ever forget to invalidate. Bulk Core updates would still
# bypass these events (we don't currently issue any against these tables); add
# `after_bulk_update` listeners here if that changes.
from sqlalchemy import event as _sa_event  # noqa: E402  (intentional late import)

def _bind_invalidator(model, invalidator):
    for _evt in ("after_insert", "after_update", "after_delete"):
        _sa_event.listen(model, _evt, lambda *_a, _inv=invalidator, **_kw: _inv())

_bind_invalidator(BOMSection,     invalidate_sections)
_bind_invalidator(Formula,        invalidate_formulas)
_bind_invalidator(GlobalVariable, invalidate_global_vars)


# ── Report rendering helper ───────────────────────────────────────────────────

def strip_excluded_items(result):
    """Return a result dict with user-excluded line items removed, so the
    costing report page and the PDF / Excel exports show only the categories
    and line items selected to appear. `category_totals` is already
    exclusion-correct (calculate_bom never adds excluded rows to it), so only
    the `items` list needs filtering. Returns the input unchanged when nothing
    is excluded."""
    if not isinstance(result, dict):
        return result
    items = result.get("items")
    if not items or not any(it.get("excluded") for it in items):
        return result
    out = dict(result)
    out["items"] = [it for it in items if not it.get("excluded")]
    return out


# ── BOM eager-load helper ─────────────────────────────────────────────────────

def _bom_load_options():
    """Shared eager-load chain for BOM queries.

    The parent relations (material/category/section + each recipe parent)
    are all many-to-one, so joinedload collapses them into a single LEFT
    JOIN on the main BOM query — no row explosion. The four recipe leaf
    collections (.items) ARE one-to-many, so joinedload on those WOULD
    Cartesian-multiply rows; they stay on selectinload to fetch each in a
    separate `WHERE formula_id IN (...)` query.

    Why parent recipes are joinedload-not-selectinload: on production
    cPanel/PyMySQL the network round-trip dominates query cost (~30-80 ms
    each). One main query with four extra LEFT JOINs beats five separate
    IN-queries by hundreds of milliseconds on recipe-heavy trailers like
    FREEZER bodies. Local SQLite is round-trip-free so the trade-off
    inverts there — don't be fooled by dev benchmarks.
    """
    return (
        joinedload(BillOfMaterial.material).joinedload(Material.category),
        joinedload(BillOfMaterial.section),
        joinedload(BillOfMaterial.skin_formula).selectinload(
            SkinFormula.items
        ).joinedload(SkinFormulaItem.ingredient).joinedload(
            SkinFormulaIngredient.sap_item
        ),
        joinedload(BillOfMaterial.taping_block).selectinload(
            TapingBlock.items
        ).joinedload(TapingBlockItem.sap_item),
        joinedload(BillOfMaterial.floor_plate).selectinload(
            FloorPlate.items
        ).joinedload(FloorPlateItem.sap_item),
        joinedload(BillOfMaterial.mounting_cleat).selectinload(
            MountingCleat.items
        ).joinedload(MountingCleatItem.sap_item),
    )


# ── Cost computation ──────────────────────────────────────────────────────────

def _compute_skin_formula_cost(formula: SkinFormula, region: str) -> float:
    """Return cost per m² for a skin formula.

    region='sap'            → every ingredient uses sap_item.last_purch_price
                               (fallback to price_standard if no SAP link)
    region='kzn'            → ingredient.price_kzn   (per-item price_source='sap' still overrides)
    region='standard'       → ingredient.price_standard (per-item price_source='sap' still overrides)
    """
    total = 0.0
    for item in formula.items:
        ing = item.ingredient
        if not ing:
            continue
        if region == "sap":
            sap = ing.sap_item
            price = sap.last_purch_price if sap else ing.price_standard
        elif getattr(item, "price_source", "standard") == "sap":
            sap = ing.sap_item
            price = sap.last_purch_price if sap else ing.price_standard
        else:
            price = ing.price_kzn if region == "kzn" else ing.price_standard
        total += price * item.qty_per_m2
    return round(total, 4)


def _compute_taping_block_cost(block: TapingBlock) -> float:
    """Return cost per block = Σ(item.m2 × price × item.quantity)."""
    total = 0.0
    for item in block.items:
        if item.quantity == 0:
            continue
        if getattr(item, "price_source", "standard") == "sap" and item.sap_item:
            price = item.sap_item.last_purch_price
        else:
            price = item.price_per_unit
        total += item.m2 * price * item.quantity
    return round(total, 4)


def _serialize_taping_block(b: TapingBlock) -> dict:
    return {
        "id":          b.id,
        "name":        b.name,
        "description": b.description or "",
        "size_mm":     b.size_mm,
        "is_active":   b.is_active,
        "sort_order":  b.sort_order,
        "cost":        _compute_taping_block_cost(b),
        "items": [
            {
                "id":               it.id,
                "item_name":        it.item_name,
                "sap_code":         it.sap_code or "",
                "sap_item_code_id": it.sap_item_code_id,
                "length":           it.length,
                "width":            it.width,
                "m2":               it.m2,
                "price_per_unit":   it.price_per_unit,
                "price_source":     getattr(it, "price_source", "standard") or "standard",
                "price_sap":        it.sap_item.last_purch_price if it.sap_item else None,
                "quantity":         it.quantity,
                "sort_order":       it.sort_order,
                "line_cost":        round(
                    it.m2 * (
                        it.sap_item.last_purch_price
                        if (getattr(it, "price_source", "standard") == "sap" and it.sap_item)
                        else it.price_per_unit
                    ) * it.quantity, 4
                ),
            }
            for it in b.items
        ],
    }


def _apply_floor_formula(raw_total: float, formula_json: str | None) -> float:
    """Apply a stored price formula (JSON list of ops) to a raw assembly total.
    formula_json example: '[{"op":"/","val":12},{"op":"/","val":2.44}]'
    Returns raw_total unchanged if formula is absent or invalid."""
    if not formula_json:
        return raw_total
    import json as _json
    try:
        steps = _json.loads(formula_json)
        result = raw_total
        for s in steps:
            op, val = s.get("op"), float(s.get("val", 1))
            if op == "/" and val != 0:
                result /= val
            elif op == "*" and val != 0:
                result *= val
        return round(result, 4)
    except Exception:
        return raw_total


def _compute_floor_plate_cost(plate: FloorPlate) -> float:
    """Return assembly cost: Σ(item.m2 × price × qty), then apply price_formula if set."""
    total = 0.0
    for item in plate.items:
        if item.quantity == 0:
            continue
        if getattr(item, "price_source", "standard") == "sap" and item.sap_item:
            price = item.sap_item.last_purch_price
        else:
            price = item.price_per_unit
        total += item.m2 * price * item.quantity
    formula = getattr(plate, "price_formula", None)
    return round(_apply_floor_formula(total, formula), 4)


def _serialize_floor_plate(p: FloorPlate) -> dict:
    raw_total = sum(
        it.m2 * (it.sap_item.last_purch_price
                 if (getattr(it, "price_source", "standard") == "sap" and it.sap_item)
                 else it.price_per_unit) * it.quantity
        for it in p.items if it.quantity != 0
    )
    formula = getattr(p, "price_formula", None)
    return {
        "id":            p.id,
        "name":          p.name,
        "description":   p.description or "",
        "is_active":     p.is_active,
        "sort_order":    p.sort_order,
        "price_formula": formula or None,
        "raw_cost":      round(raw_total, 4),
        "cost":          round(_apply_floor_formula(raw_total, formula), 4),
        "items": [
            {
                "id":               it.id,
                "side":             it.side,
                "item_name":        it.item_name,
                "sap_code":         it.sap_code or "",
                "sap_item_code_id": it.sap_item_code_id,
                "length":           it.length,
                "width":            it.width,
                "m2":               it.m2,
                "price_per_unit":   it.price_per_unit,
                "price_source":     getattr(it, "price_source", "standard") or "standard",
                "price_sap":        it.sap_item.last_purch_price if it.sap_item else None,
                "quantity":         it.quantity,
                "sort_order":       it.sort_order,
                "line_cost":        round(
                    it.m2 * (
                        it.sap_item.last_purch_price
                        if (getattr(it, "price_source", "standard") == "sap" and it.sap_item)
                        else it.price_per_unit
                    ) * it.quantity, 4
                ),
            }
            for it in p.items
        ],
    }


def _compute_mounting_cleat_cost(cleat: MountingCleat) -> float:
    """Return total assembly cost = Σ(item.m2 × price × item.quantity)."""
    total = 0.0
    for item in cleat.items:
        if item.quantity == 0:
            continue
        if getattr(item, "price_source", "standard") == "sap" and item.sap_item:
            price = item.sap_item.last_purch_price
        else:
            price = item.price_per_unit
        total += item.m2 * price * item.quantity
    return round(total, 4)


def _serialize_mounting_cleat(c: MountingCleat) -> dict:
    return {
        "id":          c.id,
        "name":        c.name,
        "group":       c.group,
        "description": c.description or "",
        "is_active":   c.is_active,
        "sort_order":  c.sort_order,
        "cost":        _compute_mounting_cleat_cost(c),
        "items": [
            {
                "id":               it.id,
                "item_name":        it.item_name,
                "sap_code":         it.sap_code or "",
                "sap_item_code_id": it.sap_item_code_id,
                "length":           it.length,
                "width":            it.width,
                "m2":               it.m2,
                "price_per_unit":   it.price_per_unit,
                "price_source":     getattr(it, "price_source", "standard") or "standard",
                "price_sap":        it.sap_item.last_purch_price if it.sap_item else None,
                "quantity":         it.quantity,
                "sort_order":       it.sort_order,
                "line_cost":        round(
                    it.m2 * (
                        it.sap_item.last_purch_price
                        if (getattr(it, "price_source", "standard") == "sap" and it.sap_item)
                        else it.price_per_unit
                    ) * it.quantity, 4
                ),
            }
            for it in c.items
        ],
    }


# ── ORM lookup / create helpers ───────────────────────────────────────────────

def _resolve_body_option_group(db, name: str):
    if not name:
        return None
    grp = db.query(BodyOptionGroup).filter_by(name=name.upper()).first()
    if not grp:
        grp = BodyOptionGroup(name=name.upper(), sort_order=0)
        db.add(grp)
        db.flush()
    return grp.id


def _resolve_body_option_subgroup(db, group_id: int, name: str):
    if not group_id or not name:
        return None
    sub = db.query(BodyOptionSubgroup).filter_by(group_id=group_id, name=name.upper()).first()
    if not sub:
        sub = BodyOptionSubgroup(group_id=group_id, name=name.upper(), sort_order=0)
        db.add(sub)
        db.flush()
    return sub.id


def _resolve_bom_section(db, name: str):
    if not name:
        return None
    sec = db.query(BOMSection).filter_by(name=name).first()
    if not sec:
        sec = BOMSection(name=name, sort_order=0)
        db.add(sec)
        db.flush()
    return sec.id


# ── Chassis cost computation ──────────────────────────────────────────────────

def compute_chassis_cost(db, selection: dict) -> dict:
    """Build chassis line items + subtotal from the calculator's chassis selection."""
    from .database import ChassisOption, ChassisConstant

    length     = float(selection.get("length") or 0)
    axles      = int(selection.get("axle_count") or 0)
    lifts      = int(selection.get("lift_count") or 0)
    tyre_style = selection.get("tyre_style") or "dual"
    per_axle   = 2 if tyre_style == "super_single" else 4
    tyre_count = (axles + lifts) * per_axle

    items: list = []
    subtotal = 0.0

    def add_option(kind_label: str, opt_id, qty: float):
        nonlocal subtotal
        if not opt_id or qty <= 0:
            return
        opt = db.query(ChassisOption).filter_by(id=int(opt_id)).first()
        if not opt:
            return
        unit = float(opt.price or 0)
        line = unit * qty
        items.append({"kind": kind_label, "label": opt.label,
                       "qty": qty, "unit_price": unit, "line_cost": line})
        subtotal += line

    add_option("Suspension", selection.get("suspension_id"), axles)
    add_option("Brake kit",  selection.get("brake_id"),     axles)
    if lifts > 0:
        add_option("Lifting axle", selection.get("lift_type_id"), lifts)
    add_option("Tyre", selection.get("tyre_id"), tyre_count)
    add_option("Rim",  selection.get("rim_id"),  tyre_count)

    consts = db.query(ChassisConstant).filter_by(is_active=True).order_by(
        ChassisConstant.category, ChassisConstant.sort_order, ChassisConstant.name).all()
    for c in consts:
        qty = float(c.qty_per_metre or 0) * length + float(c.qty_constant or 0)
        if qty <= 0:
            continue
        unit = float(c.unit_price or 0)
        line = unit * qty
        items.append({"kind": c.category, "label": c.name,
                       "qty": qty, "unit_price": unit, "line_cost": line})
        subtotal += line

    return {
        "length": length, "axle_count": axles, "lift_count": lifts,
        "tyre_style": tyre_style, "tyre_count": tyre_count,
        "items": items, "subtotal": round(subtotal, 2),
    }


# ── Template assignment helpers ───────────────────────────────────────────────

import re as _re


def _clean_trailer_name_for_archive(name: str) -> str:
    return _re.sub(r"\s*\[deleted-\d+\]\s*$", "", name or "").strip()


def archive_trailer_template_binding(tt, db) -> None:
    from .database import OrphanedTemplateAssignment
    if not tt or (not tt.group_id and not tt.override_report_template_id):
        return None
    clean_name = _clean_trailer_name_for_archive(tt.name)
    if not clean_name:
        return None
    o = OrphanedTemplateAssignment(
        trailer_name=clean_name,
        group_id=tt.group_id,
        override_report_template_id=tt.override_report_template_id,
    )
    db.add(o)
    tt.group_id = None
    tt.override_report_template_id = None
    db.flush()
    return o


def restore_orphan_for_trailer(tt, db):
    from .database import OrphanedTemplateAssignment, TrailerGroup, ReportTemplate
    from sqlalchemy import func as _fn
    if not tt or not tt.name:
        return None
    o = (db.query(OrphanedTemplateAssignment)
           .filter(_fn.lower(OrphanedTemplateAssignment.trailer_name) == tt.name.lower())
           .order_by(OrphanedTemplateAssignment.archived_at.desc())
           .first())
    if not o:
        return None
    if o.group_id and not tt.group_id:
        if db.query(TrailerGroup).filter_by(id=o.group_id).first():
            tt.group_id = o.group_id
    if o.override_report_template_id and not tt.override_report_template_id:
        if db.query(ReportTemplate).filter_by(id=o.override_report_template_id).first():
            tt.override_report_template_id = o.override_report_template_id
    db.delete(o)
    db.flush()
    return o


def resolve_report_template(tt):
    if tt is None:
        return None
    if tt.override_report_template_id and tt.override_template and tt.override_template.is_active:
        return tt.override_template
    if tt.group and tt.group.report_template and tt.group.report_template.is_active:
        return tt.group.report_template
    return None
