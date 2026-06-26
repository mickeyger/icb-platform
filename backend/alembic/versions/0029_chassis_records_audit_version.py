"""WO v4.36.5 §3.1 — chassis_records_audit + chassis_records.version (Migration 0029).

Revision ID: 0029
Revises: 0028  (re-pointed from the 0027 placeholder when v4.36c landed — ship-order swap)
Create Date: 2026-06-25

⚠ down_revision is a PLACEHOLDER. Per the 2026-06-25 ship-order swap this chains off CA1's v4.36c
   `0028`, which is not yet on main (v4.36c starts Mon 29 Jun). It is built off `0027` so this
   branch's CI is green now; **rebase down_revision "0027" → "0028" when v4.36c lands on main**
   (the v4.38 `0026→0027` dance), then `alembic upgrade head`. Surface hold-vs-placeholder at the
   §3.1 checkpoint. NOTE: if v4.36c's `0028` also adds an icb_mes table, reconcile test_smoke at
   rebase time (this commit bumps 36→37 for chassis_records_audit alone, correct for the 0027 base).

Adds icb_mes.chassis_records_audit (per-field attribute-change trail; model-declared in app.models.mes,
created via create_all here + the cross-schema edited_by_user_id → icb_costings.users FK [SET NULL],
mirroring 0023) + icb_mes.chassis_records.version (Integer NOT NULL DEFAULT 0 — optimistic lock).
Inspector-guarded throughout; up→down→up round-trips clean.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision: str = "0029"
# Re-pointed 0027 -> 0028 by CA1 when v4.36c §3.1 landed (the ship-order swap; was a 0027 placeholder).
down_revision: Union[str, Sequence[str], None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MES = "icb_mes"
_TABLE = "chassis_records_audit"
_USER_FK = "fk_chassis_records_audit_user"


def _mes_tables(bind) -> set:
    return set(sa_inspect(bind).get_table_names(schema=MES))


def _cols(bind, table) -> set:
    return {c["name"] for c in sa_inspect(bind).get_columns(table, schema=MES)}


def _fks(bind, table) -> set:
    return {fk["name"] for fk in sa_inspect(bind).get_foreign_keys(table, schema=MES)}


def upgrade() -> None:
    bind = op.get_bind()

    # 1. chassis_records.version — optimistic lock (ALTER; DEFAULT 0 keeps existing rows valid).
    if "version" not in _cols(bind, "chassis_records"):
        op.add_column("chassis_records",
                      sa.Column("version", sa.Integer(), nullable=False, server_default="0"), schema=MES)

    # 2. chassis_records_audit table (model-declared; create_all builds the same-schema chassis_id FK + indexes).
    if _TABLE not in _mes_tables(bind):
        from app.database import Base
        import app.models.mes  # noqa: F401 — registers ChassisRecordAudit on Base.metadata
        Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables[f"{MES}.{_TABLE}"]])

    # 3. cross-schema edited_by_user_id FK → icb_costings.users (SET NULL — the trail outlives a user delete).
    if _USER_FK not in _fks(bind, _TABLE):
        op.create_foreign_key(
            _USER_FK, _TABLE, "users", ["edited_by_user_id"], ["id"],
            source_schema=MES, referent_schema="icb_costings", ondelete="SET NULL")


def downgrade() -> None:
    bind = op.get_bind()
    if _USER_FK in _fks(bind, _TABLE):
        op.drop_constraint(_USER_FK, _TABLE, schema=MES, type_="foreignkey")
    if _TABLE in _mes_tables(bind):
        op.drop_table(_TABLE, schema=MES)
    if "version" in _cols(bind, "chassis_records"):
        op.drop_column("chassis_records", "version", schema=MES)
