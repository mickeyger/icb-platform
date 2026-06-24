"""WO v4.38 — feedback_submissions (Feedback Portal in-app issue reports) (Migration 0027).

Revision ID: 0027
Revises: 0026
Create Date: 2026-06-24

Threaded onto CA1's v4.36b 0026_chassis_tail_lift_code once v4.36b landed on main — chain
0024->0025->0026->0027 (WO v4.38 §3.0 / BA Ask-2 Option A). Adds icb_mes.feedback_submissions
(model-declared in app.models.mes; created via create_all here, inspector-guarded) + the
cross-schema user_id -> icb_costings.users FK (SET NULL — a ticket outlives a user delete),
mirroring 0023's audit-table user-FK pattern (NOT added to CROSS_SCHEMA_FKS, which migration
0003 consumes before this table exists). Inspector-guarded; up->down->up round-trips clean.

This adds an icb_mes table, so tests/test_smoke.py's icb_mes table-count assertion rises
35 -> 36 (bumped in the same commit).
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect as sa_inspect

revision: str = "0027"
down_revision: Union[str, Sequence[str], None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MES = "icb_mes"
_TABLE = "feedback_submissions"
_USER_FK = "fk_feedback_submissions_user"


def _mes_tables(bind) -> set:
    return set(sa_inspect(bind).get_table_names(schema=MES))


def _fks(bind, table) -> set:
    return {fk["name"] for fk in sa_inspect(bind).get_foreign_keys(table, schema=MES)}


def upgrade() -> None:
    bind = op.get_bind()

    # 1. create the table (model-declared; the two indexes ride on create_all).
    if _TABLE not in _mes_tables(bind):
        from app.database import Base
        import app.models.mes  # noqa: F401 — registers FeedbackSubmission on Base.metadata
        Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables[f"{MES}.{_TABLE}"]])

    # 2. cross-schema user_id FK -> icb_costings.users (SET NULL — the ticket outlives a user delete).
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
