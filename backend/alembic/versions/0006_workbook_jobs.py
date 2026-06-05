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
    them NULL and keep deriving from the calc join (read-path falls back to carriers).

IDEMPOTENT (mirrors 0004's `jobs_impacted` guard): migration 0003 builds the icb_mes
tables via model-driven `create_all`, so on a FRESH DB it already creates these columns
(the ProductionJob model now declares them) and `calculation_record_id` is already
nullable. On a DB migrated at v4.13–v4.20 (pre-0006) it does not. The inspector guards
below let both paths converge — and keep the CI upgrade/downgrade/upgrade round-trip green.

Additive + reversible. The v4.13 1:1 job<->calc invariant is relaxed; the deferred
calculations column-drop slides 0006+ -> 0007+ (ADR 0005 note; ADR 0012).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CARRIERS = (
    ("source", sa.String(length=16), {"nullable": False, "server_default": "quote"}),
    ("customer_name", sa.String(length=128), {"nullable": True}),
    ("description", sa.String(length=255), {"nullable": True}),
    ("selling_zar", sa.Float(), {"nullable": True}),
)


def _pj_columns(bind) -> set:
    return {c["name"] for c in sa_inspect(bind).get_columns("production_jobs", schema="icb_mes")}


def upgrade() -> None:
    bind = op.get_bind()
    # Idempotent: on a fresh DB 0003's model-driven create_all already builds this nullable.
    op.alter_column("production_jobs", "calculation_record_id",
                    existing_type=sa.Integer(), nullable=True, schema="icb_mes")
    have = _pj_columns(bind)
    for name, type_, kw in _CARRIERS:
        if name not in have:
            op.add_column("production_jobs", sa.Column(name, type_, **kw), schema="icb_mes")


def downgrade() -> None:
    bind = op.get_bind()
    have = _pj_columns(bind)
    for name, _type, _kw in reversed(_CARRIERS):
        if name in have:
            op.drop_column("production_jobs", name, schema="icb_mes")
    # NB: restoring NOT NULL requires no NULL calculation_record_id rows present.
    op.alter_column("production_jobs", "calculation_record_id",
                    existing_type=sa.Integer(), nullable=False, schema="icb_mes")
