"""Chassis register reads (WO v4.22, §3.3). Read-only — the table is populated
only by the import_workbook ETL; the API never mutates it.
"""
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.mes import ChassisRegister
from app.schemas.chassis_register import ChassisRegisterDetail, ChassisRegisterItem
from app.services.errors import NotFoundError


def list_chassis(db: Session, *, status: Optional[str] = None, customer: Optional[str] = None,
                 make: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[ChassisRegisterItem]:
    stmt = select(ChassisRegister)
    if status:
        stmt = stmt.where(ChassisRegister.submit_status == status)
    if customer:
        stmt = stmt.where(ChassisRegister.customer_name.ilike(f"%{customer}%"))
    if make:
        stmt = stmt.where(ChassisRegister.make.ilike(f"%{make}%"))
    stmt = stmt.order_by(ChassisRegister.id).limit(limit).offset(offset)
    return [ChassisRegisterItem.model_validate(r) for r in db.execute(stmt).scalars().all()]


def get_chassis(db: Session, chassis_id: int) -> ChassisRegisterDetail:
    row = db.get(ChassisRegister, chassis_id)
    if row is None:
        raise NotFoundError(f"chassis register {chassis_id} not found")
    return ChassisRegisterDetail.model_validate(row)


def by_job(db: Session, job_number: str) -> List[ChassisRegisterDetail]:
    stmt = (select(ChassisRegister)
            .where(ChassisRegister.job_number == job_number)
            .order_by(ChassisRegister.id))
    return [ChassisRegisterDetail.model_validate(r) for r in db.execute(stmt).scalars().all()]
