"""WO v4.35 §3.3b (STRETCH) — production_job_bay_events (job-centric bay events) (Migration 0024).

Revision ID: 0024
Revises: 0023
Create Date: 2026-06-16

Adds icb_mes.production_job_bay_events — the JOB-side of the body↔chassis merge: a job's panels arrive
in an assembly bay ('panels_arrived_in_bay'). Distinct table from chassis_lifecycle_events (chassis-
centric) by design (ADR 0025 footnote C — audit/event tables scoped by entity). Same-schema FKs
(production_job_id, bay_id → icb_mes, ON DELETE CASCADE) ride on the model + create_all; the cross-schema
user_id → icb_costings.users FK (SET NULL) is created here, mirroring 0023.

Inspector-guarded; up→down→up round-trips clean (0024 is head; downgrade drops the user FK then the table).
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect as sa_inspect

revision: str = "0024"
down_revision: Union[str, Sequence[str], None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MES = "icb_mes"
_TABLE = "production_job_bay_events"
_USER_FK = "fk_production_job_bay_events_user"


def _mes_tables(bind) -> set:
    return set(sa_inspect(bind).get_table_names(schema=MES))


def _fks(bind, table) -> set:
    return {fk["name"] for fk in sa_inspect(bind).get_foreign_keys(table, schema=MES)}


def upgrade() -> None:
    bind = op.get_bind()

    if _TABLE not in _mes_tables(bind):
        from app.database import Base
        import app.models.mes  # noqa: F401 — registers ProductionJobBayEvent
        Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables[f"{MES}.{_TABLE}"]])

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
