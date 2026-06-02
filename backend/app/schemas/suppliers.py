"""Supplier schemas (WO v4.15, ADR 0008).

GET /api/suppliers — read-only supplier master (the PO Suggestion Queue's
override dropdown + contact line consume this). Q4 lock: standalone endpoint.
"""
from typing import Optional

from pydantic import BaseModel, ConfigDict


class SupplierListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    contact_person: Optional[str] = None
    payment_terms: Optional[str] = None
    phone: Optional[str] = None
