"""WO v4.33 — Pre-Job Card schemas (templates §3.3; cards follow in §3.4).

The §0.5 sections shape is validated HERE (pydantic), so every writer — admin editor, import
script callers, the §3.4 modal — gets the same 422s for malformed sections: a list of
{name, items:[{text, note?, sub_items?[], sap_item_code?}]} with non-empty names/texts.
sap_item_code is the §0.10 stub (no lookup until v4.33.1).
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SectionItem(BaseModel):
    text: str = Field(..., min_length=1)
    note: Optional[str] = None
    sub_items: Optional[List[str]] = None
    sap_item_code: Optional[str] = None               # §0.10 capability stub

    @field_validator("sub_items")
    @classmethod
    def _no_empty_sub_items(cls, v):
        if v is not None and any(not (s or "").strip() for s in v):
            raise ValueError("sub_items entries must be non-empty")
        return v


class Section(BaseModel):
    name: str = Field(..., min_length=1)
    items: List[SectionItem] = []


class PrejobTemplateListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    body_type: str
    size_category: Optional[str] = None
    product_line: str
    is_active: bool
    version: int
    updated_at: Optional[datetime] = None
    updated_by: Optional[str] = None
    section_names: List[str] = []                      # derived for the list view
    item_count: int = 0


class PrejobTemplateOut(PrejobTemplateListItem):
    header_format: Optional[str] = None
    default_fridge_note: Optional[str] = None
    sections: List[Section] = []
    created_at: Optional[datetime] = None
    created_by: Optional[str] = None


class PrejobTemplateUpdate(BaseModel):
    name: Optional[str] = None
    body_type: Optional[str] = None
    size_category: Optional[str] = None
    product_line: Optional[str] = None
    header_format: Optional[str] = None
    default_fridge_note: Optional[str] = None
    sections: Optional[List[Section]] = None


# ── §3.4 — Pre-Job Card instances ─────────────────────────────────────────────
class TemplateOption(BaseModel):
    id: int
    name: str
    body_type: str
    size_category: Optional[str] = None
    product_line: str
    suggested: bool = False


class UserOption(BaseModel):
    id: int
    username: str
    role: str


class PrejobCardCreate(BaseModel):
    calculation_id: int
    template_id: int


class PrejobCardUpdate(BaseModel):
    """Draft-only edits (the service 409s otherwise). Switching template_id re-seeds sections."""
    body_description: Optional[str] = None
    chassis_make_model: Optional[str] = None
    vin_number: Optional[str] = None
    body_gap_mm: Optional[int] = None
    sections: Optional[List[Section]] = None
    fridge_ordering_mode: Optional[str] = Field(None, pattern="^(icb_orders|customer_supplies|none)$")
    fridge_model: Optional[str] = None
    customer_notes: Optional[str] = None
    sales_rep_user_id: Optional[int] = None
    planner_user_id: Optional[int] = None
    template_id: Optional[int] = None


class SubmitForCheck(BaseModel):
    waive_body_gap: bool = False                       # §0.8 explicit waiver


class SignOffRequest(BaseModel):
    attestation: str = Field(..., min_length=1)        # §0.12 — free-text attestation


class RejectRequest(BaseModel):
    reason: str = Field(..., min_length=1)             # §0.14 — captured onto the card


class PrejobCardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    calculation_id: int
    template_id: Optional[int] = None
    body_description: Optional[str] = None
    chassis_make_model: Optional[str] = None
    vin_number: Optional[str] = None
    body_gap_mm: Optional[int] = None
    body_gap_pending: bool
    sections: List[Section] = []
    fridge_ordering_mode: Optional[str] = None
    fridge_model: Optional[str] = None
    customer_notes: Optional[str] = None
    created_by_user_id: Optional[int] = None
    sales_rep_user_id: Optional[int] = None
    sales_rep_signoff_at: Optional[datetime] = None
    sales_rep_attestation: Optional[str] = None
    planner_user_id: Optional[int] = None
    planner_signoff_at: Optional[datetime] = None
    planner_attestation: Optional[str] = None
    status: str                                        # draft | sent_for_check | pre_job_confirmed
    sent_for_check_at: Optional[datetime] = None
    reject_reason: Optional[str] = None
    pdf_file_id: Optional[str] = None                  # records-copy snapshot (set at submit, §3.6)
    version: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # resolved display fields (router fills)
    quote_number: Optional[str] = None
    customer_name: Optional[str] = None
    template_name: Optional[str] = None
    sales_rep_username: Optional[str] = None
    planner_username: Optional[str] = None
    created_by_username: Optional[str] = None
