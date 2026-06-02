"""mes_schema — create the 12 icb_mes tables, cross-schema FKs, the
calculations->production_jobs data move, and the backward-compat view.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-02

WO v4.13 (Phase 2A). Creates the MES domain schema. The 12 tables are
materialised from the SQLAlchemy models (app.models.mes) via a scoped
create_all over an explicit table list — cycle-safe (the MES FK graph is
acyclic) and avoids touching the costing tables' mutually-dependent FKs.

Cross-schema FK constraints (icb_mes -> icb_costings) are added explicitly here
(they are NOT declared on the schema-less costing models). The post-acceptance
MES columns are copied from icb_costings.calculations into production_jobs (a
no-op on an empty dev DB; real work at the future prod migration), and the
backward-compat view icb_costings.v_calculation_records_legacy reconstructs the
old 32-column shape by sourcing the 18 moved columns from production_jobs — so
the view stays correct after the columns are DROPPED in a later migration (0004,
post-UAT; NOT part of this WO).
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MES_TABLES = [
    "production_jobs", "work_orders", "tasks", "sign_offs", "photos", "rework_tickets",
    "planning_slots", "planning_acks", "stock_counts", "discrepancies", "po_suggestions",
    "demand_lines",
]

# The 18 MES-lifecycle columns moved from icb_costings.calculations, in order.
_MOVED_COLUMNS = [
    "pre_job_sent_at", "pre_job_confirmed_at", "job_number_assigned", "repair_phases_json",
    "pre_job_signoff_sales_at", "pre_job_signoff_sales_by", "pre_job_signoff_sales_attestation",
    "pre_job_signoff_production_at", "pre_job_signoff_production_by",
    "pre_job_signoff_production_attestation",
    "planning_acknowledged_at", "planning_acknowledged_by",
    "chassis_eta", "chassis_eta_captured_at", "chassis_eta_captured_by", "chassis_data_json",
    "chassis_received_at", "chassis_received_by",
]

_LEGACY_VIEW = "icb_costings.v_calculation_records_legacy"


def _mes_table_objs():
    from app.database import Base
    import app.models.mes  # noqa: F401  (ensures models are registered)
    return [Base.metadata.tables[f"icb_mes.{n}"] for n in _MES_TABLES]


def upgrade() -> None:
    bind = op.get_bind()
    import app.models.mes as mes_models

    op.execute("CREATE SCHEMA IF NOT EXISTS icb_mes")

    # 1. Create the 12 MES tables (+ their indexes + intra-icb_mes FKs).
    from app.database import Base
    Base.metadata.create_all(bind=bind, tables=_mes_table_objs())

    # 2. Cross-schema FK constraints (icb_mes -> icb_costings).
    for src, col, ref, ondelete in mes_models.CROSS_SCHEMA_FKS:
        op.create_foreign_key(
            f"fk_{src}_{col}", src, ref, [col], ["id"],
            source_schema="icb_mes", referent_schema="icb_costings", ondelete=ondelete,
        )

    # 3. Move post-acceptance data: one production_jobs row per progressed costing.
    #    No-op on an empty calculations table (dev); real on the future prod migration.
    moved = ", ".join(_MOVED_COLUMNS)
    moved_c = ", ".join(f"c.{c}" for c in _MOVED_COLUMNS)
    op.execute(f"""
        INSERT INTO icb_mes.production_jobs
            (calculation_record_id, branch_id, job_number, status, accepted_at, {moved})
        SELECT c.id, c.branch_id, c.job_number_assigned, 'accepted', c.approved_at, {moved_c}
        FROM icb_costings.calculations c
        WHERE c.pre_job_sent_at IS NOT NULL
           OR c.pre_job_signoff_sales_at IS NOT NULL
           OR c.planning_acknowledged_at IS NOT NULL
           OR c.chassis_eta IS NOT NULL
           OR c.job_number_assigned IS NOT NULL
           OR c.status = 'accepted'
    """)

    # 4. Backward-compat view exposing the OLD calculations column shape.
    #    The 18 moved columns are sourced from production_jobs so the view remains
    #    valid after migration 0004 drops them from calculations.
    moved_pj = ",\n            ".join(f"pj.{c}" for c in _MOVED_COLUMNS)
    op.execute(f"""
        CREATE VIEW {_LEGACY_VIEW} AS
        SELECT
            c.id, c.branch_id, c.trailer_type_id, c.user_id, c.customer_id,
            c.dimensions_json, c.result_json, c.created_at, c.approved_at,
            c.approved_by_user_id, c.status, c.decline_reason, c.quote_number, c.is_repair,
            {moved_pj}
        FROM icb_costings.calculations c
        LEFT JOIN icb_mes.production_jobs pj ON pj.calculation_record_id = c.id
    """)


def downgrade() -> None:
    bind = op.get_bind()
    op.execute(f"DROP VIEW IF EXISTS {_LEGACY_VIEW}")
    # Dropping the icb_mes tables drops their cross-schema FK constraints too.
    from app.database import Base
    Base.metadata.drop_all(bind=bind, tables=_mes_table_objs())
