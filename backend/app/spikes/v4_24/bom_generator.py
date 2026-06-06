"""WO v4.24 spike — orchestrate JobSpec → Vacuum-Materials panel BOM.

spec → geometry (panel-count qtys) → code_lookup (material/thickness → description + SAP code)
→ pricing (icb_sap.OITM.U_LastPurchasePrice) → BomOutput. Stateless (§0.5); no persistence.
Covers the panel-count mechanism only (foam + plywood skins); other Vacuum-section mechanisms
(GRP-area, resin-weight, LVL-count) are out of the spike slice — see the spike report.
"""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from . import code_lookup, geometry, pricing
from .models import BomLine, BomOutput, JobSpec


def _line(db: Session, material, thickness, qty, mechanism, unpriced) -> BomLine:
    desc, code = code_lookup.resolve(material, thickness)
    if desc is None:
        desc = f"{material} {thickness}mm (unmapped — outside ported Freezer-vacuum subset)"
    price = pricing.unit_price(db, code) if code else None
    if code and price is None:
        unpriced.append(code)
    qd = Decimal(str(qty))
    total = (qd * price) if price is not None else None
    return BomLine(material_description=desc, sap_code=code, qty=qd,
                   unit_price=price, line_total=total, mechanism=mechanism)


def generate_bom(spec: JobSpec, db: Session) -> BomOutput:
    lines: list[BomLine] = []
    unpriced: list[str] = []
    L, W, H = spec.length_mm, spec.width_mm, spec.height_mm
    rs, rt, pl = spec.reveal_side_mm, spec.reveal_top_mm, spec.panel_length_mm
    floor_present = spec.floor.thickness_mm is not None

    # ── foam panels (workbook order: roof, floor, sides, front, rear) ──
    foam = []
    if spec.roof.thickness_mm:
        foam.append((spec.roof, geometry.roof_foam_qty(L)))
    if spec.floor.thickness_mm:
        foam.append((spec.floor, geometry.floor_foam_qty(L)))
    if spec.sides.thickness_mm:
        foam.append((spec.sides, geometry.sides_foam_qty(L)))
    if spec.front.thickness_mm:
        foam.append((spec.front, geometry.front_foam_qty(W, rs)))
    if spec.rear.thickness_mm:
        foam.append((spec.rear, geometry.rear_foam_qty(W, rs)))
    for panel, qty in foam:
        lines.append(_line(db, panel.material, panel.thickness_mm, qty, "panel-count/foam", unpriced))

    # ── plywood inner skins (floor, sides, front, rear) ──
    skins = []
    if spec.floor.skin:
        mat, thk = code_lookup.skin_material(spec.floor.skin)
        skins.append((mat, thk, geometry.floor_skin_qty(L, W, pl)))
    if spec.sides.skin:
        mat, thk = code_lookup.skin_material(spec.sides.skin)
        skins.append((mat, thk, geometry.sides_skin_qty(L, H, rt, floor_present, pl)))
    if spec.front.skin:
        mat, thk = code_lookup.skin_material(spec.front.skin)
        skins.append((mat, thk, geometry.front_skin_qty(W, H, rs, rt, floor_present, pl)))
    if spec.rear.skin:
        mat, thk = code_lookup.skin_material(spec.rear.skin)
        skins.append((mat, thk, geometry.rear_skin_qty(W, rs)))
    for mat, thk, qty in skins:
        lines.append(_line(db, mat, thk, qty, "panel-count/skin", unpriced))

    grand = sum((ln.line_total for ln in lines if ln.line_total is not None), Decimal("0"))
    return BomOutput(
        job_spec_echo=spec, lines=lines,
        grand_total=grand, unpriced_codes=sorted(set(unpriced)),
        generated_at=datetime.now(timezone.utc),
    )
