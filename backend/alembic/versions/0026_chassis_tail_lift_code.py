"""WO v4.36b — chassis_records.tail_lift_code (Migration 0026).

Revision ID: 0026
Revises: 0025
Create Date: 2026-06-22

Adds icb_mes.chassis_records.tail_lift_code (VARCHAR(64), nullable). Part of the chassis-field
unification: the Planning-ack panel previously stored the tail-lift only in the costing chassis_data
JSON blob; it now has an authoritative home on chassis_records so the Chassis page + the Planning-ack
panel share a single source of truth. Inspector-guarded; additive ALTER; up→down→up round-trips clean.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision: str = "0026"
down_revision: Union[str, Sequence[str], None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MES = "icb_mes"


def _cols(bind, table, schema) -> set:
    return {c["name"] for c in sa_inspect(bind).get_columns(table, schema=schema)}


def upgrade() -> None:
    bind = op.get_bind()
    if "tail_lift_code" not in _cols(bind, "chassis_records", MES):
        op.add_column("chassis_records",
                      sa.Column("tail_lift_code", sa.String(length=64), nullable=True), schema=MES)


def downgrade() -> None:
    bind = op.get_bind()
    if "tail_lift_code" in _cols(bind, "chassis_records", MES):
        op.drop_column("chassis_records", "tail_lift_code", schema=MES)
