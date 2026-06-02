"""`/api/suppliers` — read-only supplier master (WO v4.15, ADR 0008, Q4).

The PO Suggestion Queue's override dropdown + contact line consume this.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import User, get_db
from ..deps import require_user
from ..schemas.suppliers import SupplierListItem
from ..services import suppliers as svc

router = APIRouter(prefix="/api/suppliers", tags=["suppliers"])


@router.get("", response_model=list[SupplierListItem])
def list_suppliers(db: Session = Depends(get_db), user: User = Depends(require_user)):
    """List all suppliers (by name)."""
    return svc.list_suppliers(db)
