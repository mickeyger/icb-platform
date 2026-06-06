"""WO v4.25 §3.3 — the rules engine: JobSpec → Vacuum-Materials panel BOM.

Loads icb_mes.bom_rules (ordered by priority), builds a flat evaluation context from the
resolved JobSpec (+ derived helpers like `floor_present`), gates each rule by panel presence,
evaluates the qty formula via the AST-safe evaluator, resolves the SAP code + description via
icb_mes.bom_rule_lookups, and prices via the hybrid pricing service (override → OITM).

Two engine conventions (flagged in the WO as v4.26 data-drive candidates):
  * `bom_rules.panel` carries the foam/skin layer, e.g. 'Floor (foam)' / 'Floor (skin)';
    `_panel_face_layer` parses it to (spec face, layer).
  * inner-skin spec strings ('12mm finn' …) → (material, thickness) via `_SKIN_SPEC`.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.mes import BomRule, BomRuleLookup
from app.schemas.bom import BomLine, BomOutput, JobSpec
from . import pricing
from .evaluator import evaluate

_SECTION = "Vacuum Materials"

# inner-skin spec → (material, thickness_mm). Engine logic (v4.26 data-drive candidate).
_SKIN_SPEC = {
    "12mm finn": ("FINN PLY", 12),
    "4mm plywood": ("PLY", 4),
    "6mm plywood": ("PLY", 6),
}


def _panel_face_layer(panel_label: str) -> Tuple[str, str]:
    """'Floor (foam)' -> ('floor', 'foam'); 'Roof (skin)' -> ('roof', 'skin');
    'Roof' -> ('roof', 'foam') (default layer)."""
    label = panel_label.strip()
    if "(" in label:
        face, _, rest = label.partition("(")
        return face.strip().lower(), rest.rstrip(")").strip().lower()
    return label.lower(), "foam"


def _skin_material(skin_spec) -> Tuple:
    if not skin_spec:
        return None, None
    return _SKIN_SPEC.get(str(skin_spec).strip().lower(), (None, None))


class RulesEngine:
    def __init__(self, db: Session):
        self.db = db

    def _load_rules(self, body_type: str):
        return self.db.execute(
            select(BomRule)
            .where(BomRule.body_type == body_type, BomRule.section == _SECTION,
                   BomRule.output_field == "qty")
            .order_by(BomRule.priority, BomRule.id)
        ).scalars().all()

    def _load_lookups(self, body_type: str) -> Dict[str, Tuple[str, str]]:
        rows = self.db.execute(
            select(BomRuleLookup).where(
                BomRuleLookup.body_type == body_type, BomRuleLookup.section == _SECTION,
                BomRuleLookup.lookup_type == "spec_to_sap_code")
        ).scalars().all()
        return {r.lookup_key: (r.lookup_value, r.notes) for r in rows}

    @staticmethod
    def _context(spec: JobSpec) -> dict:
        """Flat evaluation context: top-level spec fields + derived helpers the formulas use."""
        return {
            "length_mm": spec.length_mm, "width_mm": spec.width_mm, "height_mm": spec.height_mm,
            "reveal_top_mm": spec.reveal_top_mm, "reveal_side_mm": spec.reveal_side_mm,
            "reveal_rear_mm": spec.reveal_rear_mm, "reveal_partition_mm": spec.reveal_partition_mm,
            "panel_length_mm": spec.panel_length_mm,
            "floor_present": spec.floor.thickness_mm is not None,
        }

    def _material_for(self, spec: JobSpec, face: str, layer: str):
        panel = getattr(spec, face, None)
        if panel is None:
            return None, None, False
        if layer == "skin":
            mat, thk = _skin_material(panel.skin)
            return mat, thk, (panel.skin is not None)
        return panel.material, panel.thickness_mm, (panel.thickness_mm is not None)

    def generate_bom(self, spec: JobSpec) -> BomOutput:
        rules = self._load_rules(spec.body_type)
        lookups = self._load_lookups(spec.body_type)
        ctx = self._context(spec)
        lines, unpriced = [], []

        for rule in rules:
            face, layer = _panel_face_layer(rule.panel)
            material, thickness, present = self._material_for(spec, face, layer)
            if not present:
                continue  # panel/skin absent for this spec
            qty = evaluate(rule.formula_expression, ctx)
            if qty is None or qty <= 0:
                continue
            key = f"{material}|{thickness}"
            sap_code, desc = lookups.get(key, (None, None))
            if desc is None:
                desc = f"{material} {thickness}mm ({rule.panel})"
            price, source = pricing.get_price(self.db, sap_code) if sap_code else (None, None)
            if sap_code and price is None:
                unpriced.append(sap_code)
            qd = Decimal(str(qty))
            total = (qd * price) if price is not None else None
            lines.append(BomLine(
                material_description=desc, sap_code=sap_code, qty=qd,
                unit_price=price, line_total=total, section=_SECTION, price_source=source,
            ))

        grand = sum((ln.line_total for ln in lines if ln.line_total is not None), Decimal("0"))
        return BomOutput(
            job_spec_echo=spec, lines=lines,
            grand_total=grand, unpriced_codes=sorted(set(unpriced)),
            generated_at=datetime.now(timezone.utc),
        )
