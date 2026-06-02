"""`/api/mes-materials/*` — MES materials catalogue + stock (WO v4.15, ADR 0008).

NB on the URL: the WO named this `/api/materials`, but the existing costing
materials admin (`routers/materials.py`) already owns `/api/materials` (GET list +
`/api/materials/{mat_id}` and bulk-price endpoints), registered earlier — it would
shadow these routes (a string sap_code would hit the int `{mat_id}` route → 422).
So the MES catalogue API is exposed at `/api/mes-materials` (module + table also
`mes_materials`). The costing surface is untouched. Handlers delegate to the service.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import User, get_db
from ..deps import require_user
from ..schemas.materials import MaterialDetail, MaterialListItem
from ..services import materials as svc

router = APIRouter(prefix="/api/mes-materials", tags=["mes-materials"])


@router.get("", response_model=list[MaterialListItem])
def list_materials(
    dept: Optional[str] = Query(None, description="Filter by department (vacuum|panelshop|assy|paint)"),
    abc_class: Optional[str] = Query(None, description="Filter by ABC class (A|B|C)"),
    low_stock: bool = Query(False, description="Only items with no free stock (free <= 0)"),
    branch_id: Optional[int] = Query(None, description="Accepted but no-op: stock is not branch-scoped (v4.16)"),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Materials catalogue joined to current stock position (+ cross-schema costing price)."""
    return svc.list_materials(db, dept=dept, abc_class=abc_class, low_stock=low_stock, branch_id=branch_id)


@router.get("/{sap_code}", response_model=MaterialDetail)
def get_material(sap_code: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Catalogue + current stock + recent (last 5) stock counts for one material."""
    try:
        return svc.get_material(db, sap_code)
    except svc.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
