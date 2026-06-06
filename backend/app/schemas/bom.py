"""WO v4.25 — BOM generation schemas (production home for the spike's shapes).

Same JobSpec / BomLine / BomOutput shapes as the v4.24 spike (§0.8: same endpoint contract),
now the production schema. The spike's `app/spikes/v4_24/models.py` stays committed as the
parity-oracle reference; this is what `POST /api/bom/generate` (rules-engine-backed) uses.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class PanelSpec(BaseModel):
    thickness_mm: Optional[int] = None       # foam thickness (None ⇒ panel absent)
    material: Optional[str] = None           # e.g. "EPS 24DV", "PU 32DV"
    skin: Optional[str] = None               # inner skin spec, e.g. "12mm finn", "4mm plywood"


class JobSpec(BaseModel):
    job: Optional[int] = None
    body_type: Literal["Freezer"]            # v4.25 scope (§0.7)
    length_mm: int
    width_mm: int
    height_mm: int
    roof: PanelSpec
    sides: PanelSpec
    floor: PanelSpec
    front: PanelSpec
    rear: PanelSpec
    partition: PanelSpec = PanelSpec()
    reveal_top_mm: int = 81
    reveal_side_mm: int = 65
    reveal_rear_mm: int = 93
    reveal_partition_mm: int = 56
    panel_length_mm: int = 2440              # 'New Prep'!AO8 resolution (spike boundary)


class BomLine(BaseModel):
    material_description: str
    sap_code: Optional[str] = None
    qty: Decimal
    unit_price: Optional[Decimal] = None
    line_total: Optional[Decimal] = None
    section: str = "Vacuum Materials"
    price_source: Optional[str] = None       # 'override' | 'sap' | None (WO v4.25 §0.5)


class BomOutput(BaseModel):
    job_spec_echo: JobSpec
    lines: List[BomLine] = Field(default_factory=list)
    grand_total: Optional[Decimal] = None
    unpriced_codes: List[str] = Field(default_factory=list)
    generated_at: datetime
    engine: str = "rules-table-v4.25"


# ── read-only admin inspection schemas (WO v4.25 §3.7) ──
class BomRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    body_type: str
    section: str
    panel: str
    output_field: str
    formula_expression: str
    priority: int
    notes: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None


class BomRuleLookupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    body_type: str
    section: str
    lookup_type: str
    lookup_key: str
    lookup_value: str
    notes: Optional[str] = None


class MaterialPriceOverrideOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sap_code: str
    override_price: Decimal
    reason: Optional[str] = None
    valid_from: date
    valid_to: Optional[date] = None
    created_by: Optional[str] = None
