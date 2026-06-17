"""WO v4.36a §3.1 — chassis_records soft-delete (deleted_at + merged_into_id) (Migration 0025).

Revision ID: 0025
Revises: 0024
Create Date: 2026-06-16

Adds icb_mes.chassis_records.deleted_at (NULL = live) + merged_into_id (→ surviving chassis on an admin
Merge), the soft-delete substrate for §0.10 Merge Chassis. deleted_at is orthogonal to `status` (chosen over
a status='merged_into:{id}' sentinel, which would poison the ~6 status-equality reads incl.
find_anchorless_chassis — §3.0 concern i). Plus a partial index on icb_costings.customers WHERE is_dealer
for the dealer dropdown (§0.7). Inspector-guarded; additive ALTERs; up→down→up round-trips clean.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision: str = "0025"
down_revision: Union[str, Sequence[str], None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MES = "icb_mes"
COSTINGS = "icb_costings"
_DEALER_IDX = "ix_customers_is_dealer"


def _cols(bind, table, schema) -> set:
    return {c["name"] for c in sa_inspect(bind).get_columns(table, schema=schema)}


def _idxs(bind, table, schema) -> set:
    return {i["name"] for i in sa_inspect(bind).get_indexes(table, schema=schema)}


def upgrade() -> None:
    bind = op.get_bind()
    cols = _cols(bind, "chassis_records", MES)
    if "deleted_at" not in cols:
        op.add_column("chassis_records",
                      sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True), schema=MES)
    if "merged_into_id" not in cols:
        op.add_column("chassis_records",
                      sa.Column("merged_into_id", sa.Integer(), nullable=True), schema=MES)
    # §0.7 dealer dropdown perf — partial index over the dealer subset only.
    if _DEALER_IDX not in _idxs(bind, "customers", COSTINGS):
        op.create_index(_DEALER_IDX, "customers", ["id"], schema=COSTINGS,
                        postgresql_where=sa.text("is_dealer"))


def downgrade() -> None:
    bind = op.get_bind()
    if _DEALER_IDX in _idxs(bind, "customers", COSTINGS):
        op.drop_index(_DEALER_IDX, table_name="customers", schema=COSTINGS)
    cols = _cols(bind, "chassis_records", MES)
    if "merged_into_id" in cols:
        op.drop_column("chassis_records", "merged_into_id", schema=MES)
    if "deleted_at" in cols:
        op.drop_column("chassis_records", "deleted_at", schema=MES)
