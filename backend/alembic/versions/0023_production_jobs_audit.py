"""WO v4.34.2 §3.1 — production_jobs_audit (workflow state-transition trail) (Migration 0023).

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-15

Adds icb_mes.production_jobs_audit — an append-only trail for production-job workflow transitions.
First (and, in v4.34.2, only) consumer: the scheduled → unscheduled revert. The same-schema FK
production_job_id → icb_mes.production_jobs (ON DELETE RESTRICT — audit history is sacred) rides on
the model and is built by create_all; the cross-schema user_id → icb_costings.users FK (SET NULL — the
trail survives a user delete) is created here, mirroring the 0017 prejob-card user-FK pattern (so it is
NOT added to CROSS_SCHEMA_FKS, which 0003 consumes before this table exists).

Inspector-guarded throughout; up→down→up round-trips clean (0023 is the head, so downgrade drops the
audit table before any earlier migration drops production_jobs — no RESTRICT violation).
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect as sa_inspect

revision: str = "0023"
down_revision: Union[str, Sequence[str], None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MES = "icb_mes"
_TABLE = "production_jobs_audit"
_USER_FK = "fk_production_jobs_audit_user"


def _mes_tables(bind) -> set:
    return set(sa_inspect(bind).get_table_names(schema=MES))


def _fks(bind, table) -> set:
    return {fk["name"] for fk in sa_inspect(bind).get_foreign_keys(table, schema=MES)}


def upgrade() -> None:
    bind = op.get_bind()

    # 1. create the table (model-declared; guard for the 0003 create_all path on a fresh DB).
    #    create_all builds the same-schema production_job_id FK + the two indexes inline.
    if _TABLE not in _mes_tables(bind):
        from app.database import Base
        import app.models.mes  # noqa: F401 — registers ProductionJobAudit on Base.metadata
        Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables[f"{MES}.{_TABLE}"]])

    # 2. cross-schema user_id FK → icb_costings.users (SET NULL — the trail outlives a user delete).
    if _USER_FK not in _fks(bind, _TABLE):
        op.create_foreign_key(
            _USER_FK, _TABLE, "users", ["user_id"], ["id"],
            source_schema=MES, referent_schema="icb_costings", ondelete="SET NULL")


def downgrade() -> None:
    bind = op.get_bind()
    if _USER_FK in _fks(bind, _TABLE):
        op.drop_constraint(_USER_FK, _TABLE, schema=MES, type_="foreignkey")
    if _TABLE in _mes_tables(bind):
        op.drop_table(_TABLE, schema=MES)
