"""WO v4.25 §3.5/§3.7 — production BOM generate + read-only admin inspection.

Replaces the v4.24 spike router (`app/spikes/v4_24/router.py`) — same `POST /api/bom/generate`
contract (JobSpec → BomOutput), now rules-engine-backed (icb_mes.bom_rules + lookups +
material_price_overrides → icb_sap.OITM). Plus read-only admin GETs for inspecting the
seeded rules / lookups / overrides (full CRUD deferred to v4.26). icb_sap stays read-only
(ADR 0013); endpoint is stateless (no persistence).
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import User, get_db
from ..deps import require_admin, require_user
from ..models.mes import BomRule, BomRuleLookup, MaterialPriceOverride
from ..schemas.bom import (
    BomOutput, BomRuleLookupOut, BomRuleOut, JobSpec, MaterialPriceOverrideOut,
)
from ..services.rules_engine.engine import RulesEngine

router = APIRouter(tags=["bom"])


@router.post("/api/bom/generate", response_model=BomOutput)
def generate_bom(spec: JobSpec, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Generate the Vacuum-Materials panel BOM for a resolved Freezer job spec (rules engine)."""
    return RulesEngine(db).generate_bom(spec)


@router.get("/api/admin/bom-rules", response_model=List[BomRuleOut])
def list_bom_rules(
    body_type: Optional[str] = Query(None),
    section: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    stmt = select(BomRule)
    if body_type:
        stmt = stmt.where(BomRule.body_type == body_type)
    if section:
        stmt = stmt.where(BomRule.section == section)
    stmt = stmt.order_by(BomRule.body_type, BomRule.section, BomRule.priority, BomRule.id)
    return db.execute(stmt).scalars().all()


@router.get("/api/admin/bom-rule-lookups", response_model=List[BomRuleLookupOut])
def list_bom_rule_lookups(
    body_type: Optional[str] = Query(None),
    section: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    stmt = select(BomRuleLookup)
    if body_type:
        stmt = stmt.where(BomRuleLookup.body_type == body_type)
    if section:
        stmt = stmt.where(BomRuleLookup.section == section)
    stmt = stmt.order_by(BomRuleLookup.body_type, BomRuleLookup.section,
                         BomRuleLookup.lookup_type, BomRuleLookup.lookup_key)
    return db.execute(stmt).scalars().all()


@router.get("/api/admin/material-price-overrides", response_model=List[MaterialPriceOverrideOut])
def list_material_price_overrides(
    sap_code: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    stmt = select(MaterialPriceOverride)
    if sap_code:
        stmt = stmt.where(MaterialPriceOverride.sap_code == sap_code)
    stmt = stmt.order_by(MaterialPriceOverride.sap_code, MaterialPriceOverride.valid_from.desc())
    return db.execute(stmt).scalars().all()
