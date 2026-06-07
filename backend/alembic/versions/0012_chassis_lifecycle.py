"""chassis lifecycle tables + production_jobs.chassis_record_id (WO v4.28, Phase 3 §4.2).

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-06

Additive:
  * NEW icb_mes.chassis_records (VIN-anchored) + chassis_lifecycle_events (per-cycle VCL/DCL) +
    chassis_photos.
  * production_jobs.chassis_record_id (FK -> chassis_records, nullable, ON DELETE RESTRICT).
The v4.22 `chassis_register` table is UNTOUCHED (kept for rollback; the translation script reads it).

IDEMPOTENT (mirrors 0007/0009/0010/0011): 0003's model-driven create_all builds the icb_mes tables on
a FRESH DB, so the three new tables + the new production_jobs column already exist there; every add
guards on existence. The chassis_record_id FK is NOT on the model (column-on-model / FK-in-migration,
the same idiom as 0011's current_bom FK) and is always created here, guarded by constraint name —
keeping the CI upgrade->downgrade->upgrade round-trip green.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision: str = '0012'
down_revision: Union[str, Sequence[str], None] = '0011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_TABLES = ["chassis_records", "chassis_lifecycle_events", "chassis_photos"]
_PJ_FK = "fk_production_jobs_chassis_record"


def _new_table_objs():
    from app.database import Base
    import app.models.mes  # noqa: F401  (registers ChassisRecord/Event/Photo)
    return [Base.metadata.tables[f"icb_mes.{n}"] for n in _NEW_TABLES]


def _tables(bind) -> set:
    return set(sa_inspect(bind).get_table_names(schema="icb_mes"))


def _pj_cols(bind) -> set:
    return {c["name"] for c in sa_inspect(bind).get_columns("production_jobs", schema="icb_mes")}


def _pj_fks(bind) -> set:
    return {fk["name"] for fk in sa_inspect(bind).get_foreign_keys("production_jobs", schema="icb_mes")}


def upgrade() -> None:
    bind = op.get_bind()
    have = _tables(bind)

    # 1) New chassis tables (guard: 0003 create_all already builds them on a fresh DB).
    missing = [t for t in _new_table_objs() if t.name not in have]
    if missing:
        from app.database import Base
        Base.metadata.create_all(bind=bind, tables=missing)

    # 2) production_jobs.chassis_record_id (guard: model-declared → present on a fresh DB).
    if "chassis_record_id" not in _pj_cols(bind):
        op.add_column("production_jobs", sa.Column("chassis_record_id", sa.Integer(), nullable=True),
                      schema="icb_mes")

    # 3) production_jobs.chassis_record_id -> chassis_records.id (NOT on the model; created here,
    #    guarded by name). ON DELETE RESTRICT: a chassis referenced by a job can't be deleted.
    if "chassis_records" in _tables(bind) and _PJ_FK not in _pj_fks(bind):
        op.create_foreign_key(
            _PJ_FK, "production_jobs", "chassis_records",
            ["chassis_record_id"], ["id"],
            source_schema="icb_mes", referent_schema="icb_mes", ondelete="RESTRICT",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "production_jobs" in _tables(bind):
        if _PJ_FK in _pj_fks(bind):
            op.drop_constraint(_PJ_FK, "production_jobs", schema="icb_mes", type_="foreignkey")
        if "chassis_record_id" in _pj_cols(bind):
            op.drop_column("production_jobs", "chassis_record_id", schema="icb_mes")
    have = _tables(bind)
    present = [t for t in _new_table_objs() if t.name in have]
    if present:
        from app.database import Base
        Base.metadata.drop_all(bind=bind, tables=present)
