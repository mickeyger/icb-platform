"""WO v4.27 §3.4/§3.5 — BOM-on-accept: generate + persist an immutable, versioned BOM when a
production job is accepted.

Defaults-fill (Option A, BA-locked): the accepted calc carries dimensions + a trailer_type but NOT
per-panel material selections (the costing wizard that captures those is a separate WO). So body_type
is derived from the trailer_type (locked keyword map) and panels are filled from the DDM defaults
(`bom_spec_options.is_default`) → tagged `metadata_json.spec_source='defaults'` so it self-upgrades
once the wizard captures real selections.

Per §0.5 an incomplete BOM (unmapped body type, missing dims, no geometry, or any generation error)
STILL persists — with a reason in `metadata_json` — and NEVER blocks the accept transition. Each call
creates a new version and flips `current`, so a re-accept versions cleanly.
"""
import json
from typing import Optional

from sqlalchemy import func, select, text as sa_text, update
from sqlalchemy.orm import Session

from app.database import CalculationRecord
from app.models.mes import BomLine, GeneratedBom
from app.services.rules_engine.body_type_map import map_trailer_type
from app.services.rules_engine.ddm_resolver import default_jobspec_raw, resolve_jobspec_raw
from app.services.rules_engine.engine import RulesEngine


def _trailer_type_name(db: Session, calc) -> Optional[str]:
    if calc is None or calc.trailer_type_id is None:
        return None
    row = db.execute(sa_text("SELECT name FROM icb_costings.trailer_types WHERE id = :id"),
                     {"id": calc.trailer_type_id}).first()
    return row[0] if row else None


def _dims_mm(calc) -> Optional[dict]:
    """Calc dimensions_json (metres) → {length_mm,width_mm,height_mm}; None if unusable."""
    if calc is None or not calc.dimensions_json:
        return None
    try:
        d = json.loads(calc.dimensions_json)
    except (ValueError, TypeError):
        return None

    def mm(key):
        v = d.get(key)
        try:
            return int(round(float(v) * 1000)) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    out = {"length_mm": mm("length"), "width_mm": mm("width"), "height_mm": mm("height")}
    return out if all(out.values()) else None


def _next_version(db: Session, job_id: int) -> int:
    mx = db.execute(
        select(func.max(GeneratedBom.version)).where(GeneratedBom.production_job_id == job_id)
    ).scalar()
    return (mx or 0) + 1


def _persist(db: Session, job, *, bom_status: str, grand_total, lines, metadata) -> GeneratedBom:
    """Flip the job's current BOM off, insert a new current version + its lines, update the job."""
    db.execute(
        update(GeneratedBom)
        .where(GeneratedBom.production_job_id == job.id, GeneratedBom.current.is_(True))
        .values(current=False)
    )
    db.flush()
    gb = GeneratedBom(
        production_job_id=job.id, version=_next_version(db, job.id), bom_status=bom_status,
        grand_total=grand_total, current=True, metadata_json=metadata, generated_by="bom_on_accept",
    )
    db.add(gb)
    db.flush()
    for i, ln in enumerate(lines):
        db.add(BomLine(
            generated_bom_id=gb.id, sap_code=(ln.sap_code or "UNRESOLVED"),
            description=ln.material_description, qty=ln.qty, unit_price=ln.unit_price,
            line_total=ln.line_total, section=ln.section, source="rule",
            price_source=ln.price_source, line_order=i,
        ))
    job.current_bom_id = gb.id
    job.bom_status = bom_status
    db.flush()
    return gb


def generate_and_persist_bom(db: Session, job) -> GeneratedBom:
    """Generate + persist a new current BOM version for `job`. Never raises into the caller's
    transaction — failures persist an 'incomplete' BOM with a metadata reason (§0.5). Does NOT
    commit (the caller owns the transaction)."""
    meta: dict = {"spec_source": "defaults"}
    calc = db.get(CalculationRecord, job.calculation_record_id) if job.calculation_record_id else None
    try:
        if calc is None:
            meta["reason"] = "no_calculation"   # e.g. workbook-imported job (no originating calc)
            return _persist(db, job, bom_status="incomplete", grand_total=None, lines=[], metadata=meta)
        tt_name = _trailer_type_name(db, calc)
        body_type = map_trailer_type(tt_name)
        if body_type is None:
            meta.update(reason="body_type_unmapped", trailer_type=tt_name)
            return _persist(db, job, bom_status="incomplete", grand_total=None, lines=[], metadata=meta)
        meta["body_type"] = body_type

        dims = _dims_mm(calc)
        if dims is None:
            meta["reason"] = "no_dimensions"
            return _persist(db, job, bom_status="incomplete", grand_total=None, lines=[], metadata=meta)

        raw = default_jobspec_raw(db, body_type, job=None, **dims)
        spec = resolve_jobspec_raw(db, raw)
        out = RulesEngine(db).generate_bom(spec)

        # 'complete' only when every line bound a real SAP code with a price. The defaults baseline
        # typically yields structure (panels + quantities) but unresolved codes — honestly
        # 'incomplete' until the costing wizard feeds real per-panel selections (then it self-upgrades).
        meta["lines"] = len(out.lines)
        n_codeless = sum(1 for ln in out.lines if not ln.sap_code)
        if not out.lines:
            status = "incomplete"
            meta["reason"] = "no_geometry_lines"          # e.g. Explosive (NOT AVAILABLE)
        elif n_codeless or out.unpriced_codes:
            status = "incomplete"
            meta["reason"] = "unresolved_or_unpriced_codes"
            if n_codeless:
                meta["unresolved_code_lines"] = n_codeless
            if out.unpriced_codes:
                meta["unpriced_codes"] = list(out.unpriced_codes)
        else:
            status = "complete"
        return _persist(db, job, bom_status=status, grand_total=out.grand_total,
                        lines=out.lines, metadata=meta)
    except Exception as exc:   # noqa: BLE001 — §0.5: an error must NOT block the accept
        meta.update(reason="generation_error", error=str(exc)[:300])
        return _persist(db, job, bom_status="incomplete", grand_total=None, lines=[], metadata=meta)
