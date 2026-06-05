"""live_daily_count + chassis_register — two new icb_mes tables.

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-06

WO v4.22 (Phase 2D-3). Purely ADDITIVE — two new icb_mes tables sourced from the real
ICB workbooks: `live_daily_count` (Stores physical counts, 02 - Live Daily Count) and
`chassis_register` (chassis lifecycle, Book1 TRUCK REGISTER). No destructive changes.

IDEMPOTENT (mirrors 0004's jobs_impacted guard / 0006's column guard): migration 0003
builds the icb_mes tables via model-driven create_all, so on a FRESH DB it already
creates these two (the ProductionJob-package models now declare them); on a DB migrated
at v4.13–v4.21 it does not. The per-table inspector guard converges both paths and keeps
the CI upgrade/downgrade/upgrade round-trip green (the v4.21 lesson).
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect as sa_inspect

revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_TABLES = ["live_daily_count", "chassis_register"]


def _new_table_objs():
    from app.database import Base
    import app.models.mes  # noqa: F401  (registers LiveDailyCount + ChassisRegister)
    return [Base.metadata.tables[f"icb_mes.{n}"] for n in _NEW_TABLES]


def _existing(bind) -> set:
    return set(sa_inspect(bind).get_table_names(schema="icb_mes"))


def upgrade() -> None:
    bind = op.get_bind()
    have = _existing(bind)
    missing = [t for t in _new_table_objs() if t.name not in have]
    if missing:
        from app.database import Base
        Base.metadata.create_all(bind=bind, tables=missing)


def downgrade() -> None:
    bind = op.get_bind()
    have = _existing(bind)
    present = [t for t in _new_table_objs() if t.name in have]
    if present:
        from app.database import Base
        Base.metadata.drop_all(bind=bind, tables=present)
