"""WO v4.26 §3.3 — DDM dropdown→spec resolution (the early-binding entry path).

Turns dropdown labels (`JobSpecRaw`) into a resolved `JobSpec` (spec values the formulas consume).
Per-option `sap_code` is usually NULL: the panel's SAP code early-binds at the (material × thickness)
COMBINATION inside the rules engine's `bom_rule_lookups` step, not on a single dropdown — see ADR 0014.

`resolve_spec` tries the exact `body_type` first, then falls back to `'*'` (cross-body), matching the
DDM reality that most options are field-scoped and body-agnostic.
"""
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.mes import BomSpecOption
from app.schemas.bom import JobSpec, JobSpecRaw, PanelSpec

_SECTION = "Vacuum Materials"
_CROSS = "*"
_NO_SKIN = {"none", "no", "- -", "-", ""}

# Each Vacuum panel → its DDM spec_field_types. 'skin' = the inner reinforcement/plywood layer.
_PANEL_FIELDS = {
    "roof":      {"material": "roof_material",      "thickness": "roof_material_thickness",      "skin": "roof_reinforcement"},
    "sides":     {"material": "side_material",      "thickness": "side_material_thickness",      "skin": "side_reinforcement"},
    "floor":     {"material": "floor_material",     "thickness": "floor_material_thickness",     "skin": "floor_plywood"},
    # The DDM has no front_* column — the front wall inherits the SIDE spec (front is a side-like
    # wall in the Module). Geometry still treats front as a distinct panel (its own qty formula).
    "front":     {"material": "side_material",      "thickness": "side_material_thickness",      "skin": "side_reinforcement"},
    "rear":      {"material": "rear_material",      "thickness": "rear_material_thickness",      "skin": "rear_reinforcement"},
    "partition": {"material": "partition_material", "thickness": "partition_material_thickness", "skin": None},
}


class SpecResolutionError(ValueError):
    """A dropdown selection could not be resolved to a `bom_spec_options` row."""


@dataclass
class ResolvedSpec:
    spec_value: str
    sap_code: Optional[str]
    label: str


def resolve_spec(db: Session, spec_field_type: str, body_type: str, option_label: str) -> ResolvedSpec:
    """Resolve one dropdown selection to (spec_value, sap_code, label).

    Matches `option_label` against a row's `option_label` OR `spec_value` (case-insensitive). Tries
    the exact `body_type`, then `'*'`. Raises `SpecResolutionError` if nothing matches.
    """
    if option_label is None:
        raise SpecResolutionError(f"{spec_field_type}: no selection given")
    target = str(option_label).strip().lower()
    for bt in (body_type, _CROSS):
        rows = db.execute(
            select(BomSpecOption).where(
                BomSpecOption.spec_field_type == spec_field_type,
                BomSpecOption.body_type == bt,
                BomSpecOption.section == _SECTION,
                BomSpecOption.active.is_(True),
            ).order_by(BomSpecOption.priority, BomSpecOption.id)
        ).scalars().all()
        for r in rows:
            if (r.option_label or "").strip().lower() == target or (r.spec_value or "").strip().lower() == target:
                return ResolvedSpec(spec_value=r.spec_value, sap_code=r.sap_code, label=r.option_label)
    raise SpecResolutionError(
        f"no spec option for {spec_field_type}={option_label!r} (body_type={body_type!r} or '*')")


def _to_int(v) -> Optional[int]:
    try:
        return int(float(v)) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def resolve_jobspec_raw(db: Session, raw: JobSpecRaw) -> JobSpec:
    """Resolve a `JobSpecRaw` (dropdown labels) into a resolved `JobSpec`. Absent selections stay
    None (the engine then skips that panel). The panel SAP code is bound later, at the
    (material × thickness) combination, by the rules engine (ADR 0014)."""
    panels = {}
    for panel_name, fmap in _PANEL_FIELDS.items():
        rawp = getattr(raw, panel_name)
        material = thickness = skin = None
        if rawp.material:
            material = resolve_spec(db, fmap["material"], raw.body_type, rawp.material).spec_value
        if rawp.thickness:
            thickness = resolve_spec(db, fmap["thickness"], raw.body_type, rawp.thickness).spec_value
        if rawp.skin and fmap["skin"]:
            sv = resolve_spec(db, fmap["skin"], raw.body_type, rawp.skin).spec_value
            skin = None if (sv or "").strip().lower() in _NO_SKIN else sv
        panels[panel_name] = PanelSpec(thickness_mm=_to_int(thickness), material=material, skin=skin)

    return JobSpec(
        job=raw.job, body_type=raw.body_type,
        length_mm=raw.length_mm, width_mm=raw.width_mm, height_mm=raw.height_mm,
        reveal_top_mm=raw.reveal_top_mm, reveal_side_mm=raw.reveal_side_mm,
        reveal_rear_mm=raw.reveal_rear_mm, reveal_partition_mm=raw.reveal_partition_mm,
        panel_length_mm=raw.panel_length_mm, **panels,
    )
