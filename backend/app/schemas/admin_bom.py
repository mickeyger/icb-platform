"""WO v4.26 §3.5 — admin CRUD request schemas for the 4 master-data tables.

Create = required writable fields; Update = all-optional (PATCH; only provided fields change).
Audit fields (created_by/at, updated_by/at) are server-set, never trusted from the client.
"""
from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


# ── bom_rules ──
class BomRuleCreate(BaseModel):
    body_type: str
    section: str = "Vacuum Materials"
    panel: str
    output_field: str = "qty"
    formula_expression: str
    priority: int = 100
    notes: Optional[str] = None


class BomRuleUpdate(BaseModel):
    body_type: Optional[str] = None
    section: Optional[str] = None
    panel: Optional[str] = None
    output_field: Optional[str] = None
    formula_expression: Optional[str] = None
    priority: Optional[int] = None
    notes: Optional[str] = None


# ── bom_rule_lookups ──
class BomRuleLookupCreate(BaseModel):
    body_type: str
    section: str = "Vacuum Materials"
    lookup_type: str
    lookup_key: str
    lookup_value: str
    notes: Optional[str] = None


class BomRuleLookupUpdate(BaseModel):
    body_type: Optional[str] = None
    section: Optional[str] = None
    lookup_type: Optional[str] = None
    lookup_key: Optional[str] = None
    lookup_value: Optional[str] = None
    notes: Optional[str] = None


# ── material_price_overrides ──
class MaterialPriceOverrideCreate(BaseModel):
    sap_code: str
    override_price: Decimal
    reason: Optional[str] = None
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None


class MaterialPriceOverrideUpdate(BaseModel):
    sap_code: Optional[str] = None
    override_price: Optional[Decimal] = None
    reason: Optional[str] = None
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None


# ── bom_spec_options ──
class BomSpecOptionCreate(BaseModel):
    spec_field_type: str
    body_type: str = "*"
    section: str = "Vacuum Materials"
    option_label: str
    spec_value: str
    sap_code: Optional[str] = None
    is_default: bool = False
    priority: int = 100
    active: bool = True
    notes: Optional[str] = None


class BomSpecOptionUpdate(BaseModel):
    spec_field_type: Optional[str] = None
    body_type: Optional[str] = None
    section: Optional[str] = None
    option_label: Optional[str] = None
    spec_value: Optional[str] = None
    sap_code: Optional[str] = None
    is_default: Optional[bool] = None
    priority: Optional[int] = None
    active: Optional[bool] = None
    notes: Optional[str] = None
