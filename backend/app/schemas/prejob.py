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
