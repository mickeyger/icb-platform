"""workbook_jobs — production_jobs nullable calc FK + source + carrier columns.

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-03

WO v4.21 (Phase 2D-2). Enables workbook-imported production jobs that have no
originating costing calculation:
  - production_jobs.calculation_record_id -> NULLABLE (UNIQUE kept; Postgres UNIQUE
    allows multiple NULLs, so many workbook jobs coexist while quote-born jobs still
    can't share a calc). The cross-schema FK (-> icb_costings.calculations, RESTRICT,
    created in 0003) is unchanged — NULL values simply bypass it.
  - + source ('quote' | 'workbook'), server_default 'quote'.
  - + carrier columns customer_name / description / selling_zar, populated for workbook
    jobs (which have no calc to join through for these fields). Quote-born jobs leave
    them NULL and keep deriving customer/description/selling from the calc join — the
    read-path falls back to the carriers only when the calc is absent.

Additive + reversible. The v4.13 1:1 job<->calc invariant is relaxed; the deferred
calculations column-drop slides 0006+ -> 0007+ (ADR 0005 note).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("production_jobs", "calculation_record_id",
                    existing_type=sa.Integer(), nullable=True, schema="icb_mes")
    op.add_column("production_jobs",
                  sa.Column("source", sa.String(length=16), nullable=False, server_default="quote"),
                  schema="icb_mes")
    op.add_column("production_jobs",
                  sa.Column("customer_name", sa.String(length=128), nullable=True), schema="icb_mes")
    op.add_column("production_jobs",
                  sa.Column("description", sa.String(length=255), nullable=True), schema="icb_mes")
    op.add_column("production_jobs",
                  sa.Column("selling_zar", sa.Float(), nullable=True), schema="icb_mes")


def downgrade() -> None:
    op.drop_column("production_jobs", "selling_zar", schema="icb_mes")
    op.drop_column("production_jobs", "description", schema="icb_mes")
    op.drop_column("production_jobs", "customer_name", schema="icb_mes")
    op.drop_column("production_jobs", "source", schema="icb_mes")
    # NB: restoring NOT NULL requires no NULL calculation_record_id rows present
    # (i.e. workbook jobs cleared first). On a clean/quote-only DB this is a no-op risk.
    op.alter_column("production_jobs", "calculation_record_id",
                    existing_type=sa.Integer(), nullable=False, schema="icb_mes")
