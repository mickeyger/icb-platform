"""Chassis register API (WO v4.22, §3.3) — read-only chassis lifecycle records.

Prefix is **/api/chassis-register** (not /api/chassis): the costing chassis router
already owns /api/chassis/options, /api/chassis/constants and /api/chassis/catalogue,
so a /api/chassis/{id} route would capture those literal segments. Distinct prefix
avoids the collision (WO §3.3 build-time check).
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import User, get_db
from ..deps import require_user
from ..schemas.chassis_register import ChassisRegisterDetail, ChassisRegisterItem
from ..services import chassis_register as svc
from ..services.errors import NotFoundError

router = APIRouter(prefix="/api/chassis-register", tags=["chassis-register"])


@router.get("", response_model=List[ChassisRegisterItem])
def list_chassis(
    status: Optional[str] = Query(None, description="filter by submit_status"),
    customer: Optional[str] = Query(None, description="customer name contains"),
    make: Optional[str] = Query(None, description="make contains"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    return svc.list_chassis(db, status=status, customer=customer, make=make, limit=limit, offset=offset)


# Declared before /{chassis_id} so the literal segment isn't treated as an id.
@router.get("/by-job/{job_number}", response_model=List[ChassisRegisterDetail])
def chassis_by_job(job_number: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    return svc.by_job(db, job_number)


@router.get("/{chassis_id}", response_model=ChassisRegisterDetail)
def get_chassis(chassis_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    try:
        return svc.get_chassis(db, chassis_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
